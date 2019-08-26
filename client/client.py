#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import pickle
import os
import serial
import json
import cv2
import shutil

#from picamera import PiCamera
from time import sleep

CAMERA_IP = "192.168.0.104"
CAMERA_LOGIN = "plantdata"
CAMERA_PASSWORD = "plantpassword"


def get_token():
    login_data = {"username":"plantuser@plantdata.com",
                  "password":"plantpassword"
    }
    token = None
    res = requests.post("https://plantdata.fermata.tech:5498/api/v1/token", json=login_data)
    if res.status_code == 200:
        token = res.json().get('token')
    return token


def register_sensor(token):
    sensor_uuid = None
    with open('sensor.dat', 'wb') as f:
        try:
            sensor_uuid = new_sensor(token)
            data = {'uuid': sensor_uuid}
            pickle.dump(data, f)
        except:
            pass
    return sensor_uuid


def get_sensor_uuid(token):
    sensor_uuid = None
    if not os.path.exists('sensor.dat'):
        os.mknod("sensor.dat")
        
    with open('sensor.dat', 'rb') as f:
        try:
            data = pickle.load(f)
            print(data)
            sensor_uuid = data['uuid']
        except:
            pass
    return sensor_uuid

def new_sensor(token):
    if not token:
        return "Not allowed"
    head = {'Authorization': 'Bearer ' + token}
    location = {'lat': 111, 'lon': 111, 'address': 'test address 1'}
    response = requests.post("https://plantdata.fermata.tech:5498/api/v1/sensors", json=location, headers=head)
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
    serialdata = serialdata.replace(", ,", ", ")
    serialdata = serialdata.replace(", }", "}")
    print(serialdata)
    serialdata = json.loads(serialdata)
    data_read = True
    return serialdata

def post_data(token, suuid):
    data_read = False
    if not token:
        print('Not allowed')
    head = {'Authorization': 'Bearer ' + token}

    # collect serial data here
    ser = serial.Serial('/dev/ttyACM0',9600)

    serialdata = readserialdata(ser, data_read)
    
    v0 = cv2.VideoCapture(0)
    v0.set(3,1280)
    v0.set(4,960)

    v1 = cv2.VideoCapture(1)
    v1.set(3,1280)
    v1.set(4,960)
    for i in range(15):
        check, frame = v0.read()
        sleep(1)
    showPic = cv2.imwrite("img0.jpg",frame)
    v0.release()
    print("Captured USB CAM 0")
    
    for i in range(15):
        check, frame = v1.read()
        sleep(1)

    check, frame = v1.read()
    showPic = cv2.imwrite("img1.jpg",frame)
    v1.release()
    print("Captured USB CAM 1")
    # IP Camera
    for i in range(1, 4):
        requests.get("http://{}:{}@{}//cgi-bin/hi3510/preset.cgi?-act=goto&-number={}".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP, i))
        sleep(3)
        r = requests.get("http://{}:{}@{}/tmpfs/auto.jpg".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), stream=True)
        if r.status_code == 200:
            with open("camimage{}.jpg".format(i), 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
                print("CAPTURED IP CAM PICT {}".format(i))
    requests.get("http://{}:{}@{}//cgi-bin/hi3510/preset.cgi?-act=set&-status=0&-number=1".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
    requests.get("http://{}:{}@{}//cgi-bin/hi3510/preset.cgi?-act=goto&-number=1".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP))
    files = {'upload_file0': open('img0.jpg','rb'),
             'upload_file1': open('img1.jpg','rb'),
             'upload_file2': open('camimage1.jpg','rb'),
             'upload_file3': open('camimage2.jpg','rb'),
             'upload_file4': open('camimage3.jpg','rb')
    }
    serialdata['uuid'] = suuid
    response = requests.post("https://plantdata.fermata.tech:5498/api/v1/data", data=serialdata, files=files, headers=head)
    print(response.text)
    
if __name__ == '__main__':
    token = get_token()
    sensor_uuid = get_sensor_uuid(token)
    if not sensor_uuid:
        sensor_uuid = register_sensor(token)
    if sensor_uuid:
        #for i in range(3):
        while True:
            post_data(token, sensor_uuid)
            sleep(60)
            #sleep(3600)
