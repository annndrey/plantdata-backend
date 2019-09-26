#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import yaml
import shutil

with open("config.yaml", 'r') as stream:
    try:
        CAMERA_CONFIG = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        print(exc)


for CAMERA in CAMERA_CONFIG:
    if CAMERA['CAMERA_TYPE'] == "IP":
        CAMERA_LOGIN = CAMERA['CAMERA_LOGIN']
        CAMERA_PASSWORD = CAMERA['CAMERA_PASSWORD']
        CAMERA_IP = CAMERA['CAMERA_IP']
        NUMFRAMES = CAMERA['NUMFRAMES']
        LABEL = CAMERA['LABEL']

        if LABEL == "INESUN":
            postdata = {"flag": 4,
                        "existFlag": 1,
                        "language": "cn",
                        "presetNum": 1
            }
            r = requests.post("http://{}:{}@{}/form/presetSet".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), data=postdata)
            print(r.status_code, r.text)
            r = requests.get("http://{}:{}@{}/jpgimage/1/image.jpg".format(CAMERA_LOGIN, CAMERA_PASSWORD, CAMERA_IP), stream=True)
            print(r.status_code)
            with open("testfile.jpg", 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
                
