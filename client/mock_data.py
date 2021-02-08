#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import requests
import pickle
import os
import json
import shutil
import uuid
import datetime
import pytz
import functools
import yaml
import copy
import math
import logging
from random import gauss
from time import sleep


logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)
logger = logging.getLogger(__name__)


tz = pytz.timezone('Europe/Moscow')

with open("mock_data_config.yaml", 'r') as stream:
    try:
        CONFIG_FILE = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        logger.debug(exc)


SERVER_LOGIN = CONFIG_FILE['SERVER_LOGIN']
SERVER_PASSWORD = CONFIG_FILE['SERVER_PASSWORD']
SERVER_HOST = "https://host:port/api/v2/{}"

H_mean = 70
CO_mean = 300
T_mean = 23
variance = 4
INTERVAL = 60 # minutes

def gen_rand(val, var):
    return gauss(val, math.sqrt(var))

def gen_timestamps(interval):
    now = datetime.datetime.now()
    first = now.replace(hour=0, minute=0, second=0)
    numintervals = int(round((24*60)/interval))
    return [first + datetime.timedelta(minutes=x*interval) for x in range(numintervals)]

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

def delete_data(token, bsuuid):
    logger.debug("Start delete_data")
    if not token:
        logger.debug('Not allowed')
    head = {'Authorization': 'Bearer ' + token}
    resp = requests.delete(SERVER_HOST.format("data"), headers=head)
    logger.debug(["RESP", resp])
    
def post_data(token, bsuuid):
    logger.debug("Start post_data")
    
    if not token:
        logger.debug('Not allowed')
    head = {'Authorization': 'Bearer ' + token}

    sensordata = {}
    sensordata['uuid'] = bsuuid
    sensordata['TS'] = datetime.datetime.now(tz)
    
    
    logger.debug("send data")
    #logger.debug(cacheddata)
    current_ts = datetime.datetime.now(tz)
    ts = gen_timestamps(INTERVAL)
    logger.debug(["ts", ts])
    
    for t in ts:
        postdata = {'uuid': bsuuid, 'ts': str(t), 'probes' : [
            {'puuid': 'AAAAAAAAA0', 'data': [
                {'ptype':"temp", "label": "T0", 'value': gen_rand(T_mean, variance) },
                {'ptype':"humid", "label": "H0", 'value': gen_rand(H_mean, variance) },
                {'ptype':"co2", "label": "C0", 'value': gen_rand(CO_mean, variance) }
            ]},
            {'puuid': 'AAAAAAAAA0', 'data': [
                {'ptype':"temp", "label": "T0", 'value': gen_rand(T_mean, variance) },
                {'ptype':"humid", "label": "H0", 'value': gen_rand(H_mean, variance) },
                {'ptype':"co2", "label": "C0", 'value': gen_rand(CO_mean, variance) }
            ]},
            {'puuid': 'AAAAAAAAA0', 'data': [
                {'ptype':"temp", "label": "T0", 'value': gen_rand(T_mean, variance) },
                {'ptype':"humid", "label": "H0", 'value': gen_rand(H_mean, variance) },
                {'ptype':"co2", "label": "C0", 'value': gen_rand(CO_mean, variance) }
            ]}
        ]}
    
        print(json.dumps(postdata, indent=4))

        resp = requests.post(SERVER_HOST.format("data"), json=postdata, headers=head)
        
        if resp.status_code == 201:
            resp_data = json.loads(resp.text)
            print(["DATA POSTED", resp_data])
        else:
            print(["DATA POST", resp])
            
if __name__ == '__main__':
    base_station_uuid, token = get_base_station_uuid()
    #print([base_station_uuid, token])
    if not base_station_uuid:
        token = get_token()
        base_station_uuid = register_base_station(token)
 
    #scheduler = SafeScheduler()
    #scheduler.every(60).minutes.do(post_data, token, base_station_uuid, False)
    
    #scheduler.every(120).minutes.do(post_data, token, base_station_uuid, True)
    #logger.debug(base_station_uuid)
    #post_data(token, base_station_uuid)
    delete_data(token, base_station_uuid)
    #sys.exit(1)
    #while :
    #    scheduler.run_pending()
    #    sleep(1)

        
