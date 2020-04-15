#!/usr/bin/env python
# -*- coding: utf-8 -*-

from functools import wraps
from flask import Flask, g, make_response, request, current_app, send_file, url_for
from flask_restful import Resource, Api, reqparse, abort, marshal_with
from flask.json import jsonify
from flasgger import Swagger
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, desc, and_
from sqlalchemy.orm import contains_eager
from sqlalchemy import func as sql_func
from sqlalchemy.pool import NullPool
from flask_marshmallow import Marshmallow
from flask_httpauth import HTTPBasicAuth
from flask_cors import CORS, cross_origin
from flask_restful.utils import cors
from marshmallow import fields, pre_dump, post_dump
from marshmallow_enum import EnumField
from itertools import groupby
from models import db, User, Sensor, Location, Data, DataPicture, Camera, CameraPosition, Probe, ProbeData, PictureZone, SensorType, data_probes, Notification
import logging
import os
import copy
import uuid
import tempfile
import shutil
import zipfile
import urllib.parse

# for emails
import smtplib
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from celery import Celery
from celery.schedules import crontab

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



#from multiprocessing import Pool
import multiprocessing.pool.ThreadPool as Pool

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

HOST = app.config.get('HOST', 'localhost')
REDIS_HOST = app.config.get('REDIS_HOST', 'localhost')
REDIS_PORT = app.config.get('REDIS_PORT', 6379)
REDIS_DB = app.config.get('REDIS_DB', 0)
CACHE_DB = app.config.get('CACHE_DB', 1)

BASEDIR = app.config.get('FILE_PATH')
MAILUSER = app.config.get('MAILUSER')
MAILPASS = app.config.get('MAILPASS')

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
CF_HOST = app.config['CF_HOST']
CF_TOKEN = None
FONT = app.config['FONT']
FONTSIZE = app.config['FONTSIZE']

zonefont = ImageFont.truetype(FONT, size=FONTSIZE)

CLASSIFY_ZONES = app.config['CLASSIFY_ZONES']
SEND_EMAILS = app.config.get('SEND_EMAILS', False)

app.config['CELERY_BROKER_URL'] = 'redis://{}:{}/{}'.format(REDIS_HOST, REDIS_PORT, REDIS_DB)
app.config['CELERY_RESULT_BACKEND'] = 'redis://{}:{}/{}'.format(REDIS_HOST, REDIS_PORT, REDIS_DB)

TMPDIR = app.config['TEMPDIR']


if CLASSIFY_ZONES:
    with open("cropsettings.yaml", 'r') as stream:
        try:
            CROP_SETTINGS = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            app.logger.debug(exc)


class SQLAlchemyNoPool(SQLAlchemy):
    def apply_driver_hacks(self, app, info, options):
        options.update({
            'poolclass': NullPool
        })
        super(SQLAlchemy, self).apply_driver_hacks(app, info, options)


def send_zones(zone, zonelabel, fuuid, file_format, fpath, user_login, sensor_uuid, cf_headers, original):
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
    #original.save(fullpath)
    #response = requests.post(CF_HOST.format("loadimage"), headers=cf_headers, files = {'croppedfile': img_io}, data={'index':0, 'filename': ''})
    response = requests.post(CF_HOST.format("loadimage"), auth=(CF_LOGIN, CF_PASSWORD), files = {'imagefile': img_io}, data={'index':0, 'filename': fuuid})
    if response.status_code == 200:
        cf_result = response.json().get('objtype')

        ## >>> New logic, with subzones.
        subzones = get_zones(cropped, 2, 2)
        sz_results = []
        for sz in subzones.keys():
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

        else:
            precise_results = [(res, sz_results.count(res)) for res in set(sz_results)]
            precise_results = sorted(precise_results, key=lambda x: x[1], reverse=True)
            precise_res = precise_results[0][0]

        ## >>> New logic, with subzones.


        #is_truly_unhealthy = False

        #if 'unhealthy' in cf_result:
        #    app.logger.debug("CHECKING SUBZONES")
        #    subzones = get_zones(cropped, 2, 2)
        #    sz_argslist = []
        #    sz_results = []
        #    # Todo: parallelize
        #    # aiohttp?
        #    for sz in subzones.keys():
        #        sz_res = send_subzones(subzones[sz], sz, file_format, cropped)
        #        sz_results.append(sz_res)
        #    #sz_pool = Pool(processes=2)
        #    #sz_results = p.starmap(send_subzones, sz_argslist)
        #    #sz_pool.close()
        #    app.logger.debug(f"CF SUBZONE RESULTS {sz_results}, ZONE {cf_result}")
        #    sz_results = set(sz_results)
        #    sz_results = {elem for elem in sz_results if not 'rassada' in elem}
        #    sz_results = {elem for elem in sz_results if not 'infrastructure' in elem}
        #
        #    res_plant_type = cf_result.split('_')[0]
        #
        #    newzone.revisedresults = ",".join(sz_results)
        #    #if cf_result in [sz_res for sz_res in sz_results]:
        #    if all([res_plant_type in sz_res for sz_res in sz_results]) and any(['unhealthy' in sz_res for sz_res in sz_results]):
        #        is_truly_unhealthy = True

        newzone.origresults = cf_result

        #if not is_truly_unhealthy:
        #    cf_result = cf_result.replace("_unhealthy", "_healthy_rev")
        ## >>> New logic, with subzones.


        newzone.results = precise_res

        #if is_truly_unhealthy:
        #    newzone.revisedresults = "unhealthy"
        #else:
        #    newzone.revisedresults = "healthy"

        app.logger.debug(f"CF RESULTS {cf_result}")

    db.session.add(newzone)
    db.session.commit()
    #db.session.close()
    #if newzone.revisedresults == unhealthy:
    return newzone.id


def send_subzones(zone, zonelabel, file_format, pict):
    cf_result = False
    cropped = pict.crop((zone['left'], zone['top'], zone['right'], zone['bottom']))
    img_io = io.BytesIO()
    cropped.save(img_io, file_format, quality=100)
    img_io.seek(0)
    response = requests.post(CF_HOST.format("loadimage"), auth=(CF_LOGIN, CF_PASSWORD), files = {'imagefile': img_io}, data={'index':0, 'filename': "filename"})
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
        crontab(minute=0, hour='*/1'),
        #crontab(),
        check_pending_notifications.s(),
    )


@celery.task
def check_pending_notifications():
    with app.app_context():
        print("Checking pending notifications")
        dbusers = db.session.query(User).filter(User.additional_email != None).filter(User.notifications.any(Notification.sent.is_(False))).all()
        if dbusers:
            for dbuser in dbusers:
                notifications = []
                for n in dbuser.notifications:
                    if not n.sent:
                        notifications.append(n.text)
                        n.sent = True
                        db.session.add(n)
                        db.session.commit()
                app.logger.debug(f"Sending user notifications {dbuser.additional_email}")
                # TODO Check email status before setting notification status to "Sent"
                send_email_notification.delay(dbuser.additional_email, notifications)



@celery.task
def send_email_notification(email, pict_status_list):
    print("Sending email")

    sender = MAILUSER#"noreply@plantdata.fermata.tech"
    msg = MIMEMultipart('related')
    msg['Subject'] = 'Plantdata Service Notification'
    msg['From'] = sender
    msg['To'] = email

    # form message body here

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

    print("mail ready to be sent")
    s = smtplib.SMTP('smtp.yandex.ru', 587)
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

def parse_request_pictures(parent_data, camposition_id, req_files, flabel, camname, user_login, sensor_uuid, recognize):
    with app.app_context():
        data = db.session.query(Data).filter(Data.id == parent_data).first()
        if not data:
            abort(404)

        camposition = db.session.query(CameraPosition).filter(CameraPosition.id == camposition_id).first()
        if not camposition:
            abort(404)

        picts = []
        picts_unhealthy_status = []
        app.logger.debug("PARSING REQUEST PICTURES")
        #for uplname in sorted(req_files):
        pict = req_files[0]#s.get(uplname)
        fpath = os.path.join(current_app.config['FILE_PATH'], user_login, sensor_uuid)
        app.logger.debug(fpath)
        if not os.path.exists(fpath):
            os.makedirs(fpath)
        fdata = pict.read()
        original = Image.open(io.BytesIO(fdata))
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

        original.save(origpath)

        imglabel = flabel
        app.logger.debug(["UPLNAME", flabel])
        classification_results = ""
        app.logger.debug("FILE SAVED")
        newzones = []

        if recognize:
            if CLASSIFY_ZONES:# and CF_TOKEN:
                # zones = CROP_SETTINGS.get(uplname, None)
                zones = get_zones(original, 3, 4)
                cf_headers = None #= {'Authorization': 'Bearer ' + CF_TOKEN}
                # 2592x1944
                app.logger.debug(["ZONES", zones])
                if zones:
                    responses = []
                    newzones = []
                    argslist = []
                    dr = ImageDraw.Draw(original)
                    for z in zones.keys():
                        argslist.append([zones[z], z, fuuid, FORMAT, fpath, user_login, sensor_uuid, cf_headers, original])
                        dr.rectangle((zones[z]['left'], zones[z]['top'], zones[z]['right'], zones[z]['bottom']), outline = '#fbb040', width=3)
                        dr.text((zones[z]['left']+2, zones[z]['top']+2), z, font=zonefont)

                    # Paralleled requests
                    # now using threads
                    p = Pool(4)
                    zones_ids = p.starmap(send_zones, argslist)
                    p.close()
                    app.logger.debug(["SAVED ZONES", [zones_ids]])
                    db.session.commit()

                    if zones_ids:
                        newzones = db.session.query(PictureZone).filter(PictureZone.id.in_(zones_ids)).all()
                        app.logger.debug(["NEWZONES", [(n.id, n.results) for n in newzones]])
                        # Draw a red rectangle around the unhealthy zone
                        for nzone in newzones:
                            if "unhealthy" in nzone.results:
                                # split zone into 4 subzones & check it again.
                                # if any subzone is reported as unhealthy,
                                # the zone result is confirmed

                                dr.rectangle((zones[nzone.zone]['left'], zones[nzone.zone]['top'], zones[nzone.zone]['right'], zones[nzone.zone]['bottom']), outline = '#ff0000', width=10)
                        class_results = ["{}: {}".format(z.zone, process_result(z.results)) for z in sorted(newzones, key=lambda x: int(x.zone[4:]))]
                        classification_results = "Results: {}".format(", ".join(class_results))
                    else:
                        app.logger.debug(["NO ZONES", newzones])
                        newzones = None
                        classification_results = ""
                original.save(fullpath)
                app.logger.debug(["IMGLABEL", imglabel, classification_results])
                imglabel = imglabel + " " + classification_results
        # Thumbnails
        original.thumbnail((300, 300), Image.ANTIALIAS)
        original.save(thumbpath, FORMAT, quality=90)
        app.logger.debug(["CAMERA TO PICT", camposition.camera.camlabel, camposition.poslabel, imglabel])
        newpicture = DataPicture(fpath=partpath,
                                 label=imglabel,
                                 thumbnail=partthumbpath,
                                 original=partorigpath,
                                 results=classification_results,
        )
        if newzones:
            newpicture.zones = newzones
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
                            # email_text = create_email_text(p)
                            # Now we only add a pending notification to be send
                            app.logger.debug(["CREATING NOTIFICATION", p])
                            p['ts'] = p['ts'].strftime("%d-%m-%Y %H:%M:%S")
                            newnotification = Notification(user=sensor.user, text=json.dumps(p))
                            db.session.add(newnotification)
                            db.session.commit()
        db.session.close()

    #return picts


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
            response = jsonify({ 'token': "%s" % token.decode('utf-8'), "user_id":user.id, "login": user.login, "name": user.name })
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


class CameraPositionSchema(ma.ModelSchema):
    class Meta:
        model = CameraPosition
    pictures = ma.Nested("DataPictureSchema", many=True, exclude=["camera_position", "data", "thumbnail"])#, many=False, exclude=['thumbnail', 'camera', 'camera_position', 'data'])
    #image = ma.Function(lambda obj: obj.image)

class SensorSchema(ma.ModelSchema):
    class Meta:
        model = Sensor
    numrecords = ma.Function(lambda obj: obj.numrecords)
    mindate = ma.Function(lambda obj: obj.mindate)
    maxdate = ma.Function(lambda obj: obj.maxdate)


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


class PictAPI(Resource):
    def __init__(self):
        self.schema = DataPictureSchema()
        self.m_schema = DataPictureSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    #@token_required
    @cross_origin()
    #@cache.cached(timeout=300, key_prefix=cache_key)
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
    #@cache.cached(timeout=300, key_prefix=cache_key)
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

        camera = db.session.query(Camera).filter(Camera.id==id).first()
        if camera:
            return jsonify(self.schema.dump(camera).data), 200
        return abort(404)


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
    #@cache.cached(timeout=300, key_prefix=cache_key)
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
        app.logger.debug(["SENSOR", suuid, sensor])
        if sensor:
            if sensor.user != user:
                abort(403)
        if puuid:
            probe = db.session.query(Probe).join(Sensor).filter(Probe.uuid == puuid).filter(Sensor.uuid == suuid).first()
            if probe:
                return jsonify(self.schema.dump(probe).data), 200
        elif suuid:
            probes = db.session.query(Probe).join(Sensor).filter(Sensor.uuid == suuid).all()
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

        if sensor:
            if sensor.user != user:
                abort(403)

        probe = db.session.query(Probe).filter(Probe.uuid == puuid).first()
        if not probe:
            newprobe = Probe(sensor=sensor, uuid=puuid, data=datarecord)
            db.session.add(newprobe)
            db.session.commit()
            return jsonify(self.schema.dump(newprobe).data), 201
        else:
            return jsonify(self.schema.dump(probe).data), 409
        abort(404)



class ProbeDataAPI(Resource):
    def __init__(self):
        self.schema = ProbeDataSchema()
        self.m_schema = ProbeDataSchema(many=True)
        self.method_decorators = []

    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    #@cache.cached(timeout=300, key_prefix=cache_key)
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
    #@cache.cached(timeout=60, key_prefix=cache_key)
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
        # here the data should be scaled or not
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

        cam_skipsamples = request.args.get('cam_skipsamples', False)
        data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        daystart = dayend = None
        # By default show data for the last recorded day
        #
        user = User.query.filter_by(login=data['sub']).first()
        sensor = db.session.query(Sensor).filter(Sensor.uuid == suuid).first()
        if user != sensor.user:
            abort(403)
        if not user:
            abort(401)
        if not suuid:
            return make_response(jsonify({'error': 'No sensor uuid provided'}), 400)
            abort(404)
        #if not puuid:
        #    return make_response(jsonify({'error': 'No probe uuid provided'}), 400)

        if not dataid:
            first_rec_day = db.session.query(sql_func.min(Data.ts)).filter(Data.sensor.has(Sensor.uuid == suuid)).first()[0]
            last_rec_day = db.session.query(sql_func.max(Data.ts)).filter(Data.sensor.has(Sensor.uuid == suuid)).first()[0]
            if not all([ts_from, ts_to]):
                if all([first_rec_day, last_rec_day]):
                    # IF NO DATES SPECIFIED,
                    # SHOW ONLY LAST DAY RECORDS!!

                    day_st = last_rec_day.replace(hour=0, minute=0)
                    day_end = last_rec_day.replace(hour=23, minute=59, second=59)
                else:
                    return jsonify([])
            else:
                day_st = datetime.datetime.strptime(ts_from, '%d-%m-%Y %H:%M')
                day_end = datetime.datetime.strptime(ts_to, '%d-%m-%Y %H:%M')

            sensordata_query = db.session.query(Data).filter(Data.sensor.has(Sensor.uuid == suuid))
            if puuid:
                sensordata_query = sensordata_query.join(Data.records).options(contains_eager(Data.records)).filter(ProbeData.probe.has(Probe.uuid==puuid))

            #app.logger.debug(["DATES", day_st, day_end])
            #app.logger.debug(["DATES", first_rec_day, last_rec_day])
            sensordata_query = sensordata_query.order_by(Data.ts).filter(Data.ts >= day_st).filter(Data.ts <= day_end)

            sensordata = sensordata_query.all()

            if sensordata:
                if fill_date:
                    pass
                #if fill_date:
                #    sensordata = self.fill_empty_dates(sensordata_query)
                #if export_data:
                #    app.logger.debug(f"EXPORT DATA, {export_data}")
                #    proxy = io.StringIO()
                #    writer = csv.writer(proxy, delimiter=';', quotechar='"',quoting=csv.QUOTE_MINIMAL)
                #    writer.writerow(['sensor_id',
                #                     'timestamp',
                #                     'wght0',
                #                     'wght1',
                #                     'wght2',
                #                     'wght3',
                #                     'wght4',
                #                     'temp0',
                #                     'temp1',
                #                     'hum0',
                #                     'hum1',
                #                     'tempA0',
                #                     'lux',
                #                     'co2'
                #    ])
                #    for r in sensordata:
                #        writer.writerow([r.sensor.id,
                #                         r.ts,
                #                         r.wght0,
                #                         r.wght1,
                #                         r.wght2,
                #                         r.wght3,
                #                         r.wght4,
                #                         r.temp0,
                #                         r.temp1,
                #                         r.hum0,
                #                         r.hum1,
                #                         r.tempA,
                #                         r.lux,
                #                         r.co2
                #        ])
                #    mem = io.BytesIO()
                #    mem.write(proxy.getvalue().encode('utf-8'))
                #    mem.seek(0)
                #    proxy.close()
                #    return send_file(mem, mimetype='text/csv', attachment_filename="file.csv", as_attachment=True)
                #if export_zones:
                #    app.logger.debug(f"EXPORT ZONES, {export_zones}")
                #    if ignore_night_photos:
                #        sensordata_query = sensordata_query.filter(Data.lux > 30)
                #
                #    res_data = sensordata_query.filter(Data.pictures.any()).all()
                #    app.logger.debug(len(res_data))
                #    crop_zones.delay(self.f_schema.dump(res_data).data, cam_names, cam_positions, cam_zones, cam_numsamples, cam_skipsamples, label_text)
                #
                #    res = {"numrecords": len(res_data),
                #           'mindate': first_rec_day,
                #           'maxdate': last_rec_day,
                #           'data': self.m_schema.dump(res_data).data
                #    }
                #    return jsonify(res), 200

                else:
                    if full_data:
                        data = self.f_schema.dump(sensordata).data
                    else:
                        data = self.m_schema.dump(sensordata).data
                    #if puuid:
                    #    for d in data:
                    #        for ind, pr in enumerate(d['probes']):
                    #            if pr['uuid'] != puuid:
                    #                d['probes'].pop(ind)

                    res = {"numrecords": len(sensordata),
                           'mindate': first_rec_day,
                           'maxdate': last_rec_day,
                           'data': data
                    }
                    # app.logger.debug(["RESPONSE", res])
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
            ts = request.form.get("ts")
            newdata = Data(sensor_id=sensor.id,
                           ts = ts
            )
            db.session.add(newdata)
            db.session.commit()
            for pr in probes:
                probe_uuid = pr['puuid']
                probe = db.session.query(Probe).filter(Probe.uuid==probe_uuid).first()
                if not probe:
                    probe = Probe(sensor=sensor, uuid=pr['puuid'])#, data=newdata)
                    db.session.add(probe)
                    db.session.commit()
                newdata.probes.append(probe)
                #probe.data.append(newdata)
                for pd in pr['data']:
                    prtype = db.session.query(SensorType).filter(SensorType.ptype==pd['ptype']).first()
                    newprobedata = ProbeData(probe=probe, value=pd['value'], label=pd['label'], ptype=pd['ptype'])
                    if prtype:
                        newprobedata.prtype = prtype

                    db.session.add(newprobedata)
                    db.session.commit()
                    newdata.records.append(newprobedata)
                    db.session.add(newdata)
                    db.session.commit()

            app.logger.debug(["New data saved", newdata.id])

        return jsonify(self.schema.dump(newdata).data), 201

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
        app.logger.debug(["Request Data", request.values, request.files, request.json])
        camname = request.form.get("camname")
        camposition = request.form.get("camposition")
        flabel = request.form.get("flabel")
        recognize = request.form.get("recognize", False)
        camera_position = None
        app.logger.debug(["CAMERA DB:", camname, camposition, recognize])
        if not user:
            abort(403)

        data = db.session.query(Data).filter(Data.id == id).first()
        if data:
            sensor = data.sensor
            if sensor.user != user:
                abort(403)
            # Surely there's no camera for data.id. We should replace data.id with a sensor id.
            # TODO: >>> Fix
            camera = db.session.query(Camera).join(Data).filter(Data.id == data.id).filter(Camera.camlabel == camname).first()
            if not camera:
                camera = Camera(data=data, camlabel=camname)
                db.session.add(camera)
                db.session.commit()

            camera_position = db.session.query(CameraPosition).join(Camera).filter(Camera.id == camera.id).filter(CameraPosition.poslabel == camposition).first()
            if not camera_position:
                camera_position = CameraPosition(camera=camera, poslabel=camposition)
                db.session.add(camera_position)
                db.session.commit()

            app.logger.debug(["DB CAMERA", camera.camlabel, camera_position.poslabel])
            # data.cameras.append(camera)
            app.logger.debug(["RECOGNIZE", recognize])
            # To be sure to consume request data
            # to aviod "uwsgi-body-read Error reading Connection reset by peer" errors
            request_data = request.data
            app.logger.debug(["Consuming request data", len(request_data)])
            #if data.lux < 30:
            #    recognize = False
            lowlight = [d.value < 30 for d in data.records if d.ptype == 'light']
            if any(lowlight):
                recognize = False
            db.session.add(data)
            db.session.commit()
            # Running parse_request_pictures in the background
            req_files = [io.BytesIO(request.files.get(f).read()) for f in request.files]
            app.logger.debug(["FILES", req_files])
            st = threading.Thread(target=parse_request_pictures, args=[data.id, camera_position.id, req_files, flabel, camera, user.login, sensor.uuid, recognize])
            st.start()

            #res = st.join()
            #app.logger.debug(res)
            #parse_request_pictures()
            # db.session.commit()
            #if picts:
            #    for p in picts:
            #        data.pictures.append(p)
            return "Data added", 200
        #jsonify(self.schema.dump(data).data)
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
    #@cache.cached(timeout=300, key_prefix=cache_key)
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
    #@cache.cached(timeout=300, key_prefix=cache_key)
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
