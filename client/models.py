from sqlalchemy import ForeignKey, Column, Integer, Text, DateTime, Enum, Boolean, Numeric, String
from sqlalchemy.orm import backref, validates, relationship
from sqlalchemy.ext.declarative import declarative_base
import enum
import datetime

Base = declarative_base()

# TODO Add Probe & ProbeData

#class Probe(Base):
#    id = Column(Integer, primary_key=True)
#    uuid = Column(Text(), nullable=False)
#    data_id = Column(Integer, ForeignKey('sensor_data.id'))
#    data = relationship("SensorData", backref=backref("probes", uselist=True))
#    ptype = Column(String(200))
#    label = Column(String(200))
#    minvalue = Column(Numeric(precision=3))
#    maxvalue = Column(Numeric(precision=3))


#class ProbeData(Base):
#    d = Column(Integer, primary_key=True)
#    probe_id = Column(Integer, ForeignKey('probe.id'))
#    probe = relationship("Probe", backref=backref("values", uselist=True))
#    value = Column(Numeric(precision=3))
    

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
