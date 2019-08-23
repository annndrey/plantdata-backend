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


class UserQuery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    local_name = db.Column(db.Text(), nullable=True)
    orig_name = db.Column(db.Text(), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now())
    user_id = db.Column(db.Integer, ForeignKey('user.id'))
    user = relationship("User", backref=backref("queries"))
    result = db.Column(db.Text(), nullable=True)
    fsize = db.Column(db.Integer)

    @hybrid_property
    def queryage(self):
        # query age in seconds
        today = datetime.datetime.today()
        diff = today - self.timestamp
        return diff.seconds
