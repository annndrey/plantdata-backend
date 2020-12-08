#!/usr/bin/env python
# -*- coding: utf-8 -*-

from functools import wraps
from flask import Flask, g, make_response, request, current_app, send_file, url_for
from flask import abort as fabort
from flask_restful import Resource, Api, reqparse, abort, marshal_with
from flask.json import jsonify
from flasgger import Swagger
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, desc, and_, func, not_, extract
from sqlalchemy import create_engine
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import func as sql_func
from sqlalchemy.pool import NullPool
from flask_marshmallow import Marshmallow
from flask_httpauth import HTTPBasicAuth
from flask_cors import CORS, cross_origin
from flask_restful.utils import cors
from marshmallow import fields, pre_dump, post_dump
from marshmallow_enum import EnumField
from itertools import groupby, islice, accumulate
from statistics import mean
from models import db, User, Sensor, Location, Data, DataPicture, Camera, CameraPosition, CameraLocation, CameraPositionLocation, Probe, ProbeData, PictureZone, SensorType, data_probes, Notification, SensorLimit
import logging
import os
import copy
import uuid
import tempfile
import shutil
import zipfile
import urllib.parse
import base64

# for emails
import smtplib
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger

# caching
from flask_caching import Cache
import urllib.parse

import threading

import click
import datetime
import calendar
from dateutil.relativedelta import relativedelta
from dateutil import parser
from collections import defaultdict
import jwt
import json
import yaml
import csv
import pandas as pd
import io
import requests
from PIL import Image, ImageDraw, ImageFont
import glob
from collections import OrderedDict
import orjson

from multiprocessing import Pool
#from multiprocessing.dummy import Pool 
#from concurrent.futures import ThreadPoolExecutor as pool

logging.basicConfig(format='%(levelname)s: %(asctime)s - %(message)s',
                    level=logging.DEBUG, datefmt='%d.%m.%Y %I:%M:%S %p')

app = Flask(__name__)
app.config.from_envvar('APPSETTINGS')
API_VERSION = app.config.get('API_VERSION', 1)

cors = CORS(app, resources={r"/*": {"origins": "*"}}, methods=['GET', 'POST', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
api = Api(app, prefix=f"/api/v{API_VERSION}")
auth = HTTPBasicAuth()
app.config['PROPAGATE_EXCEPTIONS'] = True
db.init_app(app)
migrate = Migrate(app, db)
ma = Marshmallow(app)

gunicorn_logger = logging.getLogger('gunicorn.error')
app.logger.handlers = gunicorn_logger.handlers
app.logger.setLevel(gunicorn_logger.level)
celery_logger = get_task_logger(__name__)
HOST = app.config.get('HOST', 'localhost')
REDIS_HOST = app.config.get('REDIS_HOST', 'localhost')
REDIS_PORT = app.config.get('REDIS_PORT', 6379)
REDIS_DB = app.config.get('REDIS_DB', 0)
CACHE_DB = app.config.get('CACHE_DB', 1)

BASEDIR = app.config.get('FILE_PATH')
MAILUSER = app.config.get('MAILUSER')
MAILPASS = app.config.get('MAILPASS')
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

DB_CONNECT = app.config.get('SQLALCHEMY_DATABASE_URI')

mysql_engine = create_engine(DB_CONNECT, poolclass=NullPool)
session_factory = sessionmaker(bind=mysql_engine, autocommit=True)
Session = scoped_session(session_factory)
#executor = ThreadPoolExecutor(3)


cache = Cache(app, config={
    'CACHE_TYPE': 'redis',
    'CACHE_KEY_PREFIX': 'fcache',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_REDIS_PORT': REDIS_PORT,
    'CACHE_REDIS_DB'  : REDIS_DB,
    'CACHE_REDIS_URL': 'redis://{}:{}/{}'.format(REDIS_HOST, REDIS_PORT, REDIS_DB)
})

app.config['SWAGGER'] = {
    'uiversion': 3
}
swtemplate = {
    "info": {
        "title": "Plantdata API",
        "description": "Plantdata API is a service to collect "
        "and monitor plant conditions across multiple remote sensors",
        "version": f"{API_VERSION}",
    },
    "schemes": [
        "https"
    ]
}

swagger_config = {
    "headers": [
    ],
    "specs": [
        {
            "endpoint": 'apidescr',
            "route": '/apidescr.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs/",
    'uiversion': 3
}

swagger = Swagger(app, config=swagger_config, template=swtemplate)


CF_LOGIN = app.config['CF_LOGIN']
CF_PASSWORD = app.config['CF_PASSWORD']
#CF_HOST = app.config['CF_HOST']
CF_HOST = "https://regions.fermata.tech:5777/api/v1/loadimage"
CF_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vdXNlckBmZXJtYXRhLnRlY2giLCJpYXQiOjE2MDUwNzgxNTEsImV4cCI6MTYwODY3ODE1MX0.wqR13DQI9oXQImvPnH8qOcc7borNEIo5dRFYe9TK1eE"
FONT = app.config['FONT']
FONTSIZE = app.config['FONTSIZE']

zonefont = ImageFont.truetype(FONT, size=FONTSIZE)

CLASSIFY_ZONES = app.config['CLASSIFY_ZONES']
SEND_EMAILS = app.config.get('SEND_EMAILS', False)

app.config['CELERY_BROKER_URL'] = 'redis://{}:{}/{}'.format(REDIS_HOST, REDIS_PORT, REDIS_DB)
app.config['CELERY_RESULT_BACKEND'] = 'redis://{}:{}/{}'.format(REDIS_HOST, REDIS_PORT, REDIS_DB)

TMPDIR = app.config['TEMPDIR']

COLOR_THRESHOLD = 75000

JSONIFY_PRETTYPRINT_REGULAR=False


#if CLASSIFY_ZONES:
#    with open("cropsettings.yaml", 'r') as stream:
#        try:
#            CROP_SETTINGS = yaml.safe_load(stream)
#        except yaml.YAMLError as exc:
#            app.logger.debug(exc)


class SQLAlchemyNoPool(SQLAlchemy):
    def apply_driver_hacks(self, app, info, options):
        options.update({
            'poolclass': NullPool
        })
        super(SQLAlchemy, self).apply_driver_hacks(app, info, options)

def get_count(q):
    count_q = q.statement.with_only_columns([sql_func.count()]).order_by(None)
    count = q.session.execute(count_q).scalar()
    return count
        

def custom_serializer(data, cameras=None):
    outdata = {"labels": [], "data": {}, "cameras": [], "locdimensions": {}, "probelabels": {} }
    
    if cameras:
        for cam in cameras:
            outdata['cameras'].append([{"camlabel": c.camlabel, "id":c.id, "warnings":c.warnings} for c in cam])
    
    for d in data:
        if len(d.records) > 0:
            outdata['labels'].append(d.ts)

        if not cameras:
            if len(d.cameras) > 0:
                outdata['cameras'].append([{"camlabel":c.camlabel, "id":c.id, "warnings":c.warnings} for c in d.cameras])
        for r in d.records:
            if r.probe.id not in [362, 356]:
                probelabel = "{} {} {}".format(r.probe.uuid, r.probe.sensor.uuid, r.probe.label)
                datalabel = "{} {} {} {}".format(r.label, r.probe.uuid, r.probe.sensor.uuid, r.probe.label)
            
                if r.probe.uuid not in outdata['locdimensions'].keys():
                    data_loc = r.probe.sensor.location
                    outdata['locdimensions'][r.probe.sensor.uuid] = {"x":data_loc.dimx, "y":data_loc.dimy, "z":data_loc.dimz}
                
                if datalabel not in outdata['data'].keys():
                    outdata['data'][datalabel] = [r.value]
                else:
                    outdata['data'][datalabel].append(r.value)
                
                if probelabel not in outdata['probelabels'].keys():
                    outdata['probelabels'][probelabel] = [d.ts]
                else:
                    if d.ts not in outdata['probelabels'][probelabel]:
                        outdata['probelabels'][probelabel].append(d.ts)
                    
    # fix missing data
    # find longest probelabel
    # find index of labels that are not in other probelabels
    #if outdata["probelabels"]:
    if False:
        #if len(set(map(len, outdata['probelabels'].values()))) != 1:
        #    maxvalues = max(outdata['probelabels'].items(), key = lambda x: len(set(x[1])))
        #    if maxvalues:
        #max_key, longest_labels = maxvalues
        longest_labels = outdata['labels']
        maxlen = len(longest_labels)
                
        for k in outdata['probelabels']:
        #if k != max_key:
            orig_labels = outdata['probelabels'][k]
            labels_intersection = list(set(longest_labels) & set(orig_labels))
            for dk in outdata['data']:
                if dk[3:] == k:
                    newdata = [0] * maxlen

                    for lab in labels_intersection:
                        label_old_ind = orig_labels.index(lab)
                        label_new_ind = longest_labels.index(lab)
                        #app.logger.debug(["DATA1", newdata])
                        #app.logger.debug(["DATA2", outdata['data'][dk]])
                        #app.logger.debug(["DATA3", k, dk, label_old_ind, label_new_ind, len(orig_labels), len(outdata['data'][dk]), orig_labels[label_old_ind]])
                        #app.logger.debug(["DATA4", outdata['data'][dk][label_old_ind]])
                        
                        newdata[label_new_ind] = outdata['data'][dk][label_old_ind]

                    # fix missing values
                    for ind, data in enumerate(newdata):
                        if data == 0:
                            if 0 < ind < maxlen - 1:
                                # app.logger.debug(["IND", ind, len(newdata)])
                                newdata[ind] = mean([newdata[ind-1], newdata[ind + 1]])
                            elif ind >= maxlen - 1:
                                newdata[ind] = mean([newdata[ind-2], newdata[ind - 1]])
                    newdata = list(accumulate(newdata, lambda x,y: y if y else mean([x, y])))
                    outdata['data'][dk] = newdata
            outdata['probelabels'][k] = longest_labels
                            #
                            #app.logger.debug([ "labels", label_new_ind,  label_old_ind, len(outdata['data'][dk])])
                            #newdata[label_new_ind] = outdata['data'][dk][label_old_ind]
                                    
                            
                            #outdata['probelabels'][k] = max_value
                            #app.logger.debug(["newdata", newdata])
                        
                        #    outdata['probelabels'][k].insert(missing_ind, s)
                        # for dk in outdata['data']:
                        #    if dk[3:] == k:
                        #        outdata['data'][dk] = newdata
                        #            missing_data = 0
                        #            max_index = len(outdata['data'][dk]) - 1
                        #            if missing_ind > 1 or missing_ind < max_ind:
                        #                missing_data = mean([outdata['data'][dk][missing_ind - 1], outdata['data'][dk][missing_ind + 1]])
                        #            elif missing_ind == max_ind:
                        #                missing_data = mean([outdata['data'][dk][max_ind - 2], outdata['data'][dk][max_ind - 1]])
                        #            outdata['data'][dk].insert(missing_ind, missing_data)

    return outdata


        
def send_zones(zone, zonelabel, fuuid, file_format, fpath, user_login, sensor_uuid, cf_headers, original, allowed_values=False):
    #with app.app_context():
    db = SQLAlchemyNoPool()
    cropped = original.crop((zone['left'], zone['top'], zone['right'], zone['bottom']))
    img_io = io.BytesIO()
    cropped.save(img_io, file_format, quality=100)
    img_io.seek(0)
    #dr = ImageDraw.Draw(original)
    #dr.rectangle((zone['left'], zone['top'], zone['right'], zone['bottom']), outline = '#fbb040', width=3)
    #dr.text((zone['left']+2, zone['top']+2), zonelabel, font=zonefont)

    zuuid = f"{fuuid}_{zonelabel}"
    zname = zuuid + "." + file_format.lower()
    z_full_path = os.path.join(fpath, zname)
    partzpath = os.path.join(user_login, sensor_uuid, zname)
    app.logger.debug(["ZONE", zonelabel, z_full_path, partzpath])
    cropped.save(z_full_path, file_format, quality=100)
    newzone = PictureZone(fpath=partzpath, zone=zonelabel)

    # Now take an original image, crop the zones, send it to the
    # CF server and get back the response for each
    # Draw rectangle zones on the original image & save it
    # Modify the image lzbel with zones results
    # send CF request
    cf_request_data = {'index':0, 'filename': fuuid}
    if allowed_values:
        cf_request_data['allowed_values'] = allowed_values
        
    response = requests.post(CF_HOST.format("loadimage"), auth=(CF_LOGIN, CF_PASSWORD), files = {'imagefile': img_io}, data=cf_request_data)
    if response.status_code == 200:
        cf_result = response.json().get('objtype')
        subzones = get_zones(cropped, 2, 2)
        sz_results = []
        for sz in subzones.keys():
            if allowed_values:
                sz_res = send_subzones(subzones[sz], sz, file_format, cropped, allowed_values=allowed_values)
            else:
                sz_res = send_subzones(subzones[sz], sz, file_format, cropped)        
            sz_results.append(sz_res)

        unhealthy_results = ['_'.join(res.split('_')[:-1]) for res in sz_results if 'unhealthy' in res]
        healthy_results = [res for res in sz_results if 'unhealthy' not in res]

        if unhealthy_results and 'unhealthy' in cf_result:
            res_plant_type = '_'.join(cf_result.split('_')[:-1])
            if res_plant_type in unhealthy_results:
                precise_res = cf_result
            elif len(unhealthy_results) > 1 and len(set(unhealthy_results)) < len(unhealthy_results):
                unhealthy_results = [(res, unhealthy_results.count(res)) for res in set(unhealthy_results)]
                unhealthy_results = sorted(unhealthy_results, key=lambda x: x[1], reverse=True)
                precise_res = unhealthy_results[0][0] + '_unhealthy'
            elif len(unhealthy_results) > 1:
                for res in healthy_results:
                    if res in unhealthy_results:
                        precise_res = res + '_unhealthy'
                        break
                    precise_res = unhealthy_results[0] + '_unhealthy'
            else:
                precise_res = cf_result

        elif unhealthy_results and 'unhealthy' not in cf_result:
            if len(unhealthy_results) > 1 and len(set(unhealthy_results)) < len(unhealthy_results):
                unhealthy_results = [(res, unhealthy_results.count(res)) for res in set(unhealthy_results)]
                unhealthy_results = sorted(unhealthy_results, key=lambda x: x[1], reverse=True)
                precise_res = unhealthy_results[0][0] + '_unhealthy'
            else:
                precise_res = cf_result
                
        elif cf_result in sz_results:
            precise_res = cf_result

        elif 'unhealthy' in cf_result and not unhealthy_results:
            # Issue #80
            precise_res = cf_result + "_ns"

        else:
            precise_results = [(res, sz_results.count(res)) for res in set(sz_results)]
            precise_results = sorted(precise_results, key=lambda x: x[1], reverse=True)
            precise_res = precise_results[0][0]

        newzone.origresults = cf_result



        newzone.results = precise_res


        app.logger.debug(f"CF RESULTS {cf_result}")

    db.session.add(newzone)
    db.session.commit()
    newzone_id = newzone.id
    db.session.close()

    #db.session.close()
    #if newzone.revisedresults == unhealthy:
    return newzone_id


def check_colors(imgfile):
    #greyscale_image = image.convert('L')
    image = Image.open(imgfile)
    pixels = image.getdata()
    n = len(set(pixels))
    return n


def send_subzones(zone, zonelabel, file_format, pict, allowed_values=False):
    cf_result = False
    cropped = pict.crop((zone['left'], zone['top'], zone['right'], zone['bottom']))
    img_io = io.BytesIO()
    cropped.save(img_io, file_format, quality=100)
    img_io.seek(0)
    cf_request_data = {'index':0, 'filename': "filename"}
    if allowed_values:
        cf_request_data['allowed_values'] = allowed_values
        
    response = requests.post(CF_HOST.format("loadimage"), auth=(CF_LOGIN, CF_PASSWORD), files = {'imagefile': img_io}, data=cf_request_data)
    if response.status_code == 200:
        cf_result = response.json().get('objtype')

    app.logger.debug(f"SUBZONE RESULTS {cf_result}")
    return cf_result

def check_unhealthy_zones(pict, suuid):
    # return Location, SensorUUID, Camname, Position, Zones
    app.logger.debug("CHECKING PICTURE ZONES")
    res = {'location': None,
           'sensor_uuid': None,
           'camname': pict.camera_position.camera.camlabel,
           'position': pict.camera_position.poslabel,
           'zones':[],
           'ts': pict.ts
    }
    # pict.zones
    # pict.camera_position.poslabel
    # pict.camera_position.camera.camlabel
    # [zone.zone for zone in pict.zones]
    for zone in pict.zones:
        # Check prev zones here >>>
        app.logger.debug(["ZONE RESULTS", zone.results])
        if zone.results:
            if 'unhealthy' in zone.results:
                prev_three_zones = db.session.query(PictureZone).join(DataPicture).join(CameraPosition).join(Camera).join(Data).join(Sensor).order_by(PictureZone.id.desc()).filter(PictureZone.zone==zone.zone).filter(CameraPosition.poslabel==res['position']).filter(Camera.camlabel==res['camname']).filter(Sensor.uuid==suuid).limit(3).offset(1).all()
                app.logger.debug(["PREV THEE ZONES", zone.id, [(z.results, z.id) for z in prev_three_zones]])
                # Changed results to revisedresults

                if all(['unhealthy' in z.results for z in prev_three_zones]):
                    res['zones'].append({"results": "{} {}".format(zone.zone, zone.results), "fpath": zone.fpath})
    if res['zones']:
        return res


def cache_key():
   args = request.args
   key = request.path + '?' + urllib.parse.urlencode([
     (k, v) for k in sorted(args) for v in sorted(args.getlist(k))
   ])
   return key



def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    TaskBase = celery.Task
    class ContextTask(TaskBase):
        abstract = True
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    return celery


celery = make_celery(app)


def get_zones(pict, n, m):
    width, height = pict.size
    left = [width/m*i for i in range(m)]
    right = [width/m*i for i in range(1, m+1)]
    top = [height/n*i for i in range(n)]
    bottom = [height/n*i for i in range(1, n+1)]
    res = {}
    n = 1
    for l,r in zip(left, right):
        for t,b in zip(top, bottom):
            zone = {'left': int(l),
                    'top': int(t),
                    'right': int(r),
                    'bottom': int(b)}
            res[f'zone{n}'] = zone
            n += 1
    return res

#def get_zones():
#    #2592х1944 224
#    #for a in range(1,12) :
#    #    print (224*a)
#    p = 2592/4
#    q = 1944/3
#    #p==q
#    n = 0
#    res = {}
#    for a in range(0,4) :
#        #    print (int (p*a) )
#        for b in range(0,3) :
#            #        print (int (q*b) )
#            n += 1
#            zone = {'left': int(a*p),
#                    'top': int(b*q),
#                    'right': int((a+1)*p),
#                    'bottom': int((b+1)*q)
#            }
#            res[f'zone{n}'] = zone
#    return res


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        crontab(minute=0, hour='*/3'),
        check_pending_image_notifications.s(),
    )
    sender.add_periodic_task(
        crontab(minute=0, hour='*/1'),
        check_pending_sensor_notifications.s(),
    )


@celery.task
def check_pending_image_notifications():
    with app.app_context():
        print("Checking pending notifications")
        dbusers = db.session.query(User).filter(User.additional_email != None).filter(User.notifications.any(Notification.sent.is_(False))).all()
        if dbusers:
            for dbuser in dbusers:
                notifications = []
                for n in dbuser.notifications:
                    if not n.sent and n.ntype=='image':
                        notifications.append(n.text)
                        n.sent = True
                        db.session.add(n)
                        db.session.commit()
                app.logger.debug(f"Sending user notifications {dbuser.additional_email}")
                if notifications:
                    send_images_email_notification.delay(dbuser.additional_email, notifications)


@celery.task
def check_pending_sensor_notifications():
    with app.app_context():
        print("Checking pending notifications")
        dbusers = db.session.query(User).filter(User.additional_email != None).filter(User.notifications.any(Notification.sent.is_(False))).all()
        if dbusers:
            for dbuser in dbusers:
                notifications = []
                for n in dbuser.notifications:
                    if not n.sent and n.ntype=='sensors':
                        notifications.append(n.text)
                        n.sent = True
                        db.session.add(n)
                        db.session.commit()
                app.logger.debug(f"Sending user notifications {dbuser.additional_email}")
                if notifications:
                    send_sensors_email_notification.delay(dbuser.additional_email, notifications)
                


@celery.task
def send_images_email_notification(email, pict_status_list):
    print("Sending email")
    sender = MAILUSER
    msg = MIMEMultipart('related')
    msg['Subject'] = 'Plantdata Service Notification'
    msg['From'] = sender
    msg['To'] = email

    email_body = """\
<html>
    <head></head>
       <body>

    The following images may need your attention:
    <ul>
    {}
    </ul>
       </body>
</html>
    """

    status_text = []
    email_images = []
    for i, obj in enumerate(pict_status_list):
        p = json.loads(obj)
        figure_template = """
        <p>
        <figure>
        <img src='cid:image{}_{}' alt='missing'/>
        <figcaption>{}</figcaption>
        </figure>
        </p>
        """
        fig_list = []
        for j, z in enumerate(p['zones']):
            fig_html = figure_template.format(i, j, z['results'])
            fig_list.append(fig_html)
            with open(os.path.join(BASEDIR, z['fpath']), 'rb') as img_file:
                msgImage = MIMEImage(img_file.read())
                msgImage.add_header('Content-ID', '<image{}_{}>'.format(i, j))
                email_images.append(msgImage)

        figs = "\n".join(fig_list)

        r = """<li>
        {} {} {} {} {}
        {}
        </li>
        """.format(p['ts'], p['location'], p['sensor_uuid'], p['camname'], p['position'], figs)
        status_text.append(r)

    status_text = "\n".join(status_text)
    email_body = email_body.format(status_text)
    message_text = MIMEText(email_body, 'html')
    msg.attach(message_text)

    for img in email_images:
        msg.attach(img)

    # FIX 
    print("mail ready to be sent")
    s = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    s.ehlo()
    s.starttls()
    #print([MAILUSER, MAILPASS])
    s.login(MAILUSER, MAILPASS)
    s.sendmail(sender, email, msg.as_string())
    s.quit()
    print("mail sent")


@celery.task
def send_sensors_email_notification(email, status_list):
    print("Sending email")
    sender = MAILUSER
    msg = MIMEMultipart('related')
    msg['Subject'] = 'Plantdata Service Notification'
    msg['From'] = sender
    msg['To'] = email

    email_body = """\
<html>
    <head></head>
       <body>
    The following sensor values are outside the scope:
    <ul>
    {}
    </ul>
       </body>
</html>
    """

    status_text = []
    for i, obj in enumerate(status_list):
        p = json.loads(obj)
        r = """<li>
        ts:{} location:{} sensor:{} probe:{} coords:{} label:{} min:{} max: {} <b>value: {}</b>
        </li>
        """.format(p['ts'], p['location'], p['suuid'], p['uuid'], p['coords'], p['label'], p['min'], p['max'], p['value'])
        status_text.append(r)

    status_text = "\n".join(status_text)
    email_body = email_body.format(status_text)
    message_text = MIMEText(email_body, 'html')
    msg.attach(message_text)

    print("mail ready to be sent")
    s = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    s.ehlo()
    s.starttls()
    print([MAILUSER, MAILPASS])
    s.login(MAILUSER, MAILPASS)
    s.sendmail(sender, email, msg.as_string())
    s.quit()
    print("mail sent")
    


@celery.task
def crop_zones(results, cam_names, cam_positions, cam_zones, cam_numsamples, cam_skipsamples, label_text):
    zones = get_zones()
    results_data = []
    with tempfile.TemporaryDirectory(dir=TMPDIR) as temp_dir:
        app.logger.debug("Start zones extract")
        # filter results
        app.logger.debug([cam_names, cam_positions])
        filtered_results = []

        if all([cam_names, cam_positions]):
            cam_names = [x.strip() for x in cam_names.split(",")]
            cam_positions = [int(x.strip()) for x in cam_positions.split(",")]
            app.logger.debug(cam_zones)
            cam_zones = ["zone{}".format(x.strip()) for x in cam_zones.split(",")]
            if cam_skipsamples:
                cam_skipsamples = int(cam_skipsamples)
            if cam_numsamples:
                cam_numsamples = int(cam_numsamples)

            prev_date = None
            sample = 0
            for d in results:
                #if d['lux'] > 10:
                if True:
                    ts = parser.isoparse(d['ts']).strftime("%d-%m-%Y_%H-%M")
                    sdate = parser.isoparse(d['ts']).strftime("%d-%m-%Y")
                    app.logger.debug([d['ts'], ts, sample, len(d['cameras']), ])
                    if len(d['cameras']) > 0:
                        if prev_date == sdate:
                            sample = sample + 1
                        else:
                            sample = 0
                        if cam_numsamples and sample < cam_numsamples:
                            app.logger.debug(f"DAY {ts} SAMPLE {sample}")

                            for cam in d['cameras']:
                                if cam['camlabel'] in cam_names:
                                    camname = cam['camlabel']
                                    pos = cam['positions'][0]
                                    for pos in cam['positions']:
                                        if pos['poslabel'] in cam_positions:
                                            position = str(pos['poslabel'])
                                            if len(pos['pictures']) > 0:
                                                p = pos['pictures'][-1]
                                                #app.logger.debug(f"Filtering results {camname}, {position}, {ts}")
                                                prefix = f"{camname}-{position}-{ts}"
                                                # Saving original_file
                                                p['original'] = p['original'].replace(f'https://dev.plantdata.fermata.tech:5598/api/v{API_VERSION}/p/', '')
                                                orig_fpath = os.path.join(current_app.config['FILE_PATH'], p['original'])
                                                orig_newpath = os.path.join(temp_dir, prefix+".jpg")
                                                if label_text:
                                                    if label_text not in p['label']:
                                                        continue
                                                original = Image.open(orig_fpath)
                                                original.save(orig_newpath, 'JPEG', quality=100)
                                                #app.logger.debug(f"Saving file {orig_newpath}")
                                                for z in zones.keys():
                                                    if z in cam_zones:
                                                        cropped = original.crop((zones[z]['left'], zones[z]['top'], zones[z]['right'], zones[z]['bottom']))
                                                        cropped_path = os.path.join(temp_dir, f"{camname}-{position}-{z}-{ts}" + ".jpg")
                                                        cropped.save(cropped_path, 'JPEG', quality=100)
                                                        app.logger.debug(f"Saving file {cropped_path}")
                    prev_date = sdate

        zfname = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M-") + '-cropped_zones.zip'
        zipname = os.path.join(temp_dir, zfname)
        zipf = zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED)
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file != zfname:
                    zipf.write(os.path.join(root, file))
        zipf.close()
        shutil.move(zipname, os.path.join('/home/annndrey/Dropbox/plantdata', zfname))


#@app.before_first_request
def login_to_classifier():
    app.logger.debug("Logging to CF server")
    login_data = {"username": CF_LOGIN,
                  "password": CF_PASSWORD
                  }

    global CF_TOKEN
    try:
        res = requests.post(CF_HOST.format("token"), json=login_data)
        if res.status_code == 200:
            CF_TOKEN = res.json().get('token')
    except:
        CF_TOKEN = None


def token_required(f):
    @wraps(f)
    def _verify(*args, **kwargs):
        auth_headers = request.headers.get('Authorization', '').split()

        invalid_msg = {
            'message': 'Invalid token. Registeration and / or authentication required',
            'authenticated': False
        }
        expired_msg = {
            'message': 'Expired token. Reauthentication required.',
            'authenticated': False
        }

        if len(auth_headers) != 2:
            return abort(403)

        token = auth_headers[1]
        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        except:
            return abort(403)

        user = User.query.filter_by(login=data['sub']).first()

        if not user:
            abort(403)

        return f(*args, **kwargs)

    return _verify


def authenticate(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not getattr(func, 'authenticated', True):
            return func(*args, **kwargs)

        acct = basic_authentication()  # custom account lookup function

        if acct:
            return func(*args, **kwargs)

        abort(401)
    return wrapper


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)

@auth.error_handler
def unauthorized():
    return make_response(jsonify({'error': 'Unauthorized access'}), 401)

@auth.verify_password
def verify_password(username_or_token, password):
    user = User.verify_auth_token(username_or_token)
    if not user:
        # try to authenticate with username/password
        user = User.query.filter_by(login = username_or_token).first()
        if not user or not user.verify_password(password):
            return False
    g.user = user
    return True

@token_required
def access_picture(path):
    print("PATH")
    print(request.cookies)
    realpath = path
    redirect_path = "/pictures/" + realpath
    response = make_response("")
    response.headers["X-Accel-Redirect"] = redirect_path
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


def process_single_file(uplname, pict):
    app.logger.debug("SAVE FILE")

def process_result(result):
    res = result

    if '_healthy' in result:
        res = '_'.join(result.split('_')[:-1])

    return res

# TODO: async
# process_single_picture
# process_single_zone

@celery.task
def parse_request_pictures(parent_data, camposition_id, req_file, flabel, photo_ts, user_login, sensor_uuid, recognize):
    with app.app_context():
        data = db.session.query(Data).filter(Data.id == parent_data).first()
        
        if not data:
            abort(404)

        camposition = db.session.query(CameraPosition).filter(CameraPosition.id == camposition_id).first()
        if not camposition:
            abort(404)

        picts = []
        picts_unhealthy_status = []
        celery_logger.info("PARSING REQUEST PICTURES")
        #for uplname in sorted(req_files):
        pict = req_file#s.get(uplname)
        fpath = os.path.join(current_app.config['FILE_PATH'], user_login, sensor_uuid)
        celery_logger.info(fpath)
        if not os.path.exists(fpath):
            os.makedirs(fpath)
        #celery_logger.info(["PICT FILESIZE", os.stat(pict).st_size])
        fdata = open(pict, 'rb').read()
        imgbytes = io.BytesIO(fdata)
        imgbytes.seek(0)
        original = Image.open(imgbytes)
        FORMAT = original.format
        fuuid = str(uuid.uuid4())
        fname = fuuid + "." + FORMAT.lower()
        thumbname = fuuid + "_thumb." + FORMAT.lower()
        origname = fuuid + "_orig." + FORMAT.lower()
        fullpath = os.path.join(fpath, fname)
        thumbpath = os.path.join(fpath, thumbname)
        origpath = os.path.join(fpath, origname)
        partpath = os.path.join(user_login, sensor_uuid, fname)
        partthumbpath = os.path.join(user_login, sensor_uuid, thumbname)
        partorigpath = os.path.join(user_login, sensor_uuid, origname)

        with open(fullpath, 'wb') as outf:
            outf.write(fdata)
        
        original.save(origpath, quality=100, subsampling=0)
        
        imglabel = flabel
        celery_logger.info(["UPLNAME", flabel])
        classification_results = ""
        celery_logger.info("FILE SAVED")
        newzones = []

        # Don't recognize if picture is BW
        unique_colors = set()
                
        if recognize:
            if CLASSIFY_ZONES:# and CF_TOKEN:
                # zones = CROP_SETTINGS.get(uplname, None)
                #zones = get_zones(original, 3, 4)
                cf_headers = {'Authorization': 'Bearer ' + CF_TOKEN}
                img_io = io.BytesIO()
                original.save(img_io, FORMAT, quality=100)
                img_io.seek(0)
                response = requests.post(CF_HOST, headers=cf_headers, files = {'croppedfile': img_io})
                if response.status_code == 200:
                    cf_result = response.json().get('objtype')
                    classification_results = json.dumps(cf_result)
                    app.logger.debug(f"CF RESULTS {cf_result}")
                else:
                    classification_results = None

        # Thumbnails
        original.thumbnail((300, 300), Image.ANTIALIAS)
        original.save(thumbpath, FORMAT, quality=90)
        celery_logger.info(["CAMERA TO PICT", camposition.camera.camlabel, camposition.poslabel, imglabel])
        newpicture = DataPicture(fpath=partpath,
                                 label=imglabel,
                                 thumbnail=partthumbpath,
                                 original=partorigpath,
                                 results=classification_results,
        )
        if photo_ts:
            newpicture.ts = photo_ts
            
        db.session.add(newpicture)
        camposition.pictures.append(newpicture)
        db.session.commit()
        picts.append(newpicture)
        data.pictures.append(newpicture)
        db.session.add(data)
        db.session.commit()
        
        # Here we have linked the picture with zones,
        # and can check now for the unhealthy results
        # and send emails
        # TODO FIX - we have no zones anymore
        pict_zones_info = check_unhealthy_zones(newpicture, sensor_uuid)
        if pict_zones_info:
            picts_unhealthy_status.append(pict_zones_info)
        app.logger.debug("NEW PICTURE ADDED")

        if picts_unhealthy_status:
            # add notification
            sensor = db.session.query(Sensor).filter(Sensor.uuid == sensor_uuid).first()
            if sensor:
                if sensor.user.login == user_login:
                    user_email = sensor.user.additional_email
                    if user_email:
                        # update results list:
                        for pict_res in picts_unhealthy_status:
                            pict_res['location'] = sensor.location.address
                            pict_res['sensor_uuid'] = sensor.uuid
                        for p in picts_unhealthy_status:
                            app.logger.debug(["CREATING NOTIFICATION", p])
                            p['ts'] = p['ts'].strftime("%d-%m-%Y %H:%M:%S")
                            newnotification = Notification(user=sensor.user, text=json.dumps(p), ntype='image')
                            db.session.add(newnotification)
                            db.session.commit()
        os.unlink(req_file)


@app.route(f'/api/v{API_VERSION}/token', methods=['POST'])
@cross_origin(supports_credentials=True)
def get_auth_token_post():
    """Access Token API
    ---
    tags: [Authentication,]
    parameters:
      - name: username
        in: body
        required: true
      - name: password
        in: body
        required: true
    responses:
      200:
        description: User is authorised
        schema:
          id: Token
          properties:
            username:
              type: string
              description: User's login, in email format.
              default: "newuser@site.com"
            user_id:
              type: integer
              description: User ID.
              default: 1
            token:
              type: string
              description: JWT Auth token
      401:
        description: UNAUTHORIZED
    """

    username = request.json.get('username')
    password = request.json.get('password')
    user = User.query.filter_by(login = username).first()
    if user:
        if user.verify_password(password):
            token = user.generate_auth_token()
            response = jsonify({ 'token': "%s" % token.decode('utf-8'), "user_id":user.id, "login": user.login, "name": user.name, "company": user.company })
            return response
    return make_response(jsonify({'error': 'Unauthorized access'}), 401)


#@app.route('/api/v1/token', methods=['GET'])
@app.route(f'/api/v{API_VERSION}/token', methods=['GET'])
def get_auth_token():
    token = g.user.generate_auth_token()
    return jsonify({ 'token': "%s" % token })


# SCHEMAS
class UserSchema(ma.ModelSchema):
    class Meta:
        model = User


class SensorTypeSchema(ma.ModelSchema):
    class Meta:
        model = SensorType


class CameraOnlySchema(ma.ModelSchema):
    class Meta:
        model = Camera
        exclude = ['positions', ]
    warnings = ma.Function(lambda obj: obj.warnings)

    # positions = ma.Nested("CameraPositionSchema", many=True, exclude=["camera", "url"])#, exclude=['camera',])

class CameraSchema(ma.ModelSchema):
    class Meta:
        model = Camera
    warnings = ma.Function(lambda obj: obj.warnings)
    positions = ma.Nested("CameraPositionSchema", many=True, exclude=["camera", "url"])#, exclude=['camera',])
    location = ma.Nested("CameraLocationSchema", many=False, exclude=["camera",])


class CameraPositionSchema(ma.ModelSchema):
    class Meta:
        model = CameraPosition
    pictures = ma.Nested("DataPictureSchema", many=True, exclude=["camera_position", "data", "thumbnail"])#, many=False, exclude=['thumbnail', 'camera', 'camera_position', 'data'])
    #image = ma.Function(lambda obj: obj.image)


class CameraLocationSchema(ma.ModelSchema):
    class Meta:
        model = CameraLocation

        
class SensorSchema(ma.ModelSchema):
    class Meta:
        model = Sensor
        exclude = ['data', ]
    numrecords = ma.Function(lambda obj: obj.numrecords)
    mindate = ma.Function(lambda obj: obj.mindate)
    maxdate = ma.Function(lambda obj: obj.maxdate)
    location = ma.Nested("LocationSchema")#, exclude=['camera',])

    
class SensorShortSchema(ma.ModelSchema):
    class Meta:
        model = Sensor
    numrecords = ma.Function(lambda obj: obj.numrecords)
    mindate = ma.Function(lambda obj: obj.mindate)
    maxdate = ma.Function(lambda obj: obj.maxdate)


class PictureZoneSchema(ma.ModelSchema):
    class Meta:
        model = PictureZone

    fpath = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.fpath, _external=True, _scheme='https')))


class DataPictureSchema(ma.ModelSchema):
    class Meta:
        model = DataPicture

    numwarnings = ma.Function(lambda obj: obj.numwarnings if 7 < obj.ts.hour < 19 else 0)
    results = ma.Function(lambda obj: obj.results if 7 < obj.ts.hour < 19 else "[]")
    preview = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.thumbnail, _external=True, _scheme='https')))
    fpath = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.fpath, _external=True, _scheme='https')))
    original = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.original, _external=True, _scheme='https')))
    zones = ma.Nested("PictureZoneSchema", many=True, exclude=["camera_position", "data", "thumbnail", "picture"])


class ImageSchema(ma.ModelSchema):
    class Meta:
        model = DataPicture
        exclude = ['zones', 'camera_position', 'data', 'thumbnail', 'preview']
    #preview = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.thumbnail, _external=True, _scheme='https')))
    fpath = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.fpath, _external=True, _scheme='https')))
    original = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.original, _external=True, _scheme='https')))

    #zones = ma.Nested("PictureZoneSchema", many=True, exclude=["data",])



class LocationSchema(ma.ModelSchema):
    class Meta:
        model = Location


class DataSchema(ma.ModelSchema):
    class Meta:
        model = Data
        exclude = ['pictures', 'sensor']
    cameras = ma.Nested("CameraOnlySchema", many=True, exclude=["data",])
    records = ma.Nested("ProbeDataSchema", many=True)

    @pre_dump(pass_many=True)
    def filter_outliers(self, data, many, **kwargs):
        if many:
            for d in data:
                for p in d.records:
                    if p.value:
                        if p.value < p.prtype.minvalue:
                            p.value = p.prtype.minvalue
                        if p.value > p.prtype.maxvalue:
                            p.value = p.prtype.maxvalue
                            #        else:
                            #            for p in data.records:
                            ##                if p.value:
                            #                    if p.value < p.prtype.minvalue:
                            #                        p.value = p.prtype.minvalue
                            #                    if p.value > p.prtype.maxvalue:
                            #                        p.value = p.prtype.maxvalue

 

    @post_dump(pass_many=True)
    def flattern_data(self, data, many, **kwargs):
        if many:
            outdata = {"labels": [], "data": {}, "cameras": []}
            for d in data:
                outdata['labels'].append(d['ts'])
                if len(d['cameras']) > 0:
                    outdata['cameras'].append(d['cameras'])
                for r in d['records']:
                    datalabel = "{} {}".format(r['label'], r['probe']['uuid'])
                    if datalabel not in outdata['data'].keys():
                        outdata['data'][datalabel] = [r['value']]
                    else:
                        outdata['data'][datalabel].append(r['value'])

            return outdata

        
    #@post_dump(pass_many=True)
    def filter_fields(self, data, many, **kwargs):
        if many:
            pr_labels = {}
            for d in data:
                probes = [r['probe'] for r in d['records']]
                d['probes'] = list({v['uuid']:v for v in probes}.values())
                for pr in d['probes']:
                    pr['values'] = []
                    # logging.debug(pr)
                    if pr['uuid'] not in pr_labels:
                        pr_labels[pr['uuid']] = []

                for k, v in groupby(d['records'], key=lambda x:x['probe']['uuid']):
                    #logging.debug(list(v))
                    for pr in d['probes']:
                        if pr['uuid'] == k:
                            vals = list(v)
                            # Detecting missing points
                            diff = list(set(pr_labels[k]) - set([vl['label'] for vl in vals]))
                            if len(diff) > 0:
                                # logging.debug(vals)
                                for df in diff:
                                    vals.append({'ptype': 'missing', 'value': None, 'label': df, 'probe': {'uuid': k}})
                            for vl in vals:
                                if vl['label'] not in pr_labels[vl['probe']['uuid']]:
                                    pr_labels[vl['probe']['uuid']].append(vl['label'])
                                del vl['probe']
                            pr['values'].extend(vals)
                del d['records']
        return data


class FullDataSchema(ma.ModelSchema):
    class Meta:
        model = Data
        exclude = ['pictures', ]
    cameras = ma.Nested("CameraSchema", many=True, exclude=["data",])


class ProbeSchema(ma.ModelSchema):
    class Meta:
        model = Probe
        exclude = ['values', 'id']


class ProbeShortSchema(ma.ModelSchema):
    class Meta:
        model = Probe
        exclude = ['values', 'id', 'data', 'sensor']


class ProbeDataSchema(ma.ModelSchema):
    class Meta:
        model = ProbeData
        exclude = ['prtype', 'id', 'data']
    ptype = ma.Function(lambda obj: obj.prtype.ptype)
    probe = ma.Nested("ProbeSchema", many=False, exclude=["data", 'sensor'])



class SensorTypeAPI(Resource):
    def __init__(self):
        self.schema = SensorTypeSchema()
        self.m_schema = SensorTypeSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    #@token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self):
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        if not user:
            abort(401)
        sensors = user.sensors
        resp = []
        for s in sensors:
            app.logger.debug([s.limits, s.id])
            #app.logger.debug(dir(s))
            #resp[s.uuid] = []
            rec = {"suuid": s.uuid, "values": [], "limits": {}}
            for d in s.sensortypes:
                rec["values"].append(d.ptype)
                slimit = db.session.query(SensorLimit).filter(SensorLimit.sensor_id==s.id).filter(SensorLimit.prtype_id==d.id).first()
                #app.logger.debug([slimit, s, d])
                if slimit:
                    rec["limits"][d.ptype] = {"minvalue":slimit.minvalue, "maxvalue":slimit.maxvalue}
                else:
                    rec["limits"][d.ptype] = {"minvalue": None, "maxvalue": None}
                #reslist.append(d.ptype)
            resp.append(rec)
        return jsonify(resp), 200


class PictAPI(Resource):
    def __init__(self):
        self.schema = DataPictureSchema()
        self.m_schema = DataPictureSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    #@token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self, path):
        """
        Get picture by URL
        ---
        tags: [Pictures,]
        parameters:
         - in: path
           name: path
           type: string
           required: true
           description: image path
        definitions:
          Picture:
            type: string
            description: Picture URL

        responses:
          200:
            description: Picture URL
            schema:
               $ref: '#/definitions/Picture'
          401:
            description: Not authorized
          404:
            description: URL not found
        """

        auth_cookie = request.cookies.get("auth", "")
        auth_headers = request.headers.get('Authorization', '').split()
        if len(auth_headers) > 0:
            token = auth_headers[1]
        elif len(auth_cookie) > 0:
            token = auth_cookie
        else:
            abort(401)

        data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=data['sub']).first()
        if not user:
            abort(401)
        if not path:
            abort(404)

        realpath = path
        redirect_path = "/pictures/" + realpath
        response = make_response("")
        response.headers["X-Accel-Redirect"] = redirect_path
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Content-Type'] = 'image/jpeg'
        return response

    
class CameraAPI(Resource):
    def __init__(self):
        self.schema = CameraSchema()
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self, id):
        """
        Get camera data
        ---
        tags: [Cameras,]
        parameters:
         - in: path
           name: id
           type: integer
           required: true
           description: Camera ID
        definitions:
          Camera:
            type: object
            description: Camera data
            properties:
              id:
                type: integer
                description: Camera ID
              camlabel:
                type: string
                description: Camera label
              positions:
                type: array
                description: A list of camera positions
                items:
                  type: object
                  description: Camera position
                  properties:
                    id:
                      type: integer
                      description: Camera Position ID
                    poslabel:
                      type: string
                      description: Camera Position Label
                    pictures:
                      type: array
                      items:
                        type: object
                        description: Picture
                        properties:
                          id:
                            type: integer
                            description: Picture ID
                          fpath:
                            type: string
                            description: Picture URL
                          thumbnail:
                            type: string
                            description: Picture thumbnail
                          label:
                            type: string
                            description: Picture label
                          original:
                            type: string
                            description: Picture Original URL
                          results:
                            type: string
                            description: Picture recognition results
                          ts:
                            type: string
                            format: date-time
                            description: Picture timestamp
        responses:
          200:
            description: Camera data
            schema:
               $ref: '#/definitions/Camera'
          401:
            description: Not authorized
          404:
            description: URL not found
        """
        # Join Data Join Sensors
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        if not user:
            abort(403)

        camera = db.session.query(Camera).join(Data).join(Sensor).filter(Sensor.id.in_([s.id for s in user.sensors])).filter(Camera.id==id).first()
        if camera:
            return jsonify(self.schema.dump(camera).data), 200
        return abort(404)


    @token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def post(self):
        """
        Create camera record
        ---
        tags: [Cameras,]
        parameters:
         - in: body
           name: data
           required: true
           description: Camera Record Data
           schema:
               $ref: '#/definitions/CameraRecord'
        definitions:
          CameraRecord:
            type: object
            description: Camera Record Data
            properties:
              id:
                type: integer
                description: Camera ID
              camlabel:
                type: string
                description: Camera label
              positions:
                type: array
                description: A list of camera positions
                items:
                  type: object
                  description: Camera position
                  properties:
                    id:
                      type: integer
                      description: Camera Position ID
                    poslabel:
                      type: string
                      description: Camera Position Label
        responses:
          200:
            description: Camera Record Data
            schema:
               $ref: '#/definitions/CameraRecord'
          401:
            description: Not authorized
          404:
            description: URL not found
        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        request.get_json()
        camname = request.json.get("camlabel")
        camposition = request.json.get("camposition")
        
   

class ImagesAPI(Resource):
    def __init__(self):
        self.schema = ImageSchema()
        self.images_schema = ImageSchema(many=True)
        self.image_zones_schema = PictureZoneSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self):
        """
        Get saved images filtered by given parameters
        ---
        tags: [Pictures,]
        parameters:
         - in: query
           name: uuid
           type: string
           required: false
           description: Sensor UUID
         - in: query
           name: ignore_night_photos
           type: boolean
           required: false
           description: Select only images taken on the light period
         - in: query
           name: ts_from
           type: string
           format: date-time
           example: "2017-01-01 10:21"
           required: false
           description: Return data starting from the given timestamp
         - in: query
           name: ts_to
           type: string
           format: date-time
           example: "2017-01-01 10:21"
           required: false
           description: Return data before the given timestamp
         - in: query
           name: label_text
           type: string
           required: false
           description: Selech only photos with label matching the search string
         - in: query
           name: cam_names
           type: string
           required: false
           default: CAM1, CAM2
           description: A comma-separated list of camera names. If no camera name provided, all cameras would be returned
         - in: query
           name: cam_positions
           type: string
           required: false
           default: 1, 2, 3
           description: A comma-separated list of camera positions. If no position provided, all positions would be returned
         - in: query
           name: cam_zones
           type: string
           required: false
           default: zone1, zone2, zone3
           description: A comma-separated list of camera zones. If no zone is provided, all zones would be returned.
        definitions:
          PictureObject:
            type: object
            description: URLList
            properties:
              numrecords:
                type: integer
                description: Number of records found
              data:
                type: array
                description: A list of Picture/PictureZone Objects found
                items:
                  type: object
                  description: A single Picture/PictureZone record
                  properties:
                    id:
                      type: integer
                      description: Picture/PictureZone ID
                    ts:
                      type: string
                      format: date-time
                      description: Timestamp
                    fpath:
                      type: string
                      description: Picture URL with zones displayed
                    label:
                      type: string
                      description: Picture label
                    zone:
                      type: string
                      description: PictureZone label
                    original:
                      type: string
                      description: Picture Original URL without zones
                    results:
                      type: string
                      description: Picture/PictureZone recognition results
        responses:
          200:
            description: Pictures found
            schema:
               $ref: '#/definitions/PictureObject'
          401:
            description: Not authorized
          404:
            description: Nothing found
        """
        suuid = request.args.get('uuid', None)
        dataid = request.args.get('dataid', None)
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        ts_from = request.args.get('ts_from', None)
        ts_to = request.args.get('ts_to', None)
        cam_names = request.args.get('cam_names', False)
        cam_positions = request.args.get('cam_positions', False)
        cam_zones = request.args.get('cam_zones', False)
        ignore_night_photos = request.args.get('ignore_night_photos', False)
        label_text = request.args.get('label_text', False)

        data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        daystart = dayend = None

        user = User.query.filter_by(login=data['sub']).first()
        if not user:
            abort(401)
        if not suuid:
            abort(404)


        first_rec_day = db.session.query(sql_func.min(Data.ts)).filter(Data.sensor.has(Sensor.uuid == suuid)).first()[0]
        last_rec_day = db.session.query(sql_func.max(Data.ts)).filter(Data.sensor.has(Sensor.uuid == suuid)).first()[0]

        if not all([ts_from, ts_to]):

            if all([first_rec_day, last_rec_day]):
                day_st = last_rec_day.replace(hour=0, minute=0)
                day_end = last_rec_day.replace(hour=23, minute=59, second=59)
            else:
                abort(404)
        else:
            day_st = datetime.datetime.strptime(ts_from, '%d-%m-%Y %H:%M')
            #day_st = day_st.replace(hour=0, minute=0)
            day_end = datetime.datetime.strptime(ts_to, '%d-%m-%Y %H:%M')
            #day_end = day_end.replace(hour=23, minute=59, second=59)

        app.logger.debug(["SEARCH PICTURES", day_st, day_end])
        if cam_zones:
            image_query = db.session.query(PictureZone).join(DataPicture).join(CameraPosition).join(Camera).join(Data).order_by(DataPicture.ts).filter(DataPicture.ts >= day_st).filter(DataPicture.ts <= day_end)
        else:
            image_query = db.session.query(DataPicture).join(Data).join(CameraPosition).join(Camera).join(PictureZone).order_by(DataPicture.ts).filter(DataPicture.ts >= day_st).filter(DataPicture.ts <= day_end)

        if ignore_night_photos:
            image_query = image_query.filter(Data.lux > 30)
        if suuid:
            image_query = image_query.filter(Data.sensor.has(Sensor.uuid == suuid))
        if cam_names:
            cam_labels = set([x.strip() for x in cam_names.split(",")])
            image_query = image_query.filter(Camera.camlabel.in_(cam_labels))
        if cam_positions:
            pos_labels = set([int(x.strip()) for x in cam_positions.split(",")])
            image_query = image_query.filter(CameraPosition.poslabel.in_(pos_labels))
        if cam_zones:
            zone_labels = set([x.strip() for x in cam_zones.split(",")])
            image_query = image_query.filter(PictureZone.zone.in_(zone_labels))
        if label_text:
            image_query = image_query.filter(PictureZone.results.ilike(r"%{}%".format(label_text)))
        res_data = image_query.all()
        if cam_zones:
            res_json = self.image_zones_schema.dump(res_data).data
        else:
            res_json = self.images_schema.dump(res_data).data

        if res_data:
            res = {"numrecords": len(res_data),
                   'data': res_json
            }

            return jsonify(res), 200

        abort(404)


class ProbeAPI(Resource):
    def __init__(self):
        self.schema = ProbeSchema()
        self.m_schema = ProbeShortSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    def get(self):
        """
        GET Get probe [TODO: Fix description]
        ---
        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        puuid = request.args.get('puuid', None)
        suuid = request.args.get('suuid', None)

        sensor = db.session.query(Sensor).filter(Sensor.uuid == suuid).first()
        app.logger.debug(["SENSOR", suuid, puuid, sensor, user])
        if sensor:
            if sensor.user != user:
                abort(403)
        if puuid:
            probe = db.session.query(Probe).join(Sensor).filter(Probe.uuid == puuid).filter(Sensor.uuid == suuid).first()
            if probe:
                return jsonify(self.schema.dump(probe).data), 200
        elif suuid:
            probes = db.session.query(Probe).join(Sensor).filter(Sensor.uuid == suuid)
            # HIDE PROBES            
            probes = probes.filter(Probe.id.notin_([362, 356]))
            probes = probes.all()
            
            return jsonify(self.m_schema.dump(probes).data), 200
        else:
            # No suuid provided, return all user's probes
            probes = [p for sens in user.sensors for p in sens.probes]
            return jsonify(self.m_schema.dump(probes).data), 200

        abort(404)


    @token_required
    @cross_origin()
    def post(self):
        """
        POST Create probe [TODO: Fix description]
        ---
        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        puuid = request.form.get('puuid', None)
        did = request.form.get('did', None)
        datarecord = db.session.query(Data).filter(Data.id == did).first()
        suuid  = request.form.get('suuid', None)
        sensor = db.session.query(Sensor).filter(Sensor.uuid == suuid).first()
        x  = request.form.get('x', None)
        y  = request.form.get('y', None)
        z  = request.form.get('z', None)
        row = request.form.get('row', None)
        col = request.form.get('col', None)
        plabel = request.form.get('plabel', None)
        if sensor:
            if sensor.user != user:
                abort(403)

        probe = db.session.query(Probe).filter(Probe.uuid == puuid).first()
        if not probe:
            newprobe = Probe(sensor=sensor, uuid=puuid, data=datarecord, label=plabel)
            if x:
                newprobe.x = x
            if y:
                newprobe.y = y
            if z:
                newprobe.z = z
            if row:
                newprobe.row = row
            if col:
                newprobe.row = col

                
            db.session.add(newprobe)
            db.session.commit()
            return jsonify(self.schema.dump(newprobe).data), 201
        else:
            return jsonify(self.schema.dump(probe).data), 409
        abort(404)



# Camera locations warnings API here:
# example:
# [(c[0].data.ts.strftime("%d-%m-%y %H:%M"), c[1].posx, c[1].posy, c[1].posz, c[1].camlabel, c[0].numwarnings) for c in db.session.query(Camera, CameraLocation).join(Data).join(Sensor).join(Location).join(CameraLocation, Camera.camlabel==CameraLocation.camlabel).filter(Data.ts > ts_from).filter(Location.id == 3).all()]


class SensorLimitsAPI(Resource):
    def __init__(self):
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])


    @token_required
    @cross_origin()
    #@cache.cached(timeout=300, key_prefix=cache_key)
    def get(self):
        """
        Sensor Limits
        TODO Fix description
        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        
        user = User.query.filter_by(login=udata['sub']).first()
        if not user:
            abort(403)
        suuid = request.args.get('suuid', None)
        ptype = request.args.get('ptype', None)
        if ptype:
            sensortype = db.session.query(SensorType).filter(SensorType.ptype==ptype).first()
        if suuid:
            sensor = db.session.query(Sensor).filter(Sensor.uuid==suuid).first()
        if sensortype and sensor:
            sensorlimit = db.session.query(SensorLimit).filter(SensorLimit.sensor==sensor).filter(SensorLimit.prtype==sensortype).first()
        response = {"min": None, "max": None, "ptype": ptype}
        if sensorlimit:
            response['min'] = sensorlimit.minvalue
            response['max'] = sensorlimit.maxvalue
        return jsonify(response), 200
            
    @token_required
    @cross_origin()
    #@cache.cached(timeout=300, key_prefix=cache_key)
    def post(self):
        """
        Sensor Limits
        TODO Fix description
        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        
        user = User.query.filter_by(login=udata['sub']).first()
        if not user:
            abort(403)
        suuid = request.json.get('suuid', None)
        if not suuid:
            return make_response(jsonify({'error': 'No suuid provided'}), 400)
        
        ptype = request.json.get('ptype', None)
        if not ptype:
            return make_response(jsonify({'error': 'No ptype provided'}), 400)
        
        minvalue = request.json.get('minvalue', None)
        maxvalue = request.json.get('maxvalue', None)
        
        if suuid:
            sensor = db.session.query(Sensor).filter(Sensor.uuid==suuid).first()

        if sensor and not sensor in user.sensors:
            abort(403)
            

        if ptype:
            sensortype = db.session.query(SensorType).filter(SensorType.ptype==ptype).filter(SensorType.sensor_id==sensor.id).first()
            app.logger.debug(["STYPE", sensortype, ptype, sensor.id])
            if not sensortype:
                sensortype = SensorType(ptype=ptype, sensor=sensor)
                db.session.add(sensortype)
                db.session.commit()
        if sensortype and sensor:
            sensorlimit = db.session.query(SensorLimit).filter(SensorLimit.sensor==sensor).filter(SensorLimit.prtype==sensortype).first()
        if not sensorlimit:
            sensorlimit = SensorLimit(sensor=sensor, prtype=sensortype)
            
        sensorlimit.minvalue = minvalue
        sensorlimit.maxvalue = maxvalue
        db.session.add(sensorlimit)
        db.session.commit()
        response = {"min": sensorlimit.minvalue, "max": sensorlimit.maxvalue, "ptype": ptype, "suuid":suuid}
        return jsonify(response), 201
    
        
class LocationWarningsAPI(Resource):
    def __init__(self):
        #self.schema = ProbeDataSchema()
        #self.m_schema = ProbeDataSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self):
        """
        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        
        user = User.query.filter_by(login=udata['sub']).first()
        if not user:
            abort(403)
            
        suuid = request.args.get('suuid', None)
        ts_from = request.args.get('ts_from', None)
        ts_to = request.args.get('ts_to', None)
        output = {}
        
        if not suuid or suuid == '':
            suuid = 'all'
        if not ts_from or ts_from == '':
            ts_from = datetime.datetime.now().replace(hour=0, minute=0, second=0)
        else:
            ts_from = int(ts_from)
            ts_from = datetime.datetime.fromtimestamp(ts_from).replace(hour=0, minute=0, second=0)
            
        if not ts_to or ts_to == '':
            ts_to = datetime.datetime.now().replace(hour=23, minute=59, second=59)
        else:
            ts_to = int(ts_to)
            ts_to = datetime.datetime.fromtimestamp(ts_to).replace(hour=23, minute=59, second=59)
            
        app.logger.debug(["DATETIME", ts_from, ts_to])

        warnings_query = db.session.query(Camera, CameraLocation).join(Data).join(Sensor).join(Location).join(CameraLocation, Camera.camlabel==CameraLocation.camlabel).filter(Data.ts.between(ts_from, ts_to))# <= ts_to).filter(Data.ts >= ts_from)
        
        if suuid == 'all':
            warnings_query = warnings_query.filter(Sensor.id.in_([s.id for s in user.sensors]))
            warnings_query = warnings_query.filter(CameraLocation.location_id.in_([s.location.id for s in user.sensors]))
        else:
            warnings_query = warnings_query.filter(Sensor.uuid == suuid)
            
        outdata = warnings_query.all()
        # TODO Local coords system
        app.logger.debug([(c[0].data.ts, c[1].posx, c[1].posy, c[1].posz, c[1].camlabel, c[0].numwarnings) for c in outdata])
        for c in outdata:
            if c[0].x is not None:
                x = c[0].x
            else:
                x = c[1].posx
                
            if c[0].y is not None:
                y = c[0].y
            else:
                y = c[1].posy
                
            if c[0].z is not None:
                z = c[0].z
            else:
                z = c[1].posz
                
            outdict = {"ts": c[0].data.ts,
                       "x": x,
                       "y": y,
                       "z": z,
                       "numwarnings":c[0].numwarnings if 7 < c[0].data.ts.hour < 19 else 0,
                       "camlabel": c[1].camlabel,
                       "camid": c[0].id,
                       "camlocation": c[1].location.address
            }
            key = int(c[0].data.ts.timestamp())
            if key not in output.keys():
                output[key] = [outdict,]
            else:
                output[key].append(outdict)
                
        return jsonify(output), 200


class SensorsStatsAPI(Resource):
    def __init__(self):
        #self.schema = ProbeDataSchema()
        #self.m_schema = ProbeDataSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self):
        """
        GET Get sensors stats. In case of no sensor UUID provided 
        return all user's sensor stats. 

        The returning values are: 
        * overall plants health: percentage of healthy plants
        * Number of diseased zones discovered
        * number of unusual spikes of sensors data
        ---
        tags: [Sensors,]
        parameters:
         - in: query
           name: suuid
           type: string
           required: false
           description: Sensor UUID
         - in: query
           name: numentries
           type: number
           required: false
           description: Number of diseased zones to return
         - in: query
           name: output
           type: array
           items:
             type: string
             enum: [diseased_zones, health, spikes, basic_stats]
           required: false
           description: A list of output parameters. If nothing provided, all values are returned
         - in: query
           name: ts_from
           type: string
           format: date-time
           example: "1595181421"
           required: false
           description: Unix timestamp in seconds
         - in: query
           name: ts_to
           type: string
           format: date-time
           example: "1595181421"
           required: false
           description: Unix timestamp in seconds
        definitions:
          SensorStats:
            type: object
            description: SensorData
            properties:
              mindate:
                type: string
                format: date-time
                description: The earliest record date
              maxdate:
                type: string
                format: date-time
                description: The latest record date
              health:
                type: integer
                description: Overall plants health, in percents
              numspikes:
                type: integer
                description: Unusual spikes of sensors data count 
              diseased_zones:
                type: array
                description: Diseased zones discovered, for the last 7 days
                items:
                  type: object
                  description: A single data record
                  properties:
                    id:
                      type: integer
                      description: Data ID
                    ts:
                      type: integer
                      description: Number of diseased zones discovered per day
        responses:
          200:
            description: Sensor Stats
            schema:
               $ref: '#/definitions/SensorStats'
          400:
            description: Bad request
          401:
            description: Not authorized
          404:
            description: URL not found

        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        
        user = User.query.filter_by(login=udata['sub']).first()
        if not user:
            abort(403)
            
        suuid = request.args.get('suuid', None)
        ts_from = request.args.get('ts_from', None)
        ts_to = request.args.get('ts_to', None)
        output_params = request.args.getlist('output', None)
        numentries = request.args.get('numentries', 7)
        numentries = int(numentries)

        output = {}
        if output_params:
            if 'health' in output_params:
                output['health'] = 0
            if 'spikes' in output_params:
                output['spikes'] = 0
            if 'diseased_zones' in output_params:
                output['diseased_zones'] = 0
            if 'basicstats' in output_params:
                output['basic_stats'] = 0
        else:
            output = {"health":0, "spikes": 0, "diseased_zones": 0, 'basic_stats': 0}
            
        output['locdimensions'] = {}
        for s in user.sensors:
            output['locdimensions'][s.uuid] = {"x": s.location.dimx, "y": s.location.dimy, "z": s.location.dimz}
        
        # if no suuid provided, collect stats for all user's sensors
        # if no ts_from or/and ts_to provided, collect stats for today's day
        
        #if any(len(p)==0 if p is not None else False for p in [suuid, ts_from, ts_to]):
        #    app.logger.debug("Wrong params")
        #    fabort(400, "Wrong parameter's value")

        #if any(p is None for p in [suuid, ts_from, ts_to]):
        #    app.logger.debug("Missong params")
        #    fabort(400, "Missing values")
        if not suuid or suuid == '':
            suuid = 'all'
        if not ts_from or ts_from == '':
            ts_from = datetime.datetime.now().replace(hour=0, minute=0, second=0)
        else:
            ts_from = int(ts_from)
            ts_from = datetime.datetime.fromtimestamp(ts_from).replace(hour=0, minute=0, second=0)
            
        if not ts_to or ts_to == '':
            ts_to = datetime.datetime.now().replace(hour=23, minute=59, second=59)
        else:
            ts_to = int(ts_to)
            ts_to = datetime.datetime.fromtimestamp(ts_to).replace(hour=23, minute=59, second=59)

        grouped_ts_from = ts_to - datetime.timedelta(days=numentries)
        
        app.logger.debug(["STATS", suuid, ts_from, ts_to, grouped_ts_from])

        sensor = db.session.query(Sensor).filter(Sensor.uuid == suuid).first()
        
        if sensor:
            if sensor.user != user:
                abort(403)

        if ( output_params and 'health' in output_params ) or ( output_params and 'diseased_zones' in output_params ) or not output_params:

                
            ## Overall health
            # Fixed for new results
            # TODO: add count unhealthy results for a particular picture
            all_unhealthy_zones = db.session.query(func.count(DataPicture.id)).join(Data).join(Sensor).filter(DataPicture.results.like('%unhealthy%')).filter(DataPicture.ts >= ts_from).filter(DataPicture.ts <= ts_to).filter(extract("hour", DataPicture.ts) > 7).filter(extract("hour", DataPicture.ts) < 19)
            # Fixed for new results
            grouped_zones = db.session.query(DataPicture.ts, func.count(DataPicture.id)).join(Data).join(Sensor).filter(DataPicture.results.like('%unhealthy%')).filter(DataPicture.ts >= grouped_ts_from).filter(DataPicture.ts <= ts_to).filter(extract("hour", DataPicture.ts) > 7).filter(extract("hour", DataPicture.ts) < 19)
        
            all_zones = db.session.query(func.count(DataPicture.id)).join(Data).join(Sensor).filter(DataPicture.ts >= ts_from).filter(DataPicture.ts <= ts_to)

            
            
            if suuid == 'all':
                app.logger.debug(["STATS suuid", [s.uuid for s in user.sensors]])
                all_unhealthy_zones = all_unhealthy_zones.filter(Sensor.uuid.in_([s.uuid for s in user.sensors]))
                grouped_zones = grouped_zones.filter(Sensor.uuid.in_([s.uuid for s in user.sensors]))
                all_zones = all_zones.filter(Sensor.uuid.in_([s.uuid for s in user.sensors]))
            else:
                all_unhealthy_zones = all_unhealthy_zones.filter(Sensor.uuid == suuid)
                grouped_zones = grouped_zones.filter(Sensor.uuid == suuid)
                all_zones = all_zones.filter(Sensor.uuid == suuid)
            
            grouped_zones = [(g[0].replace(hour=0, minute=0, second=0), g[1]) for g in grouped_zones.group_by(func.year(DataPicture.ts), func.month(DataPicture.ts), func.day(DataPicture.ts)).all()]
            app.logger.debug(["GROUPED ZONES", grouped_zones])
            date_range = [ts_to.replace(hour=0, minute=0, second=0) - datetime.timedelta(days=x) for x in range(numentries)][::-1]
            
            app.logger.debug(["GROUPED ZONES00", [g[0].strftime('%d-%m-%Y') for g in grouped_zones], [d.strftime( '%d-%m-%Y') for d in date_range]])
            
            for d in date_range:
                if d.strftime('%d-%m-%Y') not in [g[0].strftime('%d-%m-%Y') for g in grouped_zones]:
                    grouped_zones.append((d, 0))
            # >>>>> Stopped here
            #[g[0] for g in grouped_zones]
            app.logger.debug(["GROUPED ZONES0", grouped_zones])
            grouped_zones = sorted(grouped_zones, key=lambda tup: tup[0])
            grouped_zones = [{"name":g[0], "amount":g[1]} for g in grouped_zones]
            app.logger.debug(["GROUPED ZONES1", grouped_zones])
        
            all_unhealthy_zones = all_unhealthy_zones.scalar()
        
            all_zones = all_zones.scalar()
            all_healthy_zones = all_zones - all_unhealthy_zones
        
            if all_zones > 0:
                overall_health = int(round((all_healthy_zones/all_zones) * 100))
            else:
                overall_health = 100
            
            if ( output_params and 'health' in output_params ) or not output_params:
                output['health'] = overall_health
            if ( output_params and 'diseased_zones' in output_params ) or not output_params:
                output['diseased_zones'] = grouped_zones #all_unhealthy_zones
        
            ##app.logger.debug(["STATS", {"overall_health": overall_health, "unhealthy_zones": all_unhealthy_zones, "all zones": all_zones}])

        
        if ( output_params and 'spikes' in output_params ) or not output_params:                

            # number of unusual spikes
            spikes = db.session.query(func.count(ProbeData.id)).join(Data).join(Probe).join(Sensor).filter(Data.ts > ts_from).filter(Data.ts < ts_to)
            if suuid == 'all':
                spikes = spikes.filter(Sensor.uuid.in_([s.uuid for s in user.sensors]))
            else:
                spikes = spikes.filter(Sensor.uuid == suuid)
            
            if suuid == 'all':
                sensors = user.sensors
            else:
                sensors = db.session.query(Sensor).filter(Sensor.uuid == suuid).all()
            
            numspikes = 0 
            for s in sensors:
                for l in s.limits:
                    limit_type = l.prtype.ptype
                    minvalue = l.minvalue
                    maxvalue = l.maxvalue
                    # HIDE PROBES
                    sp = spikes.filter(ProbeData.ptype==limit_type).filter(not_(ProbeData.value.between(minvalue,maxvalue))).filter(ProbeData.probe_id.notin_([362, 356]))
                    numsp = sp.scalar()
                    numspikes = numspikes + numsp
                    app.logger.debug(["SPIKES", limit_type, minvalue, maxvalue, numsp])
                
            output['spikes'] = numspikes
            app.logger.debug(["TOTAL SPIKES", numspikes])


            # Data stats: min, max, mean
        if ( output_params and 'basicstats' in output_params ) or not output_params:

            probe_data = db.session.query(ProbeData).join(Data).join(Probe).join(Sensor).filter(Data.ts >= grouped_ts_from).filter(Data.ts < ts_to)
            # HIDE PROBES            
            probe_data = probe_data.filter(ProbeData.probe_id.notin_([362, 356]))
            if suuid == 'all':
                probe_data = probe_data.filter(Sensor.uuid.in_([s.uuid for s in user.sensors]))
            else:
                probe_data = probe_data.filter(Sensor.uuid == suuid)
                
            probe_data_output = {}
            for d in probe_data.all():
                timeofday = 'night'
                if 7 <= d.data.ts.hour <= 19:
                    timeofday = "day"
                
                date_key = d.data.ts.replace(hour=0, minute=0, second=0)
                date_key = "{} {}".format(d.data.ts.strftime('%d-%m-%Y'), timeofday)
                if date_key not in probe_data_output.keys():
                    probe_data_output[date_key] = {}
                    if not d.prtype.ptype in probe_data_output[date_key].keys():
                        probe_data_output[date_key][d.prtype.ptype] = [d.value, ]
                    else:
                        probe_data_output[date_key][d.prtype.ptype].append(d.value)
                else:
                    if not d.prtype.ptype in probe_data_output[date_key].keys():
                        probe_data_output[date_key][d.prtype.ptype] = [d.value, ]
                    else:
                        probe_data_output[date_key][d.prtype.ptype].append(d.value)
            probe_data_list_output = []
            
            for k in probe_data_output.keys():
                param_output = []
                for p in probe_data_output[k].keys():
                    data_array = probe_data_output[k][p]
                    param_output.append({"min": round(min(data_array), 2), "max": round(max(data_array), 2), "mean": round(mean(data_array), 2), "name": p})
                probe_data_list_output.append({"name": k, "values": param_output})
            #app.logger.debug("ProbeData")
            #app.logger.debug(probe_data_output)
            output['basic_stats'] = probe_data_list_output
            #app.logger.debug(["ProbeData", [(d.data.ts.strftime('%d-%m-%Y'), d.prtype.ptype, d.value, d.ptype, d.label) for d in probe_data.all()]])
            
        output["ts_from"] = ts_from
        output["ts_to"] = ts_to
        #app.logger.debug(["STATS", {"overall_health": overall_health, "unhealthy_zones": all_unhealthy_zones, "all zones": all_zones}])
        
        return jsonify(output), 200
        

class ProbeDataAPI(Resource):
    def __init__(self):
        self.schema = ProbeDataSchema()
        self.m_schema = ProbeDataSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self):
        """
        GET Get probe data [TODO: Fix description]
        ---
        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        puuid = request.form.get('puuid', None)
        suuid = request.form.get('suuid', None)
        did = request.form.get('did', None)
        sensor = db.session.query().filter(Sensor.uuid == suuid).first()

        abort(404)


    @token_required
    @cross_origin()
    def post(self):
        """
        POST Create probe [TODO: Fix description]
        ---
        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        pid = request.form.get('pid', None)
        suuid = request.form.get('suuid', None)
        did = request.form.get('did', None)

        sensor = db.session.query(Sensor).filter(Sensor.uuid == suuid).first()
        value = request.form.get('value', None)
        ptype = request.form.get('ptype', None)
        label = request.form.get('label', None)

        app.logger.debug(["PDATA", value, ptype, label])

        if not value:
            return make_response(jsonify({'error': 'No value provided'}), 400)

        if not ptype:
            return make_response(jsonify({'error': 'No ptype provided'}), 400)

        if not label:
            return make_response(jsonify({'error': 'No label provided'}), 400)

        if sensor:
            if sensor.user != user:
                abort(403)
            probe = db.session.query(Probe).filter(Probe.id == pid).first()
            datarecord = db.session.query(Data).filter(Data.id == did).first()
            if not probe:
                abort(404)
            if not datarecord:
                abort(404)
            newprobedata = ProbeData(probe=probe, value=value, label=label, ptype=ptype)
            db.session.add(newprobedata)
            db.session.commit()
            return jsonify(self.schema.dump(newprobedata).data), 201

        abort(404)


class DataAPI(Resource):
    def __init__(self):
        self.schema = DataSchema()
        self.m_schema = DataSchema(many=True)
        self.f_schema = FullDataSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    def fill_empty_dates(self, query):
        pictures = {p.id: p.pictures for p in query.all()}
        df = pd.read_sql(query.statement, query.session.bind)
        df = df.assign(ts=df.ts.dt.round('T'))
        r = pd.date_range(start=df.ts.min(), end=df.ts.max(), freq="T")
        df = df.set_index('ts').reindex(r).fillna(0.0).rename_axis('ts').reset_index()
        app.logger.debug("FILLING EMPTY DATES")
        #app.logger.debug(df.to_dict('records'))
        app.logger.debug(df)
        #app.logger.debug(r)
        #return df.values.tolist()
        #return query.all()
        res = df.to_dict('records')
        # restore data pictures
        for d in res:
            if d['id'] == 0:
                d['pictures'] = []
            else:
                d['pictures'] = pictures[int(d['id'])]

        return res

    @token_required
    @cross_origin()
    #@cache.cached(timeout=300, key_prefix=cache_key)
    def get(self):
        """
        Get sensors data
        ---
        tags: [Sensors,]
        parameters:
         - in: path
           name: id
           type: integer
           required: false
           description: Data ID
         - in: query
           name: uuid
           type: string
           required: false
           description: Sensor UUID
         - in: query
           name: puuid
           type: string
           required: false
           description: Probe UUID
         - in: query
           name: ts_from
           type: string
           format: date-time
           example: "2017-01-01 10:21"
           required: false
           description: Return data starting from the given timestamp
         - in: query
           name: ts_to
           type: string
           format: date-time
           example: "2017-01-01 10:21"
           required: false
           description: Return data before the given timestamp
        definitions:
          SensorData:
            type: object
            description: SensorData
            properties:
              numrecords:
                type: integer
                description: Number of records for a particular sensor
              mindate:
                type: string
                format: date-time
                description: The earliest record date
              maxdate:
                type: string
                format: date-time
                description: The latest record date
              data:
                type: array
                description: Data records for the specified sensor
                items:
                  type: object
                  description: A single data record
                  properties:
                    id:
                      type: integer
                      description: Data ID
                    ts:
                      type: string
                      format: date-time
                      description: Data record timestamp
                    probes:
                      type: array
                      items:
                        type: object
                        description: Probe data
                        properties:
                         id:
                           type: integer
                           description: Probe ID
                         uuid:
                           type: string
                           description: Probe UUID
                         values:
                           type: array
                           description: A list of probe values
                           items:
                             type: object
                             description: Probe data value
                             properties:
                               id:
                                 type: integer
                                 description: Probe Data ID
                               value:
                                 type: number
                                 format: double
                                 description: Probe Data value
                               label:
                                 type: string
                                 description: Probe Data label
                               ptype:
                                 type: string
                                 description: Probe Data type
                    cameras:
                      type: array
                      items:
                        type: object
                        description: Camera data
                        properties:
                         id:
                           type: integer
                           description: Camera ID
                         camlabel:
                           type: string
                           description: Camera label
                         positions:
                           type: array
                           description: A list of camera positions
                           items:
                             type: object
                             description: Camera position
                             properties:
                               id:
                                 type: integer
                                 description: Camera Position ID
                               poslabel:
                                 type: string
                                 description: Camera Position Label
                               pictures:
                                 type: array
                                 items:
                                   type: object
                                   description: Picture
                                   properties:
                                     id:
                                       type: integer
                                       description: Picture ID
                                     fpath:
                                       type: string
                                       description: Picture URL with zones displayed
                                     thumbnail:
                                       type: string
                                       description: Picture thumbnail
                                     label:
                                       type: string
                                       description: Picture label
                                     original:
                                       type: string
                                       description: Picture Original URL without zones
                                     results:
                                       type: string
                                       description: Picture recognition results
                                     ts:
                                       type: string
                                       format: date-time
                                       description: Picture timestamp
                                     zones:
                                       type: array
                                       description: A list of picture zones
                                       items:
                                         type: object
                                         description: Picture zone
                                         properties:
                                          id:
                                            type: integer
                                            description: Picture Zone ID
                                          fpath:
                                            type: string
                                            description: Picture Zone URL
                                          label:
                                            type: string
                                            description: Picture Zone label
                                          results:
                                            type: string
                                            description: Picture zone recognition results
                                          ts:
                                            type: string
                                            format: date-time
                                            description: Picture zone timestamp

        responses:
          200:
            description: Sensor data
            schema:
               $ref: '#/definitions/SensorData'
          401:
            description: Not authorized
          404:
            description: URL not found
        """
        app.logger.debug("GET DATA")

        suuid = request.args.get('suuid', None)
        puuid = request.args.get('puuid', None)
        dataid = request.args.get('dataid', None)
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        ts_from = request.args.get('ts_from', None)
        ts_to = request.args.get('ts_to', None)
        fill_date = request.args.get('fill_date', False)
        export_zones = request.args.get('export_zones', False)
        export_data = request.args.get('export', False)
        full_data = request.args.get('full_data', False)
        cam_names = request.args.get('cam_names', False)
        cam_positions = request.args.get('cam_positions', False)
        cam_zones = request.args.get('cam_zones', False)
        cam_numsamples = request.args.get('cam_numsamples', False)
        ignore_night_photos = request.args.get('ignore_night_photos', False)
        label_text = request.args.get('label_text', False)
        compact_data = request.args.get('compact', False)
        dataonly = request.args.get('dataonly', False)
        unixdate = request.args.get('unixdate', False)
        cam_skipsamples = request.args.get('cam_skipsamples', False)
        data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        daystart = dayend = None
        
        # By default show data for the last recorded day
        #
        user = User.query.filter_by(login=data['sub']).first()
        
        if not user:
            abort(401)
        
        if suuid:
            sensor = db.session.query(Sensor).filter(Sensor.uuid == suuid).all()
        else:
            sensor = db.session.query(Sensor).filter(Sensor.uuid.in_([s.uuid for s in user.sensors])).all()
        if user not in [s.user for s in sensor]:
            abort(403)
            
        if not dataid:
            first_rec_day = db.session.query(sql_func.min(Data.ts)).filter(Data.sensor.has(Sensor.uuid.in_([s.uuid for s in sensor]))).first()[0]
            last_rec_day = db.session.query(sql_func.max(Data.ts)).filter(Data.sensor.has(Sensor.uuid.in_([s.uuid for s in sensor]))).first()[0]
            app.logger.debug(["GET DATA 1", first_rec_day, last_rec_day])
            if not all([ts_from, ts_to]):
                if all([first_rec_day, last_rec_day]):
                    # IF NO DATES SPECIFIED,
                    # SHOW ONLY LAST DAY RECORDS!!
                    day_st = last_rec_day.replace(hour=0, minute=0, second=0)
                    day_end = last_rec_day.replace(hour=23, minute=59, second=59)
                else:
                    return jsonify([])
            else:
                if unixdate:
                    day_st = int(ts_from)
                    day_st = datetime.datetime.fromtimestamp(day_st).replace(hour=0, minute=0, second=0)
                    day_end = int(ts_to)
                    day_end = datetime.datetime.fromtimestamp(day_end).replace(hour=23, minute=59, second=59)

                else:
                    day_st = datetime.datetime.strptime(ts_from, '%d-%m-%Y %H:%M').replace(hour=0, minute=0, second=0)
                    day_end = datetime.datetime.strptime(ts_to, '%d-%m-%Y %H:%M').replace(hour=23, minute=59, second=59)
            
            sensordata_query = db.session.query(Data).filter(Data.sensor.has(Sensor.uuid.in_([s.uuid for s in sensor])))
            if puuid:
                sensordata_query = sensordata_query.join(Data.records).options(contains_eager(Data.records)).filter(ProbeData.probe.has(Probe.uuid==puuid))
            # HIDE PROBES            
            sensordata_query.filter(ProbeData.probe_id.notin_([362, 356]))
            sensordata_query = sensordata_query.order_by(Data.ts).filter(Data.ts >= day_st).filter(Data.ts <= day_end)
            
            app.logger.debug("GET DATA 2")
            app.logger.debug("GET DATA 3")
            
            query_count = get_count(sensordata_query)
            if query_count > 0:
                sensordata = sensordata_query
                if fill_date:
                    pass

                else:
                    app.logger.debug("GET DATA 4")
                    if full_data:
                        app.logger.debug("FULL DATA 4")
                        data = self.f_schema.dump(sensordata).data
                    else:
                        if query_count > 1000:
                            proportion = int(query_count/1000)
                            # Issue #84 pass all_cameras to show all photos
                            #all_cameras = [c.cameras for c in sensordata if c.cameras]
                            sensordata = list(islice(sensordata, 0, query_count, proportion))
                            app.logger.debug("SHORT DATA 4 RESAMPLE")
                            data = custom_serializer(sensordata)#, cameras=all_cameras)
                        else:
                            app.logger.debug("SHORT DATA 4")
                            data = custom_serializer(sensordata)
                            
                    app.logger.debug("GET DATA 5")

                    if dataonly:
                        data.pop('cameras', None)
                    
                    res = {"numrecords": query_count,
                           'mindate': first_rec_day,
                           'maxdate': last_rec_day,
                           'data': data
                    }
                    
                    if compact_data:
                        return orjson.dumps(res), 200
                    else:
                        return jsonify(res), 200
                    
        else:
            sensordata = db.session.query(Data).filter(Data.sensor.has(uuid=suuid)).filter(Data.id == dataid).first()
            if sensordata:
                return jsonify(self.schema.dump(sensordata).data), 200
            else:
                return(jsonify([]))
        return abort(404)

    @token_required
    @cross_origin()
    def post(self):
        """
        POST sensors data [TODO: Fix description]
        ---
        tags: [Sensors,]
        parameters:
         - in: body
           name: data
           description: Sensor data
           schema:
               $ref: '#/definitions/SensorPostData'
        definitions:
          SensorPostData:
            type: object
            description: SensorPostData
            properties:
              data:
                type: array
                description: Data records for the specified sensor
                items:
                  type: object
                  description: A single data record
                  properties:
                    id:
                      type: integer
                      description: Data ID
                    ts:
                      type: string
                      format: date-time
                      description: Data record timestamp
                    probes:
                      type: array
                      items:
                        type: object
                        description: Probe data
                        properties:
                         id:
                           type: integer
                           description: Probe ID
                         uuid:
                           type: string
                           description: Probe UUID
                         values:
                           type: array
                           description: A list of probe values
                           items:
                             type: object
                             description: Probe data value
                             properties:
                               id:
                                 type: integer
                                 description: Probe Data ID
                               value:
                                 type: number
                                 format: double
                                 description: Probe Data value
                               label:
                                 type: string
                                 description: Probe label
                               ptype:
                                 type: string
                                 description: Probe type
                    cameras:
                      type: array
                      items:
                        type: object
                        description: Camera data
                        properties:
                         id:
                           type: integer
                           description: Camera ID
                         camlabel:
                           type: string
                           description: Camera label
                         positions:
                           type: array
                           description: A list of camera positions
                           items:
                             type: object
                             description: Camera position
                             properties:
                               id:
                                 type: integer
                                 description: Camera Position ID
                               poslabel:
                                 type: string
                                 description: Camera Position Label
                               pictures:
                                 type: array
                                 items:
                                   type: object
                                   description: Picture
                                   properties:
                                     id:
                                       type: integer
                                       description: Picture ID
                                     fpath:
                                       type: string
                                       description: Picture URL
                                     thumbnail:
                                       type: string
                                       description: Picture thumbnail
                                     label:
                                       type: string
                                       description: Picture label
                                     original:
                                       type: string
                                       description: Picture Original URL
                                     results:
                                       type: string
                                       description: Picture recognition results
                                     ts:
                                       type: string
                                       format: date-time
                                       description: Picture timestamp
        responses:
          201:
            description: Sensor data created
            schema:
               $ref: '#/definitions/SensorData'
          401:
            description: Not authorized
          404:
            description: URL not found
        """

        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        request.get_json()
        suuid = request.json.get('uuid')
        sensor = db.session.query(Sensor).filter(Sensor.uuid == suuid).first()
        probes = request.json.get('probes')
        if sensor:
            if sensor.user != user:
                abort(403)
            ts = request.json.get("ts")
            app.logger.debug(['NEW DATA TS', ts])
            newdata = Data(sensor_id=sensor.id,
                           ts = ts
            )
            db.session.add(newdata)
            db.session.commit()
            for pr in probes:
                probe_uuid = pr['puuid']
                plabel = pr.get('plabel', None)
                
                probe = db.session.query(Probe).filter(Probe.uuid==probe_uuid).first()
                if not probe:
                    probe = Probe(sensor=sensor, uuid=pr['puuid'])#, data=newdata)
                    if plabel:
                        probe.label = plabel
                    db.session.add(probe)
                    db.session.commit()
                newdata.probes.append(probe)
                
                #probe.data.append(newdata)
                for pd in pr['data']:
                    prtype = db.session.query(SensorType).filter(SensorType.ptype==pd['ptype']).filter(SensorType.sensor==sensor).first()
                    if not prtype:
                        prtype = SensorType(ptype=pd['ptype'], sensor=sensor)
                        db.session.add(prtype)
                        db.session.commit()
                    
                    newprobedata = ProbeData(probe=probe, value=pd['value'], label=pd['label'], ptype=pd['ptype'])
                    # Now we're moving to the one-probe-per-datarecord model
                    # these coords would be coming from the linked probe
                    # it's intended to track coords changes
                    
                    #app.logger.debug(['PROBEDATA', ts, probe_uuid, [probe.x, probe.y, probe.z]])
                    
                    if all([True if c is not None else False for c in [probe.x, probe.y, probe.z]]):
                        newprobedata.x = float(probe.x)
                        newprobedata.y = float(probe.y)
                        newprobedata.z = float(probe.z)
                    if all([probe.row, probe.col]):
                        newprobedata.row = probe.row
                        newprobedata.col = probe.col
                    if probe.label:
                        newprobedata.plabel = probe.label
                    if prtype:
                        newprobedata.prtype = prtype
                        
                    if probe.sensor.limits:
                        app.logger.debug(["Checking sensor limits for", probe.sensor.uuid, probe.sensor.user.login])
                        for l in probe.sensor.limits:
                            if l.prtype.ptype == pd['ptype']:
                                # If both limits exists
                                if l.minvalue and l.maxvalue:
                                    if not l.minvalue < pd['value'] < l.maxvalue:
                                        #app.logger.debug(["Current value is out of limits, sending notification", pd['ptype'], pd['label'], pd['value'], "limits", l.minvalue, l.maxvalue])
                                        prev_three_values = db.session.query(ProbeData).join(Probe).join(Sensor).order_by(ProbeData.id.desc()).filter(ProbeData.ptype==pd['ptype']).filter(ProbeData.label==pd['label']).filter(Probe.uuid==probe_uuid).filter(Sensor.uuid==sensor.uuid).limit(3).offset(1)
                                    
                                        if not all([l.minvalue < v.value < l.maxvalue for v in prev_three_values]):
                                            #app.logger.debug("Prev values are out of limits")
                                        
                                            pd['ts'] = newdata.ts.strftime("%d-%m-%Y %H:%M:%S")
                                            pd['uuid'] = pr['puuid']
                                            pd['location'] = probe.sensor.location.address
                                            pd['coords'] = "x:{} y:{} z:{}".format(probe.x, probe.y, probe.z)
                                            pd['localcoords'] = "row: {} column: {}".format(probe.row, probe.col)
                                            pd['min'] = l.minvalue
                                            pd['max'] = l.maxvalue
                                            pd['suuid'] = probe.sensor.uuid
                                            app.logger.debug(["CREATE_NOTIFIACTION", pd])
                                            newnotification = Notification(user=sensor.user, text=json.dumps(pd), ntype='sensors')
                                            db.session.add(newnotification)
                                            db.session.commit()

                    db.session.add(newprobedata)
                    db.session.commit()
                    newdata.records.append(newprobedata)
                    db.session.add(newdata)
                    db.session.commit()
        
            app.logger.debug(["New data saved", newdata.id])

        return jsonify(self.schema.dump(newdata).data), 201

    @token_required
    @cross_origin()
    def delete(self, id=None):
        """
        DELETE All data
        """
        app.logger.debug(["Delete"])
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        for s in user.sensors:
            for p in s.probes:
                for d in p.data:
                    #app.logger.debug(["Deleting data", p.data])
                    db.session.delete(d)
        db.session.commit()
        app.logger.debug("Deleted data")
        return ('', 204)

    
    @token_required
    @cross_origin()
    def patch(self, id=None):
        """
        PATCH sensors data [TODO: Fix description]
        ---
        tags: [Sensors,]
        parameters:
         - in: body
           name: data
           description: Sensor data
           schema:
               $ref: '#/definitions/SensorPatchData'
        definitions:
          SensorPatchData:
            type: object
            description: SensorPatchData
            properties:
              data:
                type: array
                description: Data records for the specified sensor
                items:
                  type: object
                  description: A single data record
                  properties:
                    id:
                      type: integer
                      description: Data ID
                    ts:
                      type: string
                      format: date-time
                      description: Data record timestamp
                    probes:
                      type: array
                      items:
                        type: object
                        description: Probe data
                        properties:
                         id:
                           type: integer
                           description: Probe ID
                         uuid:
                           type: string
                           description: Probe UUID
                         values:
                           type: array
                           description: A list of probe values
                           items:
                             type: object
                             description: Probe data value
                             properties:
                               id:
                                 type: integer
                                 description: Probe Data ID
                               value:
                                 type: number
                                 format: double
                                 description: Probe Data value
                               label:
                                 type: string
                                 description: Probe label
                               ptype:
                                 type: string
                                 description: Probe type
                    cameras:
                      type: array
                      items:
                        type: object
                        description: Camera data
                        properties:
                         id:
                           type: integer
                           description: Camera ID
                         camlabel:
                           type: string
                           description: Camera label
                         positions:
                           type: array
                           description: A list of camera positions
                           items:
                             type: object
                             description: Camera position
                             properties:
                               id:
                                 type: integer
                                 description: Camera Position ID
                               poslabel:
                                 type: string
                                 description: Camera Position Label
                               pictures:
                                 type: array
                                 items:
                                   type: object
                                   description: Picture
                                   properties:
                                     id:
                                       type: integer
                                       description: Picture ID
                                     fpath:
                                       type: string
                                       description: Picture URL
                                     thumbnail:
                                       type: string
                                       description: Picture thumbnail
                                     label:
                                       type: string
                                       description: Picture label
                                     original:
                                       type: string
                                       description: Picture Original URL
                                     results:
                                       type: string
                                       description: Picture recognition results
                                     ts:
                                       type: string
                                       format: date-time
                                       description: Picture timestamp
        responses:
          201:
            description: Sensor data created
            schema:
               $ref: '#/definitions/SensorData'
          401:
            description: Not authorized
          404:
            description: URL not found
        """

        app.logger.debug("Patch Data")

        if not id:
            abort(400)


        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        # If there's no registered CAMNAME & CAMPOSITION for a given data.uuid
        # add new camera & position
        # >>>
        app.logger.debug(["Request Data", request.values, "LENGTH", [request.files.get(f).content_length for f in request.files], request.json])
        
        camname = request.form.get("camname")
        camposition = request.form.get("camposition")
        photo_ts = request.form.get("photo_ts", None)
        flabel = request.form.get("flabel")
        # TODO Ad a per-user classificator API here
        recognize = request.form.get("recognize", False)
        camera_position = None
        app.logger.debug(["CAMERA DB:", camname, camposition, recognize])
        if not user:
            abort(403)
            
        db.session.commit()

        data = db.session.query(Data).filter(Data.id == id).first()
        if data:
            sensor = data.sensor
            if sensor.user != user:
                abort(403)
            # Surely there's no camera for data.id. We should replace data.id with a sensor id.
            camlocation = db.session.query(CameraLocation).filter(CameraLocation.camlabel==camname).filter(CameraLocation.location==sensor.location).first()
            camera = db.session.query(Camera).join(Data).filter(Data.id == data.id).filter(Camera.camlabel == camname).first()
            if not camera:
                camera = Camera(data=data, camlabel=camname)
                
                if camlocation:
                    camera.x = camlocation.posx
                    camera.y = camlocation.posy
                    camera.z = camlocation.posz
                    camera.row = camlocation.row
                    camera.col = camlocation.col
                db.session.add(camera)
                db.session.commit()

            camera_position = db.session.query(CameraPosition).join(Camera).filter(Camera.id == camera.id).filter(CameraPosition.poslabel == camposition).first()
            if not camera_position:
                camera_position = CameraPosition(camera=camera, poslabel=camposition)
                db.session.add(camera_position)
                db.session.commit()

            app.logger.debug(["DB CAMERA", camera.camlabel, camera_position.poslabel, camera.x, camera.y, camera.z])
            # data.cameras.append(camera)
            app.logger.debug(["RECOGNIZE", recognize])
            # To be sure to consume request data
            # to aviod "uwsgi-body-read Error reading Connection reset by peer" errors
            request_data = request.data
            app.logger.debug(["Consuming request data", len(request_data)])
            #if data.lux < 30:
            #highlight = [d.value > 30 for d in data.records if d.ptype == 'light']
            
            tmpfname = str(uuid.uuid4())
            tmpf = open(tmpfname, 'w+b')
            fl = [request.files.get(f) for f in request.files][0]
            tmpf.write(fl.read())
            tmpf.seek(0)
            tmpf.close()
            request_image_size = os.stat(tmpfname).st_size
            
            if request_image_size == 0:
                app.logger.debug(["ZERO PICT FILESIZE", request_image_size])
                os.unlink(tmpfname)
                return "Missing image", 400
            
            db.session.add(data)
            db.session.commit()
            
            
            highlight = True
            pict_recognize = False
            
            
            #numcolors = check_colors(tmpf)
            #if numcolors < COLOR_THRESHOLD:
            #    highlight = False
            #tmpf.seek(0)
            # Running parse_request_pictures in the background
            if recognize and highlight:
                pict_recognize = True
                
            # Running as celery task
            parse_request_pictures.delay(data.id, camera_position.id, tmpf.name, flabel, photo_ts, user.login, sensor.uuid, pict_recognize)
            return "Data added", 200
        abort(404)


class SensorAPI(Resource):
    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.schema = SensorSchema()
        self.m_schema = SensorSchema(many=True)

    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self, id=None):
        """
        Get sensors
        ---
        tags: [Sensors,]
        parameters:
         - in: path
           name: id
           type: integer
           required: false
           description: Sensor ID
        definitions:
          SensorObject:
            type: object
            description: Sensor object data
            properties:
              id:
                type: integer
                description: Sensor ID
              location:
                type: integer
                description: Sensor Location ID
              maxdate:
                type: string
                format: date-time
                description: The latest record date
              mindate:
                type: string
                format: date-time
                description: The earliest record date
              numrecords:
                type: integer
                description: Number of records for a particular sensor
              registered:
                type: string
                format: date-time
                description: Sensor registration timestamp
              user:
                type: integer
                description: Sensor related User ID
              uuid:
                type: string
                description: Sensor uuid
              data:
                type: array
                items:
                  type: integer
                  description: Sensor related SensorData ID
        responses:
          200:
            description: Sensor object data
            schema:
               $ref: '#/definitions/SensorObject'
          401:
            description: Not authorized
          404:
            description: URL not found

        """
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=data['sub']).first()
        if not user:
            abort(404)
        if not id:
            sensors = user.sensors
            return jsonify(self.m_schema.dump(sensors).data), 200
        abort(404)

    @token_required
    @cross_origin()
    def post(self):
        """
        Create Sensor Object
        ---
        tags: [Sensors,]
        parameters:
         - in: body
           name: data
           type: object
           required: true
           description: Sensor Post Data
           schema:
              $ref: '#/definitions/SensorPostObject'
        definitions:
          SensorPostObject:
            type: object
            description: Sensor object data
            properties:
              lat:
                type: number
                format: float
                description: Sensor Location Latitude
              lon:
                type: number
                format: float
                description: Sensor Location Longitude
              address:
                type: integer
                description: Sensor Location ID
        responses:
          201:
            description: New Sensor created
            schema:
               $ref: '#/definitions/SensorPostObject'
          401:
            description: Not authorized
          404:
            description: URL not found

        """

        print("REQUEST", request.json)
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()

        lat = request.json.get('lat')
        lon = request.json.get('lon')
        address = request.json.get('address')
        location = db.session.query(Location).filter(Location.lat == lat).filter(Location.lon == lon).filter(Location.address == address).first()
        if not location:
            location = Location(lat=lat, lon=lon, address=address)
            db.session.add(location)
            db.session.commit()


        newsensor = Sensor(location=location, user=user)
        newuuid = str(uuid.uuid4())
        newsensor.uuid=newuuid
        db.session.add(newsensor)
        db.session.commit()

        return jsonify(self.schema.dump(newsensor).data), 201

    @token_required
    @cross_origin()
    def patch(self, id):
        print("REQUEST", request.remote_addr)

        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        if not user:
            abort(403)

        return jsonify("OK {}".format(datetime.datetime.now()))

    @token_required
    @cross_origin()
    def delete(self, id):
        """
        Delete Sensor Object
        ---
        tags: [Sensors,]
        parameters:
         - in: path
           name: id
           type: integer
           required: true
           description: Sensor ID
        responses:
          204:
            description: Sensor deleted
          401:
            description: Not authorized
          404:
            description: URL not found

        """
        print("REQUEST", request.remote_addr)
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        return jsonify("OK {}".format(datetime.datetime.now()))



class UserAPI(Resource):
    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.schema = UserSchema(exclude=['password_hash',])
        self.m_schema = UserSchema(many=True, exclude=['password_hash',])
        self.method_decorators = []


    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    @cache.cached(timeout=300, key_prefix=cache_key)
    def get(self, id=None):
        """
        Get users
        ---
        tags: [Authentication,]
        parameters:
         - in: path
           name: id
           type: integer
           required: false
           description: User ID
        definitions:
          UserObject:
            type: object
            description: User object
            properties:
              id:
                type: integer
                description: User ID
              is_confirmed:
                type: boolean
                description: Confirmed user
              is_admin:
                type: boolean
                description: Admin user
              confirmed_on:
                type: string
                format: date-time
                description: User confirmation date
              registered_on:
                type: string
                format: date-time
                description: User registration date
              login:
                type: string
                description: User login
              name:
                type: string
                description: User name
              note:
                type: string
                description: User notes
              phone:
                type: string
                description: User's phone
              sensors:
                type: array
                items:
                  type: integer
                  description: User related Sensor IDs
        responses:
          200:
            description: User object data
            schema:
               $ref: '#/definitions/UserObject'
          401:
            description: Not authorized
          404:
            description: URL not found
        """

        if not id:
            users = db.session.query(User).all()
            return jsonify(self.m_schema.dump(users).data)
        else:
            user = User.query.filter_by(id=id).first()
            if user:
                return jsonify(self.schema.dump(user).data), 200
            else:
                abort(404)

    @token_required
    @cross_origin()
    def patch(self, id):
        """
        Patch users
        ---
        tags: [Authentication,]
        parameters:
         - in: path
           name: id
           type: integer
           required: true
           description: User ID
         - in: body
           name: data
           type: object
           schema:
              $ref: '#/definitions/UserObject'
        definitions:
          UserObject:
            type: object
            description: User object
            properties:
              id:
                type: integer
                description: User ID
              is_confirmed:
                type: boolean
                description: Confirmed user
              is_admin:
                type: boolean
                description: Admin user
              confirmed_on:
                type: string
                format: date-time
                description: User confirmation date
              registered_on:
                type: string
                format: date-time
                description: User registration date
              login:
                type: string
                description: User login
              name:
                type: string
                description: User name
              note:
                type: string
                description: User notes
              phone:
                type: string
                description: User's phone
              sensors:
                type: array
                items:
                  type: integer
                  description: User related Sensor IDs
        responses:
          200:
            description: User updated
            schema:
               $ref: '#/definitions/UserObject'
          401:
            description: Not authorized
          404:
            description: URL not found
        """

        if not request.json:
            abort(400, message="No data provided")

        user = db.session.query(User).filter(User.id==id).first()
        if user:
            for attr in ['login', 'phone', 'name', 'note', 'is_confirmed', 'confirmed_on', 'password']:
                val = request.json.get(attr)
                if attr == 'password' and val:
                    user.hash_password(val)

                elif attr == 'confirmed_on':
                    val = datetime.datetime.now()


                if val:
                    setattr(user, attr, val)

            db.session.add(user)
            db.session.commit()
            return jsonify(self.schema.dump(user).data), 201

        abort(404, message="Not found")

    @token_required
    @cross_origin()
    def post(self):
        """
        Post users
        ---
        tags: [Authentication,]
        parameters:
         - in: path
           name: id
           type: integer
           required: true
           description: User ID
         - in: body
           name: data
           type: object
           schema:
              $ref: '#/definitions/UserPostObject'
        definitions:
          UserPostObject:
            type: object
            description: User object
            properties:
              login:
                type: string
                description: User login
              name:
                type: string
                description: User name
              password:
                type: string
                description: User's password
              phone:
                type: string
                description: User's phone
        responses:
          201:
            description: User created
            schema:
               $ref: '#/definitions/UserObject'
          401:
            description: Not authorized
          404:
            description: URL not found
        """

        if not request.json:
            abort(400, message="No data provided")
        login = request.json.get('login')
        phone = request.json.get('phone')
        name = request.json.get('name')
        password = request.json.get('password')

        if not(any([login, phone, name])):
            return abort(400, 'Provide required fields for phone, name or login')

        prevuser = db.session.query(User).filter(User.login==login).first()
        if prevuser:
            abort(409, message='User exists')
        note = request.json.get('note')

        is_confirmed = request.json.get('is_confirmed')
        confirmed_on = None
        if is_confirmed:
            confirmed_on = datetime.datetime.today()

        newuser = User(login=login, is_confirmed=is_confirmed, confirmed_on=confirmed_on, phone=phone, name=name, note=note)

        newuser.hash_password(password)
        db.session.add(newuser)
        db.session.commit()

        return jsonify(self.schema.dump(newuser).data), 201

    def delete(self, id):
        """
        Delete User
        ---
        tags: [Authentication,]
        parameters:
         - in: path
           name: id
           type: integer
           required: true
           description: User ID
        responses:
          204:
            description: User deleted
          401:
            description: Not authorized
          404:
            description: URL not found

        """

        if not id:
            abort(404, message="Not found")
        user = db.session.query(User).filter(User.id==id).first()
        if user:
            db.session.delete(user)
            db.session.commit()
            return make_response("User deleted", 204)
        abort(404, message="Not found")


api.add_resource(UserAPI, '/users', '/users/<int:id>', endpoint='users')
api.add_resource(ImagesAPI, '/images', endpoint='images')
api.add_resource(CameraAPI, '/cameras/<int:id>', endpoint='cameras')
api.add_resource(DataAPI, '/data', '/data/<int:id>', endpoint='savedata')
api.add_resource(SensorAPI, '/sensors', '/sensors/<int:id>', endpoint='sensors')
api.add_resource(SensorsStatsAPI, '/stats', endpoint='stats')
api.add_resource(SensorLimitsAPI, '/sensorlimits',  endpoint='sensorlimits')
api.add_resource(SensorTypeAPI, '/sensortypes',  endpoint='sensortypes')                       
api.add_resource(LocationWarningsAPI, '/locationwarnings', endpoint='locationwarnings')
api.add_resource(ProbeAPI, '/probes', '/probes/<int:id>', endpoint='probes')
api.add_resource(ProbeDataAPI, '/probedata', '/probedata/<int:id>', endpoint='probedata')
api.add_resource(PictAPI, "/p/<path:path>", endpoint="picts")

@app.cli.command()
@click.option('--login',  help='user@mail.com')
@click.option('--password',  help='password')
@click.option('--name',  help='name')
@click.option('--phone',  help='phone')
def adduser(login, password, name, phone):
    """ Create new user"""
    newuser = User(login=login, name=name, phone=phone)
    newuser.hash_password(password)
    newuser.is_confirmed = True
    newuser.confirmed_on = datetime.datetime.today()
    db.session.add(newuser)
    db.session.commit()
    print("New user added", newuser)

@app.cli.command()
def fix_path():
    data = db.session.query(Data).all()
    for d in data:
        if d.fpath is not None:
            nimage = DataPicture(fpath=d.fpath, data_id=d.id)
            db.session.add(nimage)
            db.session.commit()


if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0')
