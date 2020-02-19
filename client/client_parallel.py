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

import aiohttp
import asyncio

from multiprocessing import Pool
from time import sleep
from PIL import Image

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, or_, func

from models import Base, BaseStationData, Photo, Probe, ProbeData

import logging
from traceback import format_exc
from schedule import Scheduler



logging.basicConfig(filename='client_parallel.log',
                    filemode='w',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)


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
        logging.debug(exc)

SERVER_LOGIN = "peksha@plantdata.tech"
SERVER_PASSWORD = "pekshapasswd"
SERVER_HOST = "https://dev.plantdata.fermata.tech:5598/api/v2/{}"
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


def create_session(db_file):
    engine = create_engine('sqlite:///{}'.format(db_file))
    Session = sessionmaker(bind=engine)
    session = Session()
    session.execute('pragma foreign_keys=on')
    return session

async def async_read_sensor_data(session, url, dbsession, bsid):
    resp_json = []
    async with session.get(url, timeout=0) as response:
        if response.status == 200:
            logging.debug(["SENSOR {} RESPONSE".format(url)])
            resp = await response.text()
            resp_json = json.loads(resp)
            uuid = resp_json.get("UUID")
            data = resp_json.get("data")
            logging.debug(["UUID", uuid])
            logging.debug(["DATA", data])
            bsrecord = dbsession.query(BaseStationData).filter(BaseStationData.id==bsid).first()
            #dbprobe = dbsession.query(Probe).filter(Probe.uuid==uuid).first()
            #if not dbprobe:
            # Create Probe record
            dbprobe = Probe(uuid=uuid)
            dbsession.add(dbprobe)
            dbsession.commit()

            bsrecord.probes.append(dbprobe)
            dbsession.add(bsrecord)
            dbsession.commit()
                
            for pdata in data:
                newpdata = ProbeData(probe=dbprobe, value=pdata['value'], ptype=pdata['ptype'], label=pdata['label'])
                dbsession.add(newpdata)
                dbsession.commit()
            #basestation
            # Create ProbeData records
        else:
            logging.debug(["NO RESPONSE FROM {}".format(url), response.status])
        return resp_json

    
async def fetch_all_sensors_data(urls, loop, dbsession, bsid):
    async with aiohttp.ClientSession(loop=loop) as session:
        results = await asyncio.gather(*[async_read_sensor_data(session, url, dbsession, bsid) for url in urls], return_exceptions=True)
        return results

    
def send_patch_request(fname, flabel, fcamname, fcamposition, data_id, photo_id, header):
    files = {}
    files['{}'.format(flabel)] = open(fname, 'rb')
    url_str = "data/{}".format(data_id)
    logging.debug("SENDING PATCH REQUEST FOR {} {}".format(data_id, flabel))
    # send camera_name, camera position
    resp = requests.patch(SERVER_HOST.format(url_str), data={"camname": fcamname, "camposition": fcamposition}, headers=header, files=files)
    logging.debug("PATCH RESPONSE STATUS CODE {}".format(resp.status_code))
    if resp.status_code == 200:
        os.unlink(os.path.join("/home/pi", fname))
        session = Session()
        dbphoto = session.query(Photo).filter(Photo.photo_id == photo_id).first()
        if dbphoto:
            dbphoto.uploaded = True
            session.delete(dbphoto)
            session.commit()
            logging.debug("LOCAL PHOTO REMOVED {} {}".format(fname, flabel))
        session.close()

        #print(resp.json())
        return resp.status_code

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
            logging.debug("Trying to reconnect")
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
        # os.mknod("sensor.dat")
        
    with open('bs.dat', 'rb') as f:
        try:
            data = pickle.load(f)
            #logging.debug(data)
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
            logging.debug("Trying to connect")

    newuuid = response.json().get('uuid')
    return newuuid

def post_data(token, bsuuid, take_photos):
    data_read = False
    data_sent = False
    data_cached = False
    logging.debug("Start post_data")
    if not os.path.exists(DATADIR):
        os.makedirs(DATADIR)
    
    if not token:
        logging.debug('Not allowed')
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
        
        for SENSOR in CONFIG_FILE['SENSORS']:
            sensor_urls.append(SENSOR['URL'])
            
        loop = asyncio.get_event_loop()
        async_session = create_session(db_file)
        # Colloecting sensors data
        responses = loop.run_until_complete(fetch_all_sensors_data(sensor_urls, loop, async_session, newdata.id))
        #logging.debug(responses)
        async_session.close()
        
        # Take & process photos
        if take_photos:
            for CAMERA in CONFIG_FILE['CAMERAS']:
                if CAMERA['CAMERA_TYPE'] == "USB":
            
                    v = cv2.VideoCapture(CAMERA['PORTNUM'])
                    v.set(3,1280)
                    v.set(4,960)
                
                    for i in range(15):
                        check, frame = v.read()
                        sleep(1)
        
                    fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
                    showPic = cv2.imwrite(fname, frame)
                    camdata = {"fname": fname, "label": CAMERA["LABEL"], "cameraname": CAMERA["LABEL"], "cameraposition": 1}
                    v.release()
                    logging.debug("Captured {}".format(CAMERA['LABEL']))
    
                    # Check for black images
                    try:
                        fimg = Image.open(camdata['fname'])
                    except:
                        logging.debug("Failed to open image {}, Skipping to the next image".format(camdata['fname']))
                        continue
                    # mean
                    if sum(fimg.convert("L").getextrema())/2 >= LOWLIGHT:
                        cameradata.append(camdata)
                    else:
                        os.unlink(camdata['fname'])
                
                elif CAMERA['CAMERA_TYPE'] == "IP":
                    CAMERA_LOGIN = CAMERA['CAMERA_LOGIN']
                    CAMERA_PASSWORD = CAMERA['CAMERA_PASSWORD']
                    CAMERA_IP = CAMERA['CAMERA_IP']
                    NUMFRAMES = CAMERA['NUMFRAMES']
                    LABEL = CAMERA['LABEL']
                    NUMRETRIES = 3
                    # Turn lights on
                    # /form/IRset
                    ir_data = {"IRmode": 1,
                               "c2bwthr": 20,
                               "bw2cthr": 70,
                               "IRenable": 1,
                               "IRdelay": 3
                               }
                    
                    ir_set = False
                    for n in range(NUMRETRIES):
                        if not ir_set:
                            try:
                                ir_respr = requests.post("http://{}:{}@{}/form/IRset".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), data=ir_data)
                                ir_set = True
                            except:
                                logging.debug("Failed to connect to camera IR SET")
                                sleep(5)
                    if not ir_set:
                        # skip camera
                        logging.debug("NO CONNECTION, SKIPPING TO THE NEXT CAMERA")
                        continue
                    
                    for i in range(0, NUMFRAMES):
                        fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
                        postdata = {"flag": 4,
                                    "existFlag": 1,
                                    "language": "cn",
                                    "presetNum": i + 1
                        }
                        comm_sent = False
                        for n in range(NUMRETRIES):
                            if not comm_sent:
                                try:
                                    r = requests.post("http://{}:{}@{}/form/presetSet".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), data=postdata)
                                    comm_sent = True
                                except:
                                    logging.debug("Failed to connect to camera PRESET SET")
                                    sleep(5)
                            
                        # Delay for camera to get into the proper position
                        sleep(5)
                        rtsp = cv2.VideoCapture("rtsp://{}:{}@{}:554/1/h264major".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
                        # Read 5 frames and save the fifth one
                        # 
                        for j in range(5):
                            check, frame = rtsp.read()
                            sleep(1)
                        showPic = cv2.imwrite(fname, frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
                        logging.debug("CAPTURED {} PICT {}".format(LABEL, i+1))
                        cameradata.append({"fname": fname, "label": LABEL + " {}".format(i+1), "cameraname": LABEL, "cameraposition": i+1})
                        rtsp.release()
                        #sleep(10)
                    # turn lights off
                    ir_data['IRenable'] = 0
                    ir_set = False
                    for n in range(NUMRETRIES):
                        if not ir_set:
                            try:
                                ir_respr = requests.post("http://{}:{}@{}/form/IRset".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), data=ir_data)
                                ir_set = True
                            except:
                                logging.debug("Failed to connect to camera IR SET")
                                sleep(5)

                    # ir_respr = requests.post("http://{}:{}@{}/form/IRset".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), data=ir_data)


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
    
    numretries = 0

    while not data_sent:
        try:
            cacheddata = session.query(BaseStationData).filter(BaseStationData.uploaded.is_(False)).all()
            logging.debug("send data")
            #logging.debug(cacheddata)
            for cd in cacheddata:
                postdata = {'uuid': cd.bs_uuid, 'ts': str(cd.ts), 'probes':[]}
                for pr in cd.probes:
                    probe = {"puuid": pr.uuid, "data": []}
                    for pd in pr.values:
                        if pd.value:
                            pdvalue = float(pdvalue)
                        else:
                            pdvalue = None
                        probe_data  = {"ptype":pd.ptype, "value":pdvalue, "label": pd.label}
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
                        cachedphotos = session.query(Photo).filter(Photo.uploaded.is_(False)).all()
                        p = Pool(processes=10)
                        argslist = []
                        for i, f in enumerate(cachedphotos):
                            if f.bs:
                                if f.bs.remote_data_id:
                                    argslist.append([f.photo_filename, f.label, f.camname, f.camposition, f.bs.remote_data_id, f.photo_id, head])
                            
                        logging.debug("START LOOP")
                        loopdata = p.starmap(send_patch_request, argslist)
                        p.close()
                        totalcount = loopdata.count(200)
                        # Обрабатывать неотправленные фото, не удалять их
                        # и не удалять отправленные данные
                        # помечать данные как sent
                        # и после отправки всех фото
                        # если у данных не осталось отправленных фото, от удалять
                        logging.debug("PHOTOS SENT {}".format(totalcount))
                        # remove cached data here
            data_sent=True
            data_uploaded = session.query(BaseStationData).filter(BaseStationData.uploaded.is_(True)).all()
            for du in data_uploaded:
                session.delete(du)
            session.commit()


        except requests.exceptions.ConnectionError:
            sleep(2)
            numretries =+ 1
            logging.debug("Network error, trying to connect")

if __name__ == '__main__':

    base_station_uuid, token = get_base_station_uuid()

    if not base_station_uuid:
        token = get_token()
        base_station_uuid = register_base_station(token)

    scheduler = SafeScheduler()
    scheduler.every(5).minutes.do(post_data, token, base_station_uuid, False)
    #scheduler.every(60).minutes.do(post_data, token, base_station_uuid, True)
    logging.debug(base_station_uuid)
    #post_data(token, base_station_uuid, False)
    #sys.exit(1)
    while 1:
        scheduler.run_pending()
        sleep(1)

        
