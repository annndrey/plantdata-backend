from sqlalchemy import ForeignKey, Column, Integer, Text, DateTime, Enum, Boolean
from sqlalchemy.orm import backref, validates, relationship
from sqlalchemy.ext.declarative import declarative_base
import enum
import datetime

Base = declarative_base()

class SensorData(Base):
    __tablename__ = 'sensordata'
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=datetime.datetime.now)
    sensor_uuid = Column(Text(), nullable=False, unique=True)
    # some data here
    temp0 = db.Column(db.Numeric(precision=3))
    temp1 = db.Column(db.Numeric(precision=3))
    hum0 = db.Column(db.Numeric(precision=3))
    hum1 = db.Column(db.Numeric(precision=3))
    tempA = db.Column(db.Numeric(precision=3))
    uv = db.Column(db.Integer)
    lux = db.Column(db.Integer)
    soilmoist = db.Column(db.Integer)
    co2 = db.Column(db.Integer)
    photos = relationship("Photo", backref="sensordata")
    uploaded = Column(Boolean, default=False)

class Photo(Base):
    __tablename__ = 'photo'
    photo_id = Column(Integer, primary_key=True)
    sensordata_id = Column(Integer, ForeignKey('sensordata.id'))
    photo_filename  = Column(Text())

