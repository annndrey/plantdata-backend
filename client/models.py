from sqlalchemy import ForeignKey, Column, Integer, Text, DateTime, Enum, Boolean, Numeric, String
from sqlalchemy.orm import backref, validates, relationship
from sqlalchemy.ext.declarative import declarative_base
import enum
import datetime

Base = declarative_base()

#class Weight(Base):
#    __tablename__ = 'weight'
#    id = Column(Integer, primary_key=True)
#    label = Column(String(255))
#    value = Column(Integer)
#    ts = Column(DateTime, default=datetime.datetime.now)

    
class SensorData(Base):
    __tablename__ = 'sensordata'
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=datetime.datetime.now)
    sensor_uuid = Column(Text(), nullable=False)
    remote_data_id = Column(Integer)
    # some data here
    temp0 = Column(Numeric(precision=3))
    temp1 = Column(Numeric(precision=3))
    hum0 = Column(Numeric(precision=3))
    hum1 = Column(Numeric(precision=3))
    tempA = Column(Numeric(precision=3))
    uv = Column(Integer)
    lux = Column(Integer)
    soilmoist = Column(Integer)
    co2 = Column(Integer)
    wght0 = Column(Numeric(precision=3))
    wght1 = Column(Numeric(precision=3))
    wght2 = Column(Numeric(precision=3))
    wght3 = Column(Numeric(precision=3))
    wght4 = Column(Numeric(precision=3))
    photos = relationship("Photo", backref="sensordata", cascade="all,delete")
    uploaded = Column(Boolean, default=False)
    
    
class Photo(Base):
    __tablename__ = 'photo'
    photo_id = Column(Integer, primary_key=True)
    sensordata_id = Column(Integer, ForeignKey('sensordata.id'))
    photo_filename  = Column(Text())
    label = Column(String(255))
    uploaded = Column(Boolean, default=False)
    camname = Column(String(255))
    camposition = Column(Integer)
