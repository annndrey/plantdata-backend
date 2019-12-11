#!/usr/bin/env python
# -*- coding: utf-8 -*-

from functools import wraps
from flask import Flask, g, make_response, request, current_app, send_file, url_for
from flask_restful import Resource, Api, reqparse, abort, marshal_with
from flask.json import jsonify
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, desc
from sqlalchemy import func as sql_func
from flask_marshmallow import Marshmallow
from flask_httpauth import HTTPBasicAuth
from flask_cors import CORS, cross_origin
from flask_restful.utils import cors
from marshmallow import fields
from marshmallow_enum import EnumField
from models import db, User, Sensor, Location, Data, DataPicture, Camera, CameraPosition, Probe, ProbeData
import logging
import os
import uuid
import tempfile
import shutil
import zipfile
import urllib.parse
from celery import Celery

import click
import datetime
import calendar
from dateutil.relativedelta import relativedelta
from dateutil import parser
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

from multiprocessing.pool import ThreadPool

logging.basicConfig(format='%(levelname)s: %(asctime)s - %(message)s',
                    level=logging.DEBUG, datefmt='%d.%m.%Y %I:%M:%S %p')

app = Flask(__name__)
cors = CORS(app, resources={r"/*": {"origins": "*"}}, methods=['GET', 'POST', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
api = Api(app, prefix="/api/v1")
auth = HTTPBasicAuth()
app.config.from_envvar('APPSETTINGS')
app.config['PROPAGATE_EXCEPTIONS'] = True
db.init_app(app)
migrate = Migrate(app, db)
ma = Marshmallow(app)

gunicorn_logger = logging.getLogger('gunicorn.error')
app.logger.handlers = gunicorn_logger.handlers
app.logger.setLevel(gunicorn_logger.level)


CF_LOGIN = app.config['CF_LOGIN']
CF_PASSWORD = app.config['CF_PASSWORD']
CF_HOST = app.config['CF_HOST'] 
CF_TOKEN = None
FONT = app.config['FONT'] 
FONTSIZE = app.config['FONTSIZE']

zonefont = ImageFont.truetype(FONT, size=FONTSIZE)

CLASSIFY_ZONES = app.config['CLASSIFY_ZONES']

REDIS_HOST= app.config['REDIS_HOST']
REDIS_PORT= app.config['REDIS_PORT']
REDIS_DB= app.config['REDIS_DB']

app.config['CELERY_BROKER_URL'] = 'redis://{}:{}/{}'.format(REDIS_HOST, REDIS_PORT, REDIS_DB)
app.config['CELERY_RESULT_BACKEND'] = 'redis://{}:{}/{}'.format(REDIS_HOST, REDIS_PORT, REDIS_DB)

TMPDIR = app.config['TEMPDIR']


if CLASSIFY_ZONES:
    with open("cropsettings.yaml", 'r') as stream:
        try:
            CROP_SETTINGS = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            app.logger.debug(exc)


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


def get_zones():
    #2592х1944 224
    #for a in range(1,12) :
    #    print (224*a)
    p = 2592/4
    q = 1944/3
    #p==q
    n = 0
    res = {}
    for a in range(0,4) :
        #    print (int (p*a) )
        for b in range(0,3) :
            #        print (int (q*b) )
            n += 1
            zone = {'left': int(a*p),
                    'top': int(b*q),
                    'right': int((a+1)*p),
                    'bottom': int((b+1)*q)
            }
            res[f'zone{n}'] = zone
    return res


@celery.task
def crop_zones(results, cam_names, cam_positions, cam_zones, cam_numsamples, cam_skipsamples):
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
                                                p['original'] = p['original'].replace('https://plantdata.fermata.tech:5498/api/v1/p/', '')
                                                orig_fpath = os.path.join(current_app.config['FILE_PATH'], p['original'])
                                                orig_newpath = os.path.join(temp_dir, prefix+".jpg")
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
        

@app.before_first_request
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
        data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=data['sub']).first()

        if not user:
            abort(404)

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
    
# TODO: async
# process_single_picture
# process_single_zone

def parse_request_pictures(req_files, camname, camposition, user_login, sensor_uuid):
    picts = []
    
    for uplname in sorted(request.files):

        pict = request.files.get(uplname)
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
        
        imglabel = uplname
        app.logger.debug(["UPLNAME", uplname])
        classification_results = ""
        app.logger.debug("FILE SAVED")
        if CLASSIFY_ZONES and CF_TOKEN:
            # zones = CROP_SETTINGS.get(uplname, None)
            zones = get_zones()
            cf_headers = {'Authorization': 'Bearer ' + CF_TOKEN}
            # 2592x1944
            if zones:
                responses = []
                #original = Image.open(fullpath)
                for z in zones.keys():
                    cropped = original.crop((zones[z]['left'], zones[z]['top'], zones[z]['right'], zones[z]['bottom']))
                    img_io = io.BytesIO()
                    cropped.save(img_io, FORMAT, quality=100)
                    img_io.seek(0)
                    dr = ImageDraw.Draw(original)
                    dr.rectangle((zones[z]['left'], zones[z]['top'], zones[z]['right'], zones[z]['bottom']), outline = '#fbb040', width=3)
                    dr.text((zones[z]['left'], zones[z]['top']), z, font=zonefont)
                    # Now take an original image, crop the zones, send it to the
                    # CF server and get back the response for each
                    # Draw rectangle zones on the original image & save it
                    # Modify the image lzbel with zones results
                    # send CF request
                    response = requests.post(CF_HOST.format("loadimage"), headers=cf_headers, files = {'croppedfile': img_io}, data={'index':0, 'filename': ''})
                    if response.status_code == 200:
                        responses.append("{}: {}".format(z, response.json().get('objtype')))
                    else:
                        responses.append("{}".format(z))
                                         
                original.save(fullpath)
                classification_results = "Results: {}".format(", ".join(responses))
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
        db.session.add(newpicture)
        camposition.pictures.append(newpicture)
        db.session.commit()
        picts.append(newpicture)
        app.logger.debug("NEW PICTURE ADDED")
    return picts


@app.route('/api/v1/token', methods=['POST'])
@cross_origin(supports_credentials=True)
def get_auth_token_post():
    username = request.json.get('username')
    password = request.json.get('password')
    user = User.query.filter_by(login = username).first()
    if user:
        if user.verify_password(password):
            token = user.generate_auth_token()
            response = jsonify({ 'token': "%s" % token.decode('utf-8'), "user_id":user.id, "login": user.login, "name": user.name })
            return response
    abort(404)


@app.route('/api/v1/token', methods=['GET'])
def get_auth_token():
    token = g.user.generate_auth_token()
    return jsonify({ 'token': "%s" % token })


# SCHEMAS 
class UserSchema(ma.ModelSchema):
    class Meta:
        model = User

        
class CameraOnlySchema(ma.ModelSchema):
    class Meta:
        model = Camera
        exclude = ['positions', ]
    # positions = ma.Nested("CameraPositionSchema", many=True, exclude=["camera", "url"])#, exclude=['camera',])

class CameraSchema(ma.ModelSchema):
    class Meta:
        model = Camera
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
    

class DataPictureSchema(ma.ModelSchema):
    class Meta:
        model = DataPicture
        
    preview = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.thumbnail, _external=True, _scheme='https')))
    fpath = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.fpath, _external=True, _scheme='https')))
    original = ma.Function(lambda obj: urllib.parse.unquote(url_for("picts", path=obj.original, _external=True, _scheme='https')))
    
    # "fpath"
    # "label"
    # "original"
    # "preview"
    
    
class DPictureSchema(ma.ModelSchema):
    class Meta:
        model = DataPicture
        
    preview = ma.Function(lambda obj: obj.thumbnail if obj.thumbnail and os.path.exists(os.path.join(current_app.config['FILE_PATH'], obj.thumbnail)) else obj.fpath)

    #
    #camera_position = ma.Nested("CameraPositionSchema", many=True, exclude=['pictures', 'data', 'sensor', ''])
    
class LocationSchema(ma.ModelSchema):
    class Meta:
        model = Location
        

class DataSchema(ma.ModelSchema):
    class Meta:
        model = Data
        exclude = ['pictures', ]
    # pictures = ma.Nested("DPictureSchema", many=True, exclude=['thumbnail', 'data'])
    cameras = ma.Nested("CameraOnlySchema", many=True, exclude=["data",])#, exclude=['pictures', 'data', 'sensor'])
    # images = ma.Function(lambda obj: obj.images)

    
class FullDataSchema(ma.ModelSchema):
    class Meta:
        model = Data
        exclude = ['pictures', ]
    # pictures = ma.Nested("DPictureSchema", many=True, exclude=['thumbnail', 'data'])
    cameras = ma.Nested("CameraSchema", many=True, exclude=["data",])#, exclude=['pictures', 'data', 'sensor'])
    # images = ma.Function(lambda obj: obj.images)


    
class PictAPI(Resource):
    def __init__(self):
        self.schema = DataPictureSchema()
        self.m_schema = DataPictureSchema(many=True)
        self.method_decorators = []
        
    def options(self, *args, **kwargs):
        return jsonify([])

    #@token_required
    @cross_origin()
    def get(self, path):
        auth_cookie = request.cookies.get("auth", "")
        auth_headers = request.headers.get('Authorization', '').split()
        if len(auth_headers) > 0:
            token = auth_headers[1]
        elif len(auth_cookie) > 0:
            token = auth_cookie
        else:
            abort(403)
            
        data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=data['sub']).first()
        if not user:
            abort(404)
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
    def get(self, id):
        camera = db.session.query(Camera).filter(Camera.id==id).first()
        if camera:
            return jsonify(self.schema.dump(camera).data), 200
        return abort(404)
    
    
class StatsAPI(Resource):
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
    def get(self):
        # here the data should be scaled or not
        suuid = request.args.get('uuid', None)
        dataid = request.args.get('dataid', None)
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        datefrom = request.args.get('datefrom', None)
        dateto = request.args.get('dateto', None)
        fill_date = request.args.get('fill_date', False)
        export_zones = request.args.get('export_zones', False)
        export_data = request.args.get('export', False)
        full_data = request.args.get('full_data', False)
        cam_names = request.args.get('cam_names', False)
        cam_positions = request.args.get('cam_positions', False)
        cam_zones = request.args.get('cam_zones', False)
        cam_numsamples = request.args.get('cam_numsamples', False)
        cam_skipsamples = request.args.get('cam_skipsamples', False)
        data = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        daystart = dayend = None
        # By default show data for the last recorded day
        # 
        user = User.query.filter_by(login=data['sub']).first()
        if not user:
            abort(404)
        if not suuid:
            abort(404)
        if not dataid:
            first_rec_day = db.session.query(sql_func.min(Data.ts)).filter(Data.sensor.has(Sensor.uuid == suuid)).first()[0]
            last_rec_day = db.session.query(sql_func.max(Data.ts)).filter(Data.sensor.has(Sensor.uuid == suuid)).first()[0]
            if not all([datefrom, dateto]):
                if all([first_rec_day, last_rec_day]):
                    day_st = last_rec_day.replace(hour=0, minute=0)
                    day_end = last_rec_day.replace(hour=23, minute=59, second=59)
                else:
                    abort(404)
            else:
                day_st = datetime.datetime.strptime(datefrom, '%d-%m-%Y')
                day_st = day_st.replace(hour=0, minute=0)
                day_end = datetime.datetime.strptime(dateto, '%d-%m-%Y')
                day_end = day_end.replace(hour=23, minute=59, second=59)
            
            sensordata_query = db.session.query(Data).join(Sensor).filter(Sensor.uuid == suuid).order_by(Data.ts).filter(Data.ts >= day_st).filter(Data.ts <= day_end)
            sensordata = sensordata_query.all()
            if sensordata:
                if fill_date:
                    sensordata = self.fill_empty_dates(sensordata_query)
                if export_data:
                    app.logger.debug(f"EXPORT DATA, {export_data}")
                    proxy = io.StringIO()
                    writer = csv.writer(proxy, delimiter=';', quotechar='"',quoting=csv.QUOTE_MINIMAL)
                    writer.writerow(['sensor_id',
                                     'timestamp',
                                     'wght0',
                                     'wght1',
                                     'wght2',
                                     'wght3',
                                     'wght4',
                                     'temp0',
                                     'temp1',
                                     'hum0',
                                     'hum1',
                                     'tempA0',
                                     'lux',
                                     'co2'
                    ])
                    for r in sensordata:
                        writer.writerow([r.sensor.id,
                                         r.ts,
                                         r.wght0,
                                         r.wght1,
                                         r.wght2,
                                         r.wght3,
                                         r.wght4,
                                         r.temp0,
                                         r.temp1,
                                         r.hum0,
                                         r.hum1,
                                         r.tempA,
                                         r.lux,
                                         r.co2
                        ])
                    mem = io.BytesIO()
                    mem.write(proxy.getvalue().encode('utf-8'))
                    mem.seek(0)
                    proxy.close()
                    return send_file(mem, mimetype='text/csv', attachment_filename="file.csv", as_attachment=True)
                if export_zones:
                    app.logger.debug(f"EXPORT ZONES, {export_zones}")
                    
                    res_data = sensordata_query.filter(Data.pictures.any()).all()
                    app.logger.debug(len(res_data))
                    crop_zones.delay(self.f_schema.dump(res_data).data, cam_names, cam_positions, cam_zones, cam_numsamples, cam_skipsamples)
                    
                    res = {"numrecords": len(res_data),
                           'mindate': first_rec_day,
                           'maxdate': last_rec_day,
                           'data': self.m_schema.dump(res_data).data
                    }
                    return jsonify(res), 200
                    
                else:
                    if full_data:
                        data = self.f_schema.dump(sensordata).data
                    else:
                        data = self.m_schema.dump(sensordata).data
                        
                    res = {"numrecords": len(sensordata),
                           'mindate': first_rec_day,
                           'maxdate': last_rec_day,
                           'data': data
                    }
                    return jsonify(res), 200

        else:
            sensordata = db.session.query(Data).filter(Data.sensor.has(uuid=suuid)).filter(Data.id == dataid).first()
            if sensordata:
                return jsonify(self.schema.dump(sensordata).data), 200
            
        return abort(404)

    @token_required
    @cross_origin()
    def post(self):
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        suuid = request.form.get('uuid')
        sensor = db.session.query(Sensor).filter(Sensor.uuid == suuid).first()
      
        if sensor:
            if sensor.user != user:
                abort(403)
            wght0 = float(request.form.get('WGHT0', -1))
            wght1 = float(request.form.get('WGHT1', -1))
            wght2 = float(request.form.get('WGHT2', -1))
            wght3 = float(request.form.get('WGHT3', -1))
            wght4 = float(request.form.get('WGHT4', -1))
            temp0 = float(request.form.get('T0'))
            temp1 = float(request.form.get("T1"))
            tempA = float(request.form.get("TA"))
            hum0 = float(request.form.get("H0"))
            hum1 = float(request.form.get("H1"))
            uv = int(request.form.get("UV"))
            lux = int(request.form.get("L"))
            soilmoist = int(request.form.get("M"))
            co2 = int(request.form.get("CO2"))
            ts = request.form.get("ts")
            
            # picts = parse_request_pictures(request.files, user.login, sensor.uuid)
            
            newdata = Data(sensor_id=sensor.id,
                           wght0 = wght0,
                           wght1 = wght1,
                           wght2 = wght2,
                           wght3 = wght3,
                           wght4 = wght4,
                           ts = ts,
                           temp0 = temp0,
                           temp1 = temp1,
                           tempA = tempA,
                           hum0 = hum0,
                           hum1 = hum1,
                           uv = uv,
                           lux = lux,
                           soilmoist = soilmoist,
                           co2 = co2
            )
            db.session.add(newdata)
            db.session.commit()
            app.logger.debug(["New data saved", newdata.id])
                        
            # for p in picts:
            #    p.data_id = newdata.id
            #    db.session.add(p)
            #    db.session.commit()
        app.logger.debug(["REQUEST", request.json, user.login, sensor.uuid])
            
        return jsonify(self.schema.dump(newdata).data), 201

    @token_required
    @cross_origin()
    def patch(self, id=None):
        if not id:
            abort(400)
        app.logger.debug("Patch Data")
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'], options={'verify_exp': False})
        user = User.query.filter_by(login=udata['sub']).first()
        # If there's no registered CAMNAME & CAMPOSITION for a given data.uuid
        # add new camera & position
        # >>>
        camname = request.form.get("camname")
        camposition = request.form.get("camposition")
        camera_position = None
        app.logger.debug(["CAMERA DB:", camname, camposition])
        if not user:
            abort(403)
            
        data = db.session.query(Data).filter(Data.id == id).first()
        if data:
            sensor = data.sensor
            if sensor.user != user:
                abort(403)
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
            picts = parse_request_pictures(request.files, camera, camera_position, user.login, sensor.uuid)
            if picts:
                for p in picts:
                    data.pictures.append(p)
            db.session.add(data)
            db.session.commit()
            return jsonify(self.schema.dump(data).data)
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
    def get(self, id=None):
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
    def get(self, id=None):
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
        if not id:
            abort(404, message="Not found")
        user = db.session.query(User).filter(User.id==id).first()
        if user:
            db.session.delete(user)
            db.session.commit()
            return make_response("User deleted", 204)
        abort(404, message="Not found")

        
api.add_resource(UserAPI, '/users', '/users/<int:id>', endpoint='users')
api.add_resource(CameraAPI, '/cameras/<int:id>', endpoint='cameras')
api.add_resource(StatsAPI, '/data', '/data/<int:id>', endpoint='savedata')
api.add_resource(SensorAPI, '/sensors', '/sensors/<int:id>', endpoint='sensors')
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
