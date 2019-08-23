#!/usr/bin/env python
#Ю -*- coding: utf-8 -*-

from functools import wraps
from flask import Flask, g, make_response, request, current_app
from flask_restful import Resource, Api, reqparse, abort, marshal_with
from flask.json import jsonify
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from sqlalchemy import func as sql_func
from flask_marshmallow import Marshmallow
from flask_httpauth import HTTPBasicAuth
from flask_cors import CORS, cross_origin
from flask_restful.utils import cors
from marshmallow import fields
from marshmallow_enum import EnumField
from models import db, User, UserQuery

import os
import uuid

import click
import datetime
import calendar
from dateutil.relativedelta import relativedelta
import jwt
import json

# AI
import torch
import torchvision
from torchvision import datasets, models, transforms

import io
import requests
from PIL import Image
import glob
from collections import OrderedDict


app = Flask(__name__)
cors = CORS(app, resources={r"/*": {"origins": "*"}}, support_credentials=True, methods=['GET', 'POST', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
api = Api(app, prefix="/api/v1")
auth = HTTPBasicAuth()
app.config.from_envvar('APPSETTINGS')
app.config['PROPAGATE_EXCEPTIONS'] = True
db.init_app(app)
migrate = Migrate(app, db)
ma = Marshmallow(app)

# _____________________ AI Section _____________________

plant_or_not_path = app.config['PLANT_OR_NOT_PATH']
leaf_or_not_path = app.config['LEAF_OR_NOT_PATH']
tomat_or_not_path = app.config['TOMAT_OR_NOT_PATH']
plant_health_or_not_path = app.config['PLANT_HEALTH_OR_NOT_PATH']
tomat_health_or_not_path = app.config['TOMAT_HEALTH_OR_NOT_PATH']

using_model_name = app.config['USING_MODEL_NAME']
num_classes_used = app.config['NUM_CLASSES_USED']
resize = (224,224)

using_data_transform = transforms.Compose([
    transforms.Resize(resize, interpolation=2),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
])

pil_transform = transforms.Compose([
    transforms.Resize(resize, interpolation=2),
])

modres = ( { 0 : "it's not a tomato", 1 : "it's a tomato" },
           { 0 : "it's a healthy tomato", 1 : "it's an unhealthy tomato" },
           { 0 : "it's a healthy plant", 1 : "it's an unhealthy plant" }
)

global aimodels

aimodels = {}

all_models = {
    'plant_or_not': plant_or_not_path,
    'leaf_or_not': leaf_or_not_path,
    'tomat_or_not': tomat_or_not_path,
    'tomat_health_or_not': tomat_health_or_not_path,
    'plant_health_or_not': plant_health_or_not_path
}

models_to_apply = ("plant_or_not", "leaf_or_not", "tomat_or_not", "tomat_health_or_not", "plant_health_or_not")

def get_model_results(modelname, results, img):
    model = aimodels[modelname]
    idx_to_class = {v: k for k, v in model.class_to_idx.items()}
    print("MODEL", idx_to_class)
    outputs = model(img)
    _, preds = torch.max(outputs, 1)
    detected_img_type = idx_to_class[int(preds)]
    results[modelname] = detected_img_type
    return results

def remove_transparency(im, bg_colour=(255, 255, 255)):
    # Only process if image has
    # transparency (http://stackoverflow.com/a/1963146)
    if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
        # Need to convert to RGBA if LA format
        # due to a bug in PIL (http://stackoverflow.com/a/1963146)
        alpha = im.convert('RGBA').split()[-1]
        # Create a new background image of our matt color.
        # Must be RGBA because paste requires both images have the same format
        # (http://stackoverflow.com/a/8720632  and  http://stackoverflow.com/a/9459208)
        bg = PIL.Image.new("RGB", im.size, bg_colour + (255,))
        bg.paste(im, mask=alpha)
        return bg
    else:
        return im


def load_model_to_continue_froma_state_dict(file_name, gpu_or_cpu='cpu'):
    print('Loading model for continue training : "{}" to "{}" '.format(file_name, gpu_or_cpu))
    assert gpu_or_cpu=='gpu' or gpu_or_cpu=='cpu' 
    checkpoint = torch.load(file_name, map_location='cpu')
    print( "Saved entities: ", checkpoint.keys())
    if 'state_dict' in checkpoint:
        state_dict = checkpoint['state_dict']
    else:
        state_dict = checkpoint
    arch = checkpoint['arch']
    class_to_idx = checkpoint['class_to_idx']
    num_classes = len(class_to_idx)
    model = torchvision.models.__dict__[arch](num_classes=num_classes)
    model_dict = model.state_dict()
    new_state_dict = OrderedDict()
    matched_layers, discarded_layers = [], []
    for k, v in state_dict.items():
        if k.startswith('module.'):
            k = k[7:]
        if k in model_dict and model_dict[k].size() == v.size():
            new_state_dict[k] = v
            matched_layers.append(k)
        else:
            discarded_layers.append(k)
    model_dict.update(new_state_dict)
    model.load_state_dict(model_dict)
    model.class_to_idx = class_to_idx
    if len(matched_layers) == 0:
        print('The pretrained weights "{}" cannot be loaded, please check the key names manually (** ignored and continue **)'.format(weight_path))
    else:
        print('Successfully loaded pretrained weights from "{}":\n"{}"'.format(file_name, matched_layers))
        if len(discarded_layers) > 0:
            print("!!!!!! The following layers are discarded due to unmatched keys or layer size: {}".format(discarded_layers))
            return

    if gpu_or_cpu=='gpu':
        print("Transfering models to GPU(s)")
        model = torch.nn.DataParallel(model_pretrained).cuda()
    return model

            
@app.before_first_request            
def loadmodels():
   
    for k in models_to_apply:
        amodel = load_model_to_continue_froma_state_dict( all_models[k])
        amodel.eval()
        aimodels[k] = amodel

# _____________________ AI Section _____________________


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

        #try:
        token = auth_headers[1]
        data = jwt.decode(token, current_app.config['SECRET_KEY'])
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


class StatsAPI(Resource):
    def __init__(self):
        self.reqparse = reqparse.RequestParser()
    
    def options(self, *args, **kwargs):
        return jsonify([])

    @token_required
    @cross_origin()
    def get(self, id=None):
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        data = jwt.decode(token, current_app.config['SECRET_KEY'])
        user = User.query.filter_by(login=data['sub']).first()
        if not user:
            abort(404)

        return jsonify({})

    @token_required
    @cross_origin()
    def post(self):
        print("REQUEST", request.remote_addr)
        auth_headers = request.headers.get('Authorization', '').split()
        token = auth_headers[1]
        udata = jwt.decode(token, current_app.config['SECRET_KEY'])
        user = User.query.filter_by(login=udata['sub']).first()
        fpath = os.path.join(current_app.config['FILE_PATH'], user.login)
        maxqueryage = current_app.config['QUERY_AGE']
        if not user:
            return abort(403)

        index = request.form['index']
        orig_name = request.form['filename']
        f = request.files['croppedfile']
        data = f.read()
        fsize = len(data)
        imgext = os.path.splitext(f.filename)[-1].lower()
        #print(1)
        if not os.path.exists(fpath):
            os.makedirs(fpath)
        #print(2)
        fuuid = str(uuid.uuid4())
        fname = fuuid + imgext
        #print(3)
        prevquery = db.session.query(UserQuery).filter(UserQuery.orig_name == orig_name).filter(UserQuery.fsize == fsize).filter(UserQuery.user == user).first()
        if prevquery and prevquery.queryage <= maxqueryage:
            #print(11)
            # return existing data without calculating
            print("SAVED RESULTS")
            resp = json.loads(prevquery.result)
        else:
            print("NEW RESULTS")
            fullpath = os.path.join(fpath, fname)

            with open(fullpath, 'wb') as outf:
                outf.write(data)
            #print(4)
            # AI Section start
            img_pil = Image.open(io.BytesIO(data))
            if imgext == '.png':
                img_pil = remove_transparency(img_pil)

            img_tensor = using_data_transform(img_pil)
            img_tensor.unsqueeze_(0)
            img_variable = img_tensor
            result = {}
            # passing the image to models
            # and getting back the result

            # 1. plant / non plant 
            # if not plant:
            # return result
            # if plant:
            # 2. leaf / non leaf
            # if not leaf:
            # return result
            # if leaf:
            # 3. tomato / non tomato
            # if tomato:
            # 4. tomato healthy / unhealthy
            # if not tomato:
            # 5. plant healthy / unhealthy

            print("1 Plant / non plant")
            result = get_model_results('plant_or_not', result, img_variable)
            
            if result['plant_or_not'] == "plant":
                print("Leaf / non leaf")

                result = get_model_results('leaf_or_not', result, img_variable)
                
                if result['leaf_or_not'] == "leaf":
                    print("tomato / non tomato")
                    result = get_model_results('tomat_or_not', result, img_variable)

                    if result['tomat_or_not'] == "tomat":
                        print("health_tomato or not")
                        result = get_model_results('tomat_health_or_not', result, img_variable)
                    else:
                        print("health_plant or not")
                        result = get_model_results('plant_health_or_not', result, img_variable)
                

            print('RESULT', result)
            # AI Section ends
            
            objtype = result.get("plant_or_not", "non_plant")
            picttype = result.get("leaf_or_not", "not_single_leaf")
            planttype = result.get("tomat_or_not", "non_tomat")
            tomatostatus = result.get("tomat_health_or_not", "tomat_non_health")
            plantstatus = result.get("plant_health_or_not", "plants_non_health")
            
            resp  = {'objtype': objtype, 'picttype': picttype, 'planttype': planttype, 'plantstatus': plantstatus, 'tomatostatus': tomatostatus, 'index': index, 'filename': orig_name}
            print("RESP", resp)

            newquery = UserQuery(local_name=fname, orig_name=orig_name, user=user, result=json.dumps(resp), fsize=fsize)
            db.session.add(newquery)
            db.session.commit()

        print(resp)
        return jsonify(resp)


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

api.add_resource(UserAPI, '/users', '/users/<int:id>', endpoint = 'users')
api.add_resource(StatsAPI, '/loadimage', endpoint = 'loadimage')


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

                
if __name__ == '__main__':
    app.debug = True
    app.run(host='0.0.0.0')
