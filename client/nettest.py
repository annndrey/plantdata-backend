#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import pickle
import os
import serial
import json
import shutil

from time import sleep


def get_token():
    data_sent = False
    login_data = {"username":"user@host",
                  "password":"password"
    }
    token = None
    while not data_sent:
        try:
            res = requests.post("https://host:port/api/v1/token", json=login_data)
            data_sent = True
        except requests.exceptions.ConnectionError:
            print("")
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
        #os.mknod("sensor.dat")
        
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
            response = requests.post("https://host:port/api/v1/sensors", json=location, headers=head)
            data_sent = True
        except requests.exceptions.ConnectionError:
            sleep(2)
            print("Trying to connect")
            
    newuuid = response.json().get('uuid')
    return newuuid

def post_data(token, suuid):
    data_sent = False
    data_cached = False
    if not token:
        print('Not allowed')
    head = {'Authorization': 'Bearer ' + token}
    
    # collect serial data here
    serialdata = {}
    serialdata['uuid'] = suuid
    while not data_sent:
        try:
            response = requests.post("https://host:port/api/v1/data", data=serialdata,  headers=head)
            data_sent=True
        except requests.exceptions.ConnectionError:
            if not data_cached:
                # cache data
                data_cached = True
            sleep(2)
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
            print("Data sent")
            for i in range(5):
                print("Next post request in {}".format(5-i))
                sleep(1)
            #sleep(3600)
