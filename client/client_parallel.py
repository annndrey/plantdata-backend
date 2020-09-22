#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

sys.path.append('/home/pi/lib/python3.5/site-packages')

import requests
import pickle
import os
import json
import cv2
import shutil
import uuid
import datetime
import pytz
import functools
import yaml
import copy

import aiohttp
import asyncio

from multiprocessing import Pool
from time import sleep
from PIL import Image

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, or_, func

from models import Base, BaseStationData, Photo, Probe, ProbeData

import logging
from logging.handlers import RotatingFileHandler

from traceback import format_exc
from schedule import Scheduler



logger = logging.getLogger("PlantData Client Log")
logger.setLevel(logging.DEBUG)
handler = RotatingFileHandler("client_parallel.log", mode='a', maxBytes=1000000, backupCount=5, encoding='utf-8', delay=0)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
print(logger)
logger.debug("App started")

# Some useful camera commands
# http://XXX.XXX.XXX.XXX/cgi-bin/hi3510/preset.cgi?-act=set&-status=1&-number=[0-7] :: установить позицию
# http://XXX.XXX.XXX.XXX/cgi-bin/hi3510/ptzctrl.cgi?-step=1&-act=down :: Переход на один шаг вниз
# http://XXX.XXX.XXX.XXX/cgi-bin/hi3510/preset.cgi?-act=set&-status=0&-number=[0-7] :: отключить позицию
# http://XXX.XXX.XXX.XXX/cgi-bin/hi3510/preset.cgi?-act=goto&-status=1&-number=[0-7] :: перейти к заданной позиции
# http://192.168.1.225/web/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act=zoomout&-speed=45 zoom

tz = pytz.timezone('Europe/Moscow')

class SafeScheduler(Scheduler):
    """
    An implementation of Scheduler that catches jobs that fail, logs their
    exception tracebacks as errors, optionally reschedules the jobs for their
    next run time, and keeps going.
    
    Use this to run jobs that may or may not crash without worrying about
    whether other jobs will run or if they'll crash the entire script.
    """

    def __init__(self, reschedule_on_failure=True):
        """
        If reschedule_on_failure is True, jobs will be rescheduled for their
        next run as if they had completed successfully. If False, they'll run
        on the next run_pending() tick.
        """
        self.reschedule_on_failure = reschedule_on_failure
        super().__init__()
        
        def _run_job(self, job):
            try:
                super()._run_job(job)
            except Exception:
                logger.error(format_exc())
                job.last_run = datetime.datetime.now()
                job._schedule_next_run()



with open("config.yaml", 'r') as stream:
    try:
        CONFIG_FILE = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        logger.debug(exc)


SERVER_LOGIN = CONFIG_FILE['SERVER_LOGIN']
SERVER_PASSWORD = CONFIG_FILE['SERVER_PASSWORD']
SERVER_HOST = "https://dev.plantdata.fermata.tech:5598/api/v2/{}"

TEST_HOST = "http://testapi.me:9898/api/v2/{}"
db_file = 'localdata.db'
DATADIR = "picts"
LOWLIGHT = 10
# Weights
OFFSET0 = 96249
SCALE0 = 452
OFFSET1 = 25400
SCALE1 = 560
OFFSET2 = 49000
SCALE2 = 614
OFFSET3 = 60600
SCALE3 = 576
OFFSET4 = 123553
SCALE4 = 639

engine = create_engine('sqlite:///{}'.format(db_file))
Session = sessionmaker(bind=engine)
session = Session()

Base.metadata.create_all(engine, checkfirst=True)


def collect_pictures(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP, LABEL, NUMFRAMES, NUMRETRIES):
    cameradata = []
    # Ping camera
    try:
        r = requests.put("http://{}".format(CAMERA_IP))
    except:
        logger.debug(["No connection with {} {}, skipping".format(LABEL, CAMERA_IP)])
        return 
        
    for i in range(NUMFRAMES):
        fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
        putdata = {"Param1": i}
        comm_sent = False
        for n in range(NUMRETRIES):
            if not comm_sent:
                try:
                    r = requests.put("http://{}:{}@{}/PTZ/1/Presets/Goto".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), data=putdata)
                    comm_sent = True
                except Exception as e:
                    logger.debug("Failed to connect to camera PRESET SET")
                    logger.debug(e)
                    sleep(5)
        # Delay for camera to get into the proper position
        if comm_sent:
            sleep(5)
            rtsp = cv2.VideoCapture("rtsp://{}:{}@{}:554/live/0/MAIN".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
            # Read 5 frames and save the fifth one
            # 
            for j in range(5):
                check, frame = rtsp.read()
                sleep(1)
            showPic = cv2.imwrite(fname, frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
            logger.debug("CAPTURED {} PICT {}".format(LABEL, i+1))
            cameradata.append({"fname": fname, "label": LABEL + " {}".format(i+1), "cameraname": LABEL, "cameraposition": i+1})
            rtsp.release()
            #sleep(10)
    return cameradata


def create_session(db_file):
    engine = create_engine('sqlite:///{}'.format(db_file))
    Session = sessionmaker(bind=engine)
    session = Session()
    session.execute('pragma foreign_keys=on')
    return session

async def async_read_sensor_data(session, url, dbsession, bsid):
    resp_json = []
    pkl_fname = "{}.pkl".format(url.replace("/", "~"))
    try:
        async with session.get(url, timeout=10) as response:
            if response.status == 200:
                logger.debug(["SENSOR {} RESPONSE".format(url)])
                resp = await response.text()
                resp_json = json.loads(resp)
                if not os.path.exists(pkl_fname):
                    pkl_data = copy.deepcopy(resp_json)
                    for d in pkl_data['data']:
                        d['value'] = 0
                    with open(pkl_fname, 'wb') as f:
                        pickle.dump(pkl_data, f)
    except:
        logger.debug(["NO RESPONSE FROM {}".format(url)])
        f = open(pkl_fname, 'rb')
        resp_json = pickle.load(f)
            
    uuid = resp_json.get("UUID")
    data = resp_json.get("data")
                
    logger.debug(["UUID", uuid])
    logger.debug(["DATA", data])
    bsrecord = dbsession.query(BaseStationData).filter(BaseStationData.id==bsid).first()
    # Create Probe record
    dbprobe = Probe(uuid=uuid)
    dbsession.add(dbprobe)
    dbsession.commit()
    
    bsrecord.probes.append(dbprobe)
    dbsession.add(bsrecord)
    dbsession.commit()
                
    for pdata in data:
        if not pdata['value']:
            pdata['value'] = 0
        newpdata = ProbeData(probe=dbprobe, value=pdata['value'], ptype=pdata['ptype'], label=pdata['label'])
        dbsession.add(newpdata)
        dbsession.commit()
        #basestation
        # Create ProbeData records
        
    return resp_json

    
async def fetch_all_sensors_data(urls, loop, dbsession, bsid):
    async with aiohttp.ClientSession(loop=loop) as session:
        results = await asyncio.gather(*[async_read_sensor_data(session, url, dbsession, bsid) for url in urls], return_exceptions=True)
        return results

    
def send_patch_request(fname, flabel, fcamname, fcamposition, data_id, photo_id, header):
    resp = None
    numretries = 5
    files = {}
    img = Image.open(fname)
    logger.debug(("IMAGEFILE", fname, img.format, "%dx%d" % img.size, img.mode, os.stat(fname).st_size))
    files['{}'.format(flabel)] = open(fname, 'rb')
    logger.debug("FILESIZE {}".format(os.stat(fname).st_size))
    url_str = "data/{}".format(data_id)
    logger.debug("SENDING PATCH REQUEST FOR {} {}".format(data_id, flabel))
    logger.debug("SENDING FILE {}".format(files))
    # send camera_name, camera position
    #resp = requests.patch(SERVER_HOST.format(url_str), data={"camname": fcamname, 'flabel': flabel, "camposition": fcamposition, "recognize": False}, headers=header, files=files)
    while numretries > 0:
        logger.debug("{} RETRIES LEFT".format(numretries))
        
        try:
            logger.debug(["DATA", {"camname": fcamname, 'flabel': flabel, "camposition": fcamposition}, header, files])
            # resp = requests.patch(TEST_HOST.format(url_str), data={"camname": fcamname, 'flabel': flabel, "camposition": fcamposition}, headers=header, files=files, timeout=(40, 40))
            resp = requests.patch(SERVER_HOST.format(url_str), data={"camname": fcamname, 'flabel': flabel, "camposition": fcamposition}, headers=header, files=files, timeout=(40, 40))
            logger.debug("PATCH RESPONSE STATUS CODE {}".format(resp.status_code))
            if resp.status_code == 200:
                os.unlink(os.path.join("/home/pi", fname))
                session = Session()
                dbphoto = session.query(Photo).filter(Photo.photo_id == photo_id).first()
                if dbphoto:
                    dbphoto.uploaded = True
                    session.delete(dbphoto)
                    session.commit()
                    logger.debug("LOCAL PHOTO REMOVED {} {}".format(fname, flabel))
                session.close()
                
                #print(resp.json())
                return resp.status_code
            else:
                logger.debug("Retrying... Response was {}".format(resp.status_code))
                numretries = numretries - 1
                sleep(3)
        except Exception as e:
            print("type error: " + str(e))
            #return None
            numretries = numretries - 1
    return resp
            
def get_token():
    data_sent = False
    login_data = {"username": SERVER_LOGIN,
                  "password": SERVER_PASSWORD
    }
    token = None
    while not data_sent:
        print("SEND DATA")
        try:
            res = requests.post(SERVER_HOST.format("token"), json=login_data)
            data_sent = True
        except requests.exceptions.ConnectionError:
            logger.debug("Trying to reconnect")
            sleep(3)
            
    if res.status_code == 200:
        token = res.json().get('token')
    return token

def register_base_station(token, suuid=None):
    base_station_uuid = suuid
    with open('bs.dat', 'wb') as f:
        try:
            if not base_station_uuid:
                base_station_uuid = new_base_station(token)
            data = {'uuid': base_station_uuid, 'token': token}
            pickle.dump(data, f)
        except:
            pass
    return base_station_uuid


def get_base_station_uuid():
    base_station_uuid = None
    token = None

    if not os.path.exists('bs.dat'):
        open('bs.dat', 'w').close()
        
    with open('bs.dat', 'rb') as f:
        try:
            data = pickle.load(f)
            #logger.debug(data)
            base_station_uuid = data['uuid']
            token = data['token']
        except:
            pass
    return base_station_uuid, token

def new_base_station(token):
    data_sent = False

    if not token:
        return "Not allowed"
    head = {'Authorization': 'Bearer ' + token}
    location = {'lat': 111, 'lon': 111, 'address': 'test address 1'}
    while not data_sent:
        try:
            response = requests.post(SERVER_HOST.format("sensors"), json=location, headers=head)
            data_sent = True
        except requests.exceptions.ConnectionError:
            sleep(2)
            logger.debug("Trying to connect")

    newuuid = response.json().get('uuid')
    return newuuid

def post_data(token, bsuuid, take_photos):
    data_read = False
    data_sent = False
    data_cached = False
    logger.debug("Start post_data")
    if not os.path.exists(DATADIR):
        os.makedirs(DATADIR)
    
    if not token:
        logger.debug('Not allowed')
    head = {'Authorization': 'Bearer ' + token}

    cameradata = []
    sensordata = {}
    sensordata['uuid'] = bsuuid
    sensordata['TS'] = datetime.datetime.now(tz)
    
    newdata = BaseStationData(bs_uuid=sensordata['uuid'], ts=sensordata['TS'])
    session.add(newdata)
    session.commit()
    

    if CONFIG_FILE:
        # Read sensors data
        sensor_urls = []
        if CONFIG_FILE['SENSORS']:
            for SENSOR in CONFIG_FILE['SENSORS']:
                sensor_urls.append(SENSOR['URL'])
            
        loop = asyncio.get_event_loop()
        async_session = create_session(db_file)
        # Collecting sensors data
        responses = loop.run_until_complete(fetch_all_sensors_data(sensor_urls, loop, async_session, newdata.id))
        #logger.debug(responses)
        async_session.close()
        
        # Take & process photos
        if take_photos:
            for CAMERA in CONFIG_FILE['CAMERAS']:
                
                if CAMERA['CAMERA_TYPE'] == "IP":
                    CAMERA_LOGIN = CAMERA['CAMERA_LOGIN']
                    CAMERA_PASSWORD = CAMERA['CAMERA_PASSWORD']
                    CAMERA_IP = CAMERA['CAMERA_IP']
                    NUMFRAMES = CAMERA['NUMFRAMES']
                    LABEL = CAMERA['LABEL']
                    NUMRETRIES = 3
                    photos = collect_pictures(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP, LABEL, NUMFRAMES, NUMRETRIES)
                    if photos:
                        cameradata.extend(photos)
                    #camera_is_online = False
                    #for i in range(NUMFRAMES):
                    #    fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
                    #    putdata = {"Param1": i}
                    #    comm_sent = False
                    #    for n in range(NUMRETRIES):
                    #        if not comm_sent:
                    #            try:
                    #                r = requests.put("http://{}:{}@{}/PTZ/1/Presets/Goto".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), data=putdata)
                    #                comm_sent = True
                    #                camera_is_online = True
                    #            except Exception as e:
                    #                logger.debug("Failed to connect to camera PRESET SET")
                    #                logger.debug(e)
                    #                sleep(5)
                    #    if not comm_sent:
                    #        break
                    #    else:
                    #        # Delay for camera to get into the proper position
                    #        sleep(5)
                    #        rtsp = cv2.VideoCapture("rtsp://{}:{}@{}:554/live/0/MAIN".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
                    #        # Read 5 frames and save the fifth one
                    #        # 
                    #        for j in range(5):
                    #            check, frame = rtsp.read()
                    #            sleep(1)
                    #        showPic = cv2.imwrite(fname, frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
                    #        logger.debug("CAPTURED {} PICT {}".format(LABEL, i+1))
                    #        cameradata.append({"fname": fname, "label": LABEL + " {}".format(i+1), "cameraname": LABEL, "cameraposition": i+1})
                    #        rtsp.release()
                    #        #sleep(10)



    if take_photos:
        files = {}
        for i, d in enumerate(cameradata):
            newphoto = Photo(bs=newdata, photo_filename=d['fname'], label=d["label"], camname=d["cameraname"], camposition=d["cameraposition"])
            session.add(newphoto)
            session.commit()
    else:
        files = None
        
    # All data saved
    # Now sending all cached data to the server
    
    numretries = 3
    
    #while not data_sent:
    if numretries > 0:
        try:
            cacheddata = session.query(BaseStationData).filter(or_(BaseStationData.uploaded.is_(False), BaseStationData.photos_uploaded.is_(False))).all()
            logger.debug("send data")
            #logger.debug(cacheddata)
            for cd in cacheddata:
                if not cd.uploaded:
                    postdata = {'uuid': cd.bs_uuid, 'ts': str(cd.ts), 'probes':[]}
                    for pr in cd.probes:
                        probe = {"puuid": pr.uuid, "data": []}
                        for pd in pr.values:
                            if pd.value is not None:
                                probe_data  = {"ptype":pd.ptype, "value":float(pd.value), "label": pd.label}
                                probe['data'].append(probe_data)
                        postdata['probes'].append(probe)
                    print(json.dumps(postdata, indent=4))
                    resp = requests.post(SERVER_HOST.format("data"), json=postdata, headers=head)
                    if resp.status_code == 201:
            
                        resp_data = json.loads(resp.text)
                        cd.remote_data_id = resp_data['id']
                        cd.uploaded = True
                        session.add(cd)
                        session.commit()
                    
                # Send all cached photos
                if take_photos:
                    cachedphotos = cd.photos
                    loopdata = []
                    for i, f in enumerate(cachedphotos):
                        if f.bs:
                            if f.bs.remote_data_id:
                                logger.debug("Sending patch request {i}")
                                patch_res = send_patch_request(f.photo_filename, f.label, f.camname, f.camposition, f.bs.remote_data_id, f.photo_id, head)
                                loopdata.append(patch_res)
                        
                    logger.debug(["RESULTS STATUSES", loopdata])
                    if len(set(loopdata)) == 1:
                        cd.photos_uploaded = True
                        session.add(cd)
                        session.commit()
                            
                    # Обрабатывать неотправленные фото, не удалять их
                    # и не удалять отправленные данные
                    # помечать данные как sent
                    # и после отправки всех фото
                    # если у данных не осталось отправленных фото, от удалять
                    logger.debug("PHOTOS SENT {}".format(len(loopdata)))
                    # remove cached data here
            data_sent=True
            data_uploaded = session.query(BaseStationData).filter(BaseStationData.uploaded.is_(True)).filter(BaseStationData.photos_uploaded.is_(True)).all()
            for du in data_uploaded:
                session.delete(du)
            session.commit()


        except requests.exceptions.ConnectionError:
            sleep(2)
            logger.debug("Network error, trying to connect, retry {}".format(numretries))
            numretries = numretries - 1

if __name__ == '__main__':
    base_station_uuid, token = get_base_station_uuid()
    logger.debug(("App started", [base_station_uuid, token]))
    if not base_station_uuid:
        token = get_token()
        base_station_uuid = register_base_station(token)
 
    scheduler = SafeScheduler()
    #scheduler.every(5).minutes.do(post_data, token, base_station_uuid, False)
    scheduler.every(120).minutes.do(post_data, token, base_station_uuid, True)
    logger.debug(base_station_uuid)
    #post_data(token, base_station_uuid, True)
    #sys.exit(1)
    while 1:
        scheduler.run_pending()
        sleep(1)

        
