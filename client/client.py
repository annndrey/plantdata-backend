#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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

#from picamera import PiCamera
from time import sleep
from PIL import Image

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from models import Base, SensorData, Photo


tz = pytz.timezone('Europe/Moscow')

CAMERA_IP = "192.168.0.100"
CAMERA_LOGIN = "plantdata"
CAMERA_PASSWORD = "plantpassword"
SERVER_LOGIN = "plantuser@plantdata.com"
SERVER_PASSWORD = "plantpassword"
SERVER_HOST = "https://plantdata.fermata.tech:5498/api/v1/{}"
db_file = 'localdata.db'
DATADIR = "picts"
LOWLIGHT = 10

engine = create_engine('sqlite:///{}'.format(db_file))
Session = sessionmaker(bind=engine)
session = Session()

Base.metadata.create_all(engine, checkfirst=True)

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
            print("Trying to reconnect")
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
            print(data)
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
            print("Trying to connect")

    newuuid = response.json().get('uuid')
    return newuuid

def readserialdata(ser, isread):

    # read a line until the end to skip incomplete data
    lastchar = ser.read_until(b'\n')
    ser.flushInput()
    ser.flushOutput()
    # read complete line
    print(lastchar)
    #sleep(1)
    serialdata = ser.readline().decode('utf-8')
    serialdata = serialdata.replace("\r\n", '')
    serialdata = serialdata.replace("'", '"')
    serialdata = serialdata.replace("CO2", '"CO2"')
    #serialdata = serialdata.replace("WGHT0", '"WGHT0"')
    serialdata = serialdata.replace(", ,", ", ")
    serialdata = serialdata.replace(", }", "}")
    print(serialdata)
    serialdata = json.loads(serialdata)
    data_read = True
    return serialdata

def post_data(token, suuid):
    data_read = False
    data_sent = False
    data_cached = False

    if not os.path.exists(DATADIR):
        os.makedirs(DATADIR)
    
    if not token:
        print('Not allowed')
    head = {'Authorization': 'Bearer ' + token}

    # collect serial data here
    fnames = []
    
    ser = serial.Serial('/dev/ttyACM0',9600)
    serialdata = readserialdata(ser, data_read)
    # USB0
    v0 = cv2.VideoCapture(0)
    v0.set(3,1280)
    v0.set(4,960)
    # USB1
    v1 = cv2.VideoCapture(1)
    v1.set(3,1280)
    v1.set(4,960)
    
    for i in range(15):
        check, frame = v0.read()
        sleep(1)
    fname0 = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
    showPic = cv2.imwrite(fname0, frame)
    v0.release()
    print("Captured USB CAM 0")
    
    for i in range(15):
        check, frame = v1.read()
        sleep(1)

    check, frame = v1.read()
    fname1 = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
    showPic = cv2.imwrite(fname1, frame)
    v1.release()

    for fnm in [fname0, fname1]:
        fimg = Image.open(fnm)
        if sum(fimg.convert("L").getextrema()) >= LOWLIGHT:
            fnames.append(fnm)
        else:
            os.unlink(fnm)
    
    print("Captured USB CAM 1")
    # IP Camera
    for i in range(1, 4):
        fname = os.path.join(DATADIR, str(uuid.uuid4())+".jpg")
        try:
            requests.get("http://{}:{}@{}//cgi-bin/hi3510/preset.cgi?-act=goto&-number={}".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP, i))
            sleep(3)
            r = requests.get("http://{}:{}@{}/tmpfs/auto.jpg".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), stream=True)
            if r.status_code == 200:
                with open(fname, 'wb') as f:
                    r.raw.decode_content = True
                    shutil.copyfileobj(r.raw, f)
                    print("CAPTURED IP CAM PICT {}".format(i))
            requests.get("http://{}:{}@{}//cgi-bin/hi3510/preset.cgi?-act=goto&-number=1".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
            fnames.append(fname)
        except:
            pass
        
    #requests.get("http://{}:{}@{}//cgi-bin/hi3510/preset.cgi?-act=set&-status=0&-number=1".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
    serialdata['uuid'] = suuid
    serialdata['TS'] = datetime.datetime.now(tz)
    #create cache record here with status uploaded False
    newdata = SensorData(ts = serialdata['TS'],
                         sensor_uuid = serialdata['uuid'],
                         temp0 = serialdata['T0'],
                         temp1 = serialdata['T1'],
                         hum0 = serialdata['H0'],
                         hum1 = serialdata['H1'],
                         tempA = serialdata['TA'],
                         uv = serialdata['UV'],
                         lux = serialdata['L'],
                         soilmoist = serialdata['M'],
                         co2 = serialdata['CO2'],
                         wght0 = serialdata.get('WGHT0')#/472
    )
    session.add(newdata)
    session.commit()
    
    files = {}
    for i, f in enumerate(fnames):
        newphoto = Photo(sensordata=newdata, photo_filename=f)
        session.add(newphoto)
        session.commit()
    # All data saved
    numretries = 0
    #while not data_sent:
    try:
        # try to send all cached data
        cacheddata = session.query(SensorData).filter(SensorData.uploaded.is_(False)).all()
        print("CACHED DATA", [(c.sensor_uuid, c.ts) for c in cacheddata])
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
                          'WGHT0':cd.wght0
            }
            files = {}
            for i, f in enumerate(cd.photos):
                files['uploaded_file{}'.format(i)] = open(f.photo_filename, 'rb')
            print("SENDING POST REQUEST")
            response = requests.post(SERVER_HOST.format("data"), data=serialdata, files=files, headers=head)
            print("SERVER RESPONSE", response.status_code)
            # cd.uploaded = True
            # remoce all cached photos
            # CREATED
            if response.status_code == 201:
                for f in cd.photos:
                    os.unlink(f.photo_filename)
                    session.delete(f)
                    session.commit()
                    # remove cached data
                session.delete(cd)
                session.commit()
                
                data_sent=True
        # remove cached data here
    except requests.exceptions.ConnectionError:
        sleep(2)
        numretries =+ 1
        print("No network, trying to connect")

if __name__ == '__main__':
    sensor_uuid, token = get_sensor_uuid()
    if not sensor_uuid:
        token = get_token()
        sensor_uuid = register_sensor(token)
    else:
        #for i in range(3):
        while True:
            post_data(token, sensor_uuid)
            sleep(60)
            #sleep(3600)
