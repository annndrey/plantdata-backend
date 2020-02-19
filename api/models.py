#!/usr/bin/python
# -*- coding: utf-8 -*-

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, ForeignKey, Table
from sqlalchemy.orm import backref, validates, relationship
from sqlalchemy.ext.hybrid import hybrid_property
from passlib.apps import custom_app_context as pwd_context
from itsdangerous import URLSafeSerializer, BadSignature, SignatureExpired
from flask import current_app, jsonify
from flask_login import UserMixin
import datetime
import enum
import jwt
import calendar

db = SQLAlchemy()

class Gender(enum.Enum):
    m = u'm'
    f = u'f'
    n = 'na'


#data_cameras = db.Table('data_cameras', db.Model.metadata,
#                        db.Column('data_id', db.Integer, db.ForeignKey('data.id')),
#                        db.Column('camera_id', db.Integer, db.ForeignKey('camera.id'))
#)
#
data_probes = db.Table('data_probes', db.Model.metadata,
                       db.Column('data_id', db.Integer, db.ForeignKey('data.id')),
                       db.Column('probe_id', db.Integer, db.ForeignKey('probe.id'))
)



class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(400))
    name = db.Column(db.String(400))
    password_hash = db.Column(db.String(400))
    note = db.Column(db.Text(), nullable=True)
    is_confirmed = db.Column(db.Boolean, default=False)
    confirmed_on = db.Column(db.DateTime, default=False)
    registered_on = db.Column(db.DateTime, default=datetime.datetime.today)
    phone = db.Column(db.String(400))
    additional_email = db.Column(db.String(400))
    is_admin = db.Column(db.Boolean, default=False)
    
    @validates('login')
    def validate_login(self, key, login):
        if len(login) > 1:
            assert '@' in login, 'Invalid email'
        return login
    
    def hash_password(self, password):
        self.password_hash = pwd_context.encrypt(password)

    def verify_password(self, password):
        return pwd_context.verify(password, self.password_hash)

    def generate_auth_token(self):
        # Change expiration value
        token = jwt.encode({
        'sub': self.login,
        'iat': datetime.datetime.utcnow(),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=60000)},
        current_app.config['SECRET_KEY'])
        return token

    @staticmethod
    def verify_auth_token(token):
        s = URLSafeSerializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token)
        except SignatureExpired:
            return None 
        except BadSignature:
            return None 
        user = Staff.query.get(data['id'])
        return user

    
class ProbeData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    probe_id = db.Column(db.Integer, ForeignKey('probe.id'))
    probe = relationship("Probe", backref=backref("values", uselist=True))
    data_id = db.Column(db.Integer, ForeignKey('data.id'))
    data = relationship("Data", backref=backref("records", uselist=True))
    value = db.Column(db.Float())
    ptype = db.Column(db.String(200))
    label = db.Column(db.String(200))
    prtype_id = db.Column(db.Integer, ForeignKey('sensor_type.id'))
    prtype = relationship("SensorType", backref=backref("values", uselist=True))


class Probe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.Text(), nullable=False)
    sensor_id = db.Column(db.Integer, ForeignKey('sensor.id'))
    sensor = relationship("Sensor", backref=backref("probes", uselist=True))
    #records = relationship("Data", secondary=data_probes)
    #data_id = db.Column(db.Integer, ForeignKey('data.id'))
    #data = relationship("Data", backref=backref("probes", uselist=True))


    
# Sensors
class Sensor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.Text(), nullable=False)
    user_id = db.Column(db.Integer, ForeignKey('user.id'))
    user = relationship("User", backref=backref("sensors"))
    location_id = db.Column(db.Integer, ForeignKey('location.id'))
    location = relationship("Location", backref=backref("sensors"))
    registered = db.Column(db.DateTime, default=datetime.datetime.now)

    @hybrid_property
    def numrecords(self):
        return len(self.data)

    @hybrid_property
    def mindate(self):
        ts = [d.ts for d in self.data]
        if ts:
            return min(ts)
        else:
            return 0

        return min([d.ts for d in self.data])
    
    @hybrid_property
    def maxdate(self):
        ts = [d.ts for d in self.data]
        if ts:
            return max(ts)
        else:
            return 0
    
# Locations
# descr
# lat
# lon
# address
class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.Text(), nullable=True)
    lat = db.Column(db.Text(), nullable=True)
    lon = db.Column(db.Text(), nullable=True)


class SensorType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    minvalue = db.Column(db.Float(), nullable=True)
    maxvalue = db.Column(db.Float(), nullable=True)
    ptype = db.Column(db.String(200))
    

class Data(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sensor_id = db.Column(db.Integer, ForeignKey('sensor.id'))
    sensor = relationship("Sensor", backref=backref("data", uselist=True))
    ts = db.Column(db.DateTime, default=datetime.datetime.now)
    probes = relationship("Probe", secondary=data_probes, lazy='joined', backref=backref('data', lazy='joined'))

    
class DataPicture(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_id = db.Column(db.Integer, ForeignKey('data.id'))
    data = relationship("Data", backref=backref("pictures", uselist=True))
    camera_position_id = db.Column(db.Integer, ForeignKey('camera_position.id'))
    camera_position = relationship("CameraPosition", backref=backref("pictures", uselist=True))
    fpath = db.Column(db.Text())
    thumbnail = db.Column(db.Text())
    label = db.Column(db.Text())
    original = db.Column(db.Text())
    results = db.Column(db.Text())
    ts = db.Column(db.DateTime, default=datetime.datetime.now)


class PictureZone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    picture_id = db.Column(db.Integer, ForeignKey('data_picture.id'))
    picture = relationship("DataPicture", backref=backref("zones", uselist=True))
    fpath = db.Column(db.Text())
    results = db.Column(db.Text())
    zone = db.Column(db.Text())
    ts = db.Column(db.DateTime, default=datetime.datetime.now)
    
    
class Camera(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_id = db.Column(db.Integer, ForeignKey('data.id'))
    data = relationship("Data", backref=backref("cameras", uselist=True))
    camlabel = db.Column(db.Text())
    url = db.Column(db.Text())


class CameraPosition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    camera_id = db.Column(db.Integer, ForeignKey('camera.id'))
    camera = relationship("Camera", backref=backref("positions", uselist=True))
    poslabel = db.Column(db.Integer)
    url = db.Column(db.Text())

        
