#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

#sys.path.append('/home/pi/lib/python3.5/site-packages')

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

from onvif import ONVIFCamera



logger = logging.getLogger("PlantData Client Log")
logger.setLevel(logging.DEBUG)
handler = RotatingFileHandler("client_parallel.log", mode='a', maxBytes=1000000, backupCount=5, encoding='utf-8', delay=0)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
print(logger)
logger.debug("App started")


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
db_file = CONFIG_FILE['DB_FILE']
DATADIR = CONFIG_FILE['DATADIR']
LOWLIGHT = CONFIG_FILE['LOWLIGHT']
EXCLUDE_POS = CONFIG_FILE['EXCLUDE_POS']
EXCLUDE_RANGE = []
for p in EXCLUDE_POS.split(","):
    if "-" in p:
        pr = p.split("-")
        for n in range(int(pr[0]), int(pr[1])+1):
            EXCLUDE_RANGE.append(n)
    else:
        EXCLUDE_RANGE.append(int(p))
        


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


CAM_WSDL = ".local/lib/python3.7/site-packages/wsdl"

def collect_pictures(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP, LABEL, NUMFRAMES, NUMRETRIES):
    cameradata = []
    # Ping camera
    try:
        #r = requests.put("http://{}".format(CAMERA_IP))
        cam = ONVIFCamera(CAMERA_IP, 80, CAMERA_LOGIN, CAMERA_PASSWORD, CAM_WSDL)
        media = cam.create_media_service()
        ptz = cam.create_ptz_service()
        media_profile = media.GetProfiles()[0]
        request = ptz.create_type('GetConfigurationOptions')
        request.ConfigurationToken = media_profile.PTZConfiguration.token
        ptz_configuration_options = ptz.GetConfigurationOptions(request)
        ptzconf = ptz_configuration_options
        ptz_status = ptz.GetStatus({'ProfileToken': media_profile.token})
        req = ptz.create_type('ContinuousMove')
        req.ProfileToken = media_profile.token
        
    except:
        logger.debug(["No connection with {} {}, skipping".format(LABEL, CAMERA_IP)])
        return 
        
    for i in range(NUMFRAMES):
        fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
        #putdata = {"Param1": i}
        comm_sent = False
        if i+1 not in EXCLUDE_RANGE:
            for n in range(NUMRETRIES):
                if not comm_sent:
                    try:
                        r = ptz.create_type('GotoPreset')
                        r.ProfileToken = media_profile.token
                        r.PresetToken = str(i+1)
                        ptz.GotoPreset(r)
                        sleep(1)
                        comm_sent = True
                    except Exception as e:
                        logger.debug("Failed to connect to camera PRESET SET")
                        logger.debug(e)
                        sleep(5)
            # Delay for camera to get into the proper position
            if comm_sent:
                rtsp = cv2.VideoCapture("rtsp://{}:{}@{}:554/Streaming/Channels/1".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
                # Read 5 frames and save the fifth one
                # 
                for j in range(5):
                    check, frame = rtsp.read()
                    sleep(1)
                # Skip night images
                #
                blur = cv2.blur(frame, (5, 5))
                #if max(cv2.mean(blur)) > 130:
                showPic = cv2.imwrite(fname, frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
                logger.debug("CAPTURED {} PICT {}".format(LABEL, i+1))
                logger.debug("PICT BRIGHTNESS {}".format(max(cv2.mean(blur))))
                cameradata.append({"fname": fname, "label": LABEL + " {}".format(i+1), "cameraname": LABEL, "cameraposition": i+1, "ts": datetime.datetime.now()})
                #else:
                #    logger.debug("SKIPPING {} PICT {}, TOO DARK".format(LABEL, i+1))
                    
                rtsp.release()
                #sleep(10)
    # Go to the first position
    r = ptz.create_type('GotoPreset')
    r.ProfileToken = media_profile.token
    r.PresetToken = str(1)
    ptz.GotoPreset(r)
               
    return cameradata


def create_session(db_file):
    engine = create_engine('sqlite:///{}'.format(db_file))
    Session = sessionmaker(bind=engine)
    session = Session()
    session.execute('pragma foreign_keys=on')
    return session

    
def send_patch_request(fname, flabel, fcamname, fcamposition, data_id, photo_id, photo_ts, header):
    files = {}
    files['{}'.format(flabel)] = open(fname, 'rb')
    logger.debug("FILESIZE {}".format(os.stat(fname).st_size))
    url_str = "data/{}".format(data_id)
    logger.debug("SENDING PATCH REQUEST FOR {} {}".format(data_id, flabel))
    logger.debug("SENDING FILE {}".format(files))
    # send camera_name, camera position
    #resp = requests.patch(SERVER_HOST.format(url_str), data={"camname": fcamname, 'flabel': flabel, "camposition": fcamposition, "recognize": False}, headers=header, files=files)
    resp = requests.patch(SERVER_HOST.format(url_str), data={"camname": fcamname, 'flabel': flabel, "camposition": fcamposition, "recognize": True, "photo_ts": photo_ts}, headers=header, files=files)
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
        logging.debug("SEND DATA")
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
            newphoto = Photo(bs=latestdata, photo_filename=d['fname'], label=d["label"], camname=d["cameraname"], camposition=d["cameraposition"], ts=d['ts'])
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
            for pd in cacheddata:
                logging.debug("*"*80)
                postdata = {'uuid': bsuuid, 'ts': str(pd.ts), 'probes':[]}
                    
                for pr in pd.probes:
                    probe = {"puuid": pr.uuid, "data": []}
                    for prb in pr.values:
                        if prb.value is not None:
                            probe_data  = {"ptype":prb.ptype, "value":float(prb.value), "label": prb.label, "plabel": pr.plabel}
                            probe['data'].append(probe_data)
                postdata['probes'].append(probe)
                logging.debug(json.dumps(postdata, indent=4))
                resp = requests.post(SERVER_HOST.format("data"), json=postdata, headers=head)
                if resp.status_code == 201:
                    resp_data = json.loads(resp.text)

                    pd.remote_data_id = resp_data['id']
                    pd.uploaded = True
                    session.add(pd)
                    session.commit()
                        
                    # Send all cached photos
                    if take_photos:
                        cachedphotos = session.query(Photo).filter(Photo.uploaded.is_(False)).all()
                        loopdata = []
                        for i, f in enumerate(cachedphotos):
                            if f.bs:
                                if f.bs.remote_data_id:
                                    loopdata.append(send_patch_request(f.photo_filename, f.label, f.camname, f.camposition, f.bs.remote_data_id, f.photo_id, f.ts, head))
                                
                        logger.debug(["RESULTS STATUSES", loopdata])

            data_sent=True
            data_uploaded = session.query(BaseStationData).filter(BaseStationData.uploaded.is_(True)).all()
            for du in data_uploaded:
                session.delete(du)
            session.commit()
            logging.debug("DATA POSTED")

        except requests.exceptions.ConnectionError:
            sleep(2)
            logger.debug("Network error, trying to connect, retry {}".format(numretries))
            numretries = numretries - 1

if __name__ == '__main__':
    base_station_uuid, token = get_base_station_uuid()
    logging.debug([base_station_uuid, token])
    if not base_station_uuid:
        token = get_token()
        base_station_uuid = register_base_station(token)
 
    scheduler = SafeScheduler()
    collect_data = scheduler.every(60).minutes.do(post_data, token, base_station_uuid, False)
    # 45 min to collect, 110 min to send + 10 additional min just to be sure
    collect_photos = scheduler.every(100).minutes.do(post_data, token, base_station_uuid, True)
    logger.debug(base_station_uuid)
    # first run
    collect_data.run()
    #collect_photos.run()
    #post_data(token, base_station_uuid, True)
    #sys.exit(1)
    while 1:
        scheduler.run_pending()
        sleep(1)

        
