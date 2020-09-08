#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
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
from traceback import format_exc
from schedule import Scheduler



logging.basicConfig(filename='client_parallel.log',
                    filemode='w',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)
logger = logging.getLogger(__name__)

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
SERVER_HOST = CONFIG_FILE['SERVER_HOST']
db_file = CONFIG_FILE['DB_FILE']
DATADIR = CONFIG_FILE['DATADIR']
LOWLIGHT = CONFIG_FILE['LOWLIGHT']

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
    # Move all this to lora_listener
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
    # Move to lora_listener
    async with aiohttp.ClientSession(loop=loop) as session:
        results = await asyncio.gather(*[async_read_sensor_data(session, url, dbsession, bsid) for url in urls], return_exceptions=True)
        return results

    
def send_patch_request(fname, flabel, fcamname, fcamposition, data_id, photo_id, header):
    files = {}
    files['{}'.format(flabel)] = open(fname, 'rb')
    logger.debug("FILESIZE {}".format(os.stat(fname).st_size))
    url_str = "data/{}".format(data_id)
    logger.debug("SENDING PATCH REQUEST FOR {} {}".format(data_id, flabel))
    logger.debug("SENDING FILE {}".format(files))
    # send camera_name, camera position
    #resp = requests.patch(SERVER_HOST.format(url_str), data={"camname": fcamname, 'flabel': flabel, "camposition": fcamposition, "recognize": False}, headers=header, files=files)
    resp = requests.patch(SERVER_HOST.format(url_str), data={"camname": fcamname, 'flabel': flabel, "camposition": fcamposition}, headers=header, files=files)
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
    
    # Move to lora listener
    # 
    latestdata = session.query(BaseStationData).filter(BaseStationData.bs_uuid==sensordata['uuid']).order_by(BaseStationData.ts.desc()).first()
    # Move to lora listener
    

    if CONFIG_FILE:
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
    
    if take_photos:
        files = {}
        # Take newdata from the DB
        for i, d in enumerate(cameradata):
            newphoto = Photo(bs=latestdata, photo_filename=d['fname'], label=d["label"], camname=d["cameraname"], camposition=d["cameraposition"])
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
            cacheddata = session.query(BaseStationData).filter(BaseStationData.uploaded.is_(False)).all()
            logger.debug("send data")
            #logger.debug(cacheddata)
            for cd in cacheddata:
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
                        cachedphotos = session.query(Photo).filter(Photo.uploaded.is_(False)).all()
                        loopdata = []
                        for i, f in enumerate(cachedphotos):
                            if f.bs:
                                if f.bs.remote_data_id:
                                    loopdata.append(send_patch_request(f.photo_filename, f.label, f.camname, f.camposition, f.bs.remote_data_id, f.photo_id, head))
                        
                        logger.debug(["RESULTS STATUSES", loopdata])
                        # Обрабатывать неотправленные фото, не удалять их
                        # и не удалять отправленные данные
                        # помечать данные как sent
                        # и после отправки всех фото
                        # если у данных не осталось отправленных фото, от удалять
                        logger.debug("PHOTOS SENT {}".format(len(loopdata)))
                        # remove cached data here
            data_sent=True
            data_uploaded = session.query(BaseStationData).filter(BaseStationData.uploaded.is_(True)).all()
            for du in data_uploaded:
                session.delete(du)
            session.commit()


        except requests.exceptions.ConnectionError:
            sleep(2)
            logger.debug("Network error, trying to connect, retry {}".format(numretries))
            numretries = numretries - 1

if __name__ == '__main__':
    base_station_uuid, token = get_base_station_uuid()
    print([base_station_uuid, token])
    if not base_station_uuid:
        token = get_token()
        base_station_uuid = register_base_station(token)
 
    scheduler = SafeScheduler()
    scheduler.every(5).minutes.do(post_data, token, base_station_uuid, False)
    #scheduler.every(120).minutes.do(post_data, token, base_station_uuid, True)
    logger.debug(base_station_uuid)
    #post_data(token, base_station_uuid, False)
    #sys.exit(1)
    while 1:
        scheduler.run_pending()
        sleep(1)

        
