#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

sys.path.append('/home/pi/lib/python3.5/site-packages')

import requests
import pickle
import os
import serial
import json
import cv2
import shutil
import uuid
import datetime
import pytz
import functools
import yaml
import schedule
import logging

from multiprocessing import Pool

#from picamera import PiCamera
from time import sleep
from PIL import Image

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, or_, func

from models import Base, SensorData, Photo
import logging


logging.basicConfig(filename='client_parallel.log',
                    filemode='w',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)


#logging.basicConfig()
#logging.getLogger().setLevel(logging.DEBUG)
#requests_log = logging.getLogger("requests.packages.urllib3")
#requests_log.setLevel(logging.DEBUG)
#requests_log.propagate = True

# Some useful camera commands
# http://XXX.XXX.XXX.XXX/cgi-bin/hi3510/preset.cgi?-act=set&-status=1&-number=[0-7] :: установить позицию
# http://XXX.XXX.XXX.XXX/cgi-bin/hi3510/ptzctrl.cgi?-step=1&-act=down :: Переход на один шаг вниз
# http://XXX.XXX.XXX.XXX/cgi-bin/hi3510/preset.cgi?-act=set&-status=0&-number=[0-7] :: отключить позицию
# http://XXX.XXX.XXX.XXX/cgi-bin/hi3510/preset.cgi?-act=goto&-status=1&-number=[0-7] :: перейти к заданной позиции
# http://192.168.1.225/web/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act=zoomout&-speed=45 zoom


tz = pytz.timezone('Europe/Moscow')

try:
    ser = serial.Serial('/dev/ttyACM0', 9600, timeout=5)
except:
    ser = serial.Serial('/dev/ttyACM1', 9600, timeout=5)



with open("config.yaml", 'r') as stream:
    try:
        CAMERA_CONFIG = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        logging.debug(exc)

SERVER_LOGIN = "plantuser@plantdata.com"
SERVER_PASSWORD = "plantpassword"
SERVER_HOST = "https://plantdata.fermata.tech:5498/api/v1/{}"
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

def send_patch_request(fname, flabel, data_id, photo_id, header):
    files = {}
    files['{}'.format(flabel)] = open(fname, 'rb')
    url_str = "data/{}".format(data_id)
    logging.debug("SENDING PATCH REQUEST FOR {} {}".format(data_id, flabel))
    
    resp = requests.patch(SERVER_HOST.format(url_str), files=files, headers=header)
    if resp.status_code == 200:
        os.unlink(fname)
        session = Session()
        dbphoto = session.query(Photo).filter(Photo.photo_id == photo_id).first()
        if dbphoto:
            #dbphoto.uploaded = True
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
        try:
            res = requests.post(SERVER_HOST.format("token"), json=login_data)
            data_sent = True
        except requests.exceptions.ConnectionError:
            logging.debug("Trying to reconnect")
            sleep(3)
            
    if res.status_code == 200:
        token = res.json().get('token')
    return token


def register_sensor(token):
    sensor_uuid = None
    with open('sensor.dat', 'wb') as f:
        try:
            sensor_uuid = new_sensor(token)
            data = {'uuid': sensor_uuid, 'token': token}
            pickle.dump(data, f)
        except:
            pass
    return sensor_uuid


def get_sensor_uuid():
    sensor_uuid = None
    token = None

    if not os.path.exists('sensor.dat'):
        open('sensor.dat', 'w').close()
        # os.mknod("sensor.dat")
        
    with open('sensor.dat', 'rb') as f:
        try:
            data = pickle.load(f)
            logging.debug(data)
            sensor_uuid = data['uuid']
            token = data['token']
        except:
            pass
    return sensor_uuid, token

def new_sensor(token):
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

def tryserial(ser):
    try:
        bufferstr = ""
        for i in range(3):
            bufferstr = bufferstr + ser.readline().decode("utf-8")
            sleep(2)
        serialdata = bufferstr.split("\n")[-2]
        serialdata = serialdata.replace("'", '"')
        serialdata = serialdata.replace("CO2", '"CO2"')
        serialdata = serialdata.replace(", ,", ", ")
        serialdata = serialdata.replace(", }", "} ")
        serialdata = serialdata.replace("nan", "-1")
        logging.debug(serialdata)
        serialdata = json.loads(serialdata)
        logging.debug("data read")
    except Exception as e:
        ser.close()
        logging.debug("json next try {}".format(repr(e)))
        sleep(10)
        ser = serial.Serial('/dev/ttyACM0',9600)
        # toss any data already received, see
        # http://pyserial.sourceforge.net/pyserial_api.html#serial.Serial.flushInput
        return tryserial(ser)
    else:
        logging.debug("json read")
        return serialdata

def readserialdata(ser, isread):
    # read a line until the end to skip incomplete data
    #sleep(1)
    #lastchar = ser.read_until(b'\n')
    #ser.flushInput()
    #ser.flushOutput()
    # read complete line
    #logging.debug(lastchar)
    # serialdata = #ser.readline().decode('utf-8')
    
    serialdata = tryserial(ser)#ser.readline().decode('utf-8')
    data_read = True
    return serialdata

def post_data(token, suuid, ser, take_photos):
    data_read = False
    data_sent = False
    data_cached = False
    logging.debug("Start post_data")
    if not os.path.exists(DATADIR):
        os.makedirs(DATADIR)
    
    if not token:
        logging.debug('Not allowed')
    head = {'Authorization': 'Bearer ' + token}

    # collect serial data here
    cameradata = []
        
    serialdata = readserialdata(ser, data_read)
    if take_photos:
        if CAMERA_CONFIG:
            for CAMERA in CAMERA_CONFIG:
                if CAMERA['CAMERA_TYPE'] == "USB":
            
                    v = cv2.VideoCapture(CAMERA['PORTNUM'])
                    v.set(3,1280)
                    v.set(4,960)
                
                    for i in range(15):
                        check, frame = v.read()
                        sleep(1)
        
                    fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
                    showPic = cv2.imwrite(fname, frame)
                    camdata = {"fname": fname, "label": CAMERA["LABEL"]}
                    v.release()
                    logging.debug("Captured {}".format(CAMERA['LABEL']))
    
                    # Check for black images
                    fimg = Image.open(camdata['fname'])
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
                    NUMRETRIES = 10
                    if LABEL == "INESUN":
                        for i in range(0, NUMFRAMES):
                    
                            fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
                            postdata = {"flag": 4,
                                        "existFlag": 1,
                                        "language": "cn",
                                        "presetNum": i
                            }
                            comm_sent = False
                            for n in range(NUMRETRIES):
                                if not comm_sent:
                                    try:
                                        r = requests.post("http://{}:{}@{}/form/presetSet".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), data=postdata)
                                        comm_sent = True
                                    except:
                                        logging.debug("Failed to connect to camera")
                                        sleep(2)
                            
                            sleep(4)
                            rtsp = cv2.VideoCapture("rtsp://{}:{}@{}:554/1/h264major".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
                            check, frame = rtsp.read()
                            showPic = cv2.imwrite(fname, frame)#, [cv2.IMWRITE_PNG_COMPRESSION, 9])
                            logging.debug("CAPTURED {} PICT {}".format(LABEL, i+1))
                            cameradata.append({"fname": fname, "label": LABEL + " {}".format(i+1)})
                            rtsp.release()
                    

                    else:
                        requests.get("http://{}:{}@{}//cgi-bin/hi3510/preset.cgi?-act=goto&-number=0".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))    
                        sleep(5)
                        for i in range(1, NUMFRAMES + 1):
                            fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
                            try:
                                requests.get("http://{}:{}@{}//cgi-bin/hi3510/preset.cgi?-act=goto&-number={}".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP, i))
                                sleep(5)
                                r = requests.get("http://{}:{}@{}/tmpfs/auto.jpg".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), stream=True)
                                if r.status_code == 200:
                                    with open(fname, 'wb') as f:
                                        r.raw.decode_content = True
                                        shutil.copyfileobj(r.raw, f)
                                        logging.debug("CAPTURED {} PICT {}".format(LABEL, i))
                                        cameradata.append({"fname": fname, "label": LABEL + " {}".format(i)})
                            except:
                                pass
                        
                
    serialdata['uuid'] = suuid
    serialdata['TS'] = datetime.datetime.now(tz)
    #create cache record here with status uploaded False

    wght0 = (serialdata.get('WGHT0') - OFFSET0) / SCALE0
    wght1 = (serialdata.get('WGHT1') - OFFSET1) / SCALE1
    wght2 = (serialdata.get('WGHT2') - OFFSET2) / SCALE2
    wght3 = (serialdata.get('WGHT3') - OFFSET3) / SCALE3
    wght4 = (serialdata.get('WGHT4') - OFFSET4) / SCALE4
    newdata = SensorData(ts = serialdata['TS'],
                         sensor_uuid = serialdata['uuid'],
                         temp0 = serialdata.get('T0', -1),
                         temp1 = serialdata.get('T1', -1),
                         hum0 = serialdata.get('H0', -1),
                         hum1 = serialdata.get('H1', -1),
                         tempA = serialdata.get('TA', -1),
                         uv = serialdata.get('UV', -1),
                         lux = serialdata.get('L', -1),
                         soilmoist = serialdata.get('M', -1),
                         co2 = serialdata.get('CO2', -1),
                         wght0 = wght0,
                         wght1 = wght1,
                         wght2 = wght2,
                         wght3 = wght3,
                         wght4 = wght4
                         
    )
    session.add(newdata)
    session.commit()

    if take_photos:
        files = {}
        for i, d in enumerate(cameradata):
            newphoto = Photo(sensordata=newdata, photo_filename=d['fname'], label=d["label"])
            session.add(newphoto)
            session.commit()
    else:
        files = None
            
    # All data saved
    numretries = 0
    #while not data_sent:
            
    try:
        # cleanup
        data_uploaded = session.query(SensorData).filter(SensorData.uploaded.is_(True)).delete()
        session.commit()
        # try to send all cached data
        cacheddata = session.query(SensorData).filter(SensorData.uploaded.is_(False)).all()
        logging.debug("CACHED DATA {}".format([(c.sensor_uuid, c.ts) for c in cacheddata]))
        for cd in cacheddata:
            serialdata = {'uuid': cd.sensor_uuid,
                          'ts': cd.ts,
                          'TA': cd.tempA,
                          'T0': cd.temp0,
                          'T1': cd.temp1,
                          'H0': cd.hum0,
                          'H1': cd.hum1,
                          'UV': cd.uv,
                          'L': cd.lux,
                          'M': cd.soilmoist,
                          'CO2': cd.co2,
                          'WGHT0':cd.wght0,
                          'WGHT1':cd.wght1,
                          'WGHT2':cd.wght2,
                          'WGHT3':cd.wght3,
                          'WGHT4':cd.wght4
            }
            logging.debug("SENDING POST REQUEST")
            if files:
                response = requests.post(SERVER_HOST.format("data"), data=serialdata, files=files, headers=head)
            else:
                response = requests.post(SERVER_HOST.format("data"), data=serialdata, headers=head)
            logging.debug("SERVER RESPONSE {} {}".format(response.status_code, response.text))
            if response.status_code == 201:
                resp_data = json.loads(response.text)
                cd.remote_data_id = resp_data['id']
                cd.uploaded = True
                session.add(cd)
                session.commit()
                data_sent=True
        
        # Send all cached photos
        if take_photos:
            cachedphotos = session.query(Photo).filter(Photo.uploaded.is_(False)).all()
            p = Pool(processes=10)
            argslist = []
            for i, f in enumerate(cachedphotos):
                if f.sensordata.remote_data_id:
                    argslist.append([f.photo_filename, f.label, f.sensordata.remote_data_id, f.photo_id, head])
                    
            logging.debug("START LOOP")
            data = p.starmap(send_patch_request, argslist)
            p.close()
            totalcount = data.count(200)
            # Обрабатывать неотправленные фото, не удалять их
            # и не удалять отправленные данные
            # помечать данные как sent
            # и после отправки всех фото
            # если у данных не осталось отправленных фото, от удалять
            logging.debug("PHOTOS SENT {}".format(totalcount))
            # remove cached data here
    except requests.exceptions.ConnectionError:
        sleep(2)
        numretries =+ 1
        logging.debug("Network error, trying to connect")

if __name__ == '__main__':
    sensor_uuid, token = get_sensor_uuid()
    # data -> data only
    # photos -> data & photos
    tocollect = 'data'
    
    if len(sys.argv) > 1:
        tocollect = sys.argv[1]

    if not sensor_uuid:
        token = get_token()
        sensor_uuid = register_sensor(token)
   # else:
        #for i in range(3):
    #while True:


    schedule.every(5).minutes.do(post_data, token, sensor_uuid, ser, False)
    schedule.every().hour.do(post_data, token, sensor_uuid, ser, True)
    while 1:
        schedule.run_pending()
        sleep(1)

        
