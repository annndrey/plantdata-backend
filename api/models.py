#!/usr/bin/python
# -*- coding: utf-8 -*-

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import CheckConstraint, ForeignKey
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

    
# Sensors
# one sensor - one user
# one sensor - one location
# sensor uuid - unique
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


# Data
# one row - one sensor
class Data(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sensor_id = db.Column(db.Integer, ForeignKey('sensor.id'))
    sensor = relationship("Sensor", backref=backref("data", uselist=True))
    ts = db.Column(db.DateTime, default=datetime.datetime.now)
    temp0 = db.Column(db.Numeric(precision=3))
    wght0 = db.Column(db.Numeric(precision=3))
    temp1 = db.Column(db.Numeric(precision=3))
    hum0 = db.Column(db.Numeric(precision=3))
    hum1 = db.Column(db.Numeric(precision=3))
    tempA = db.Column(db.Numeric(precision=3))
    uv = db.Column(db.Integer)
    lux = db.Column(db.Integer)
    soilmoist = db.Column(db.Integer)
    co2 = db.Column(db.Integer)
    fpath = db.Column(db.Text())

class DataPicture(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_id = db.Column(db.Integer, ForeignKey('data.id'))
    data = relationship("Data", backref=backref("pictures", uselist=True))
    fpath = db.Column(db.Text())
    label = db.Column(db.String(255))
