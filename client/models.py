from sqlalchemy import ForeignKey, Column, Integer, Text, DateTime, Enum, Boolean, Numeric, String
from sqlalchemy.orm import backref, validates, relationship
from sqlalchemy.ext.declarative import declarative_base
import enum
import datetime

Base = declarative_base()

# TODO Add Probe & ProbeData

class Probe(Base):
    __tablename__ = 'probe'
    id = Column(Integer, primary_key=True)
    uuid = Column(Text(), nullable=False)
    bs_id = Column(Integer, ForeignKey('bsdata.id'))
    values = relationship("ProbeData", backref="probe", cascade="all,delete")

class ProbeData(Base):
    __tablename__ = 'probedata'
    id = Column(Integer, primary_key=True)
    probe_id = Column(Integer, ForeignKey('probe.id'))
    value = Column(Numeric(precision=3))
    ptype = Column(String(200))
    label = Column(String(200))
    

class BaseStationData(Base):
    __tablename__ = 'bsdata'
    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=datetime.datetime.now)
    bs_uuid = Column(Text(), nullable=False)
    remote_data_id = Column(Integer)
    photos = relationship("Photo", backref="bs", cascade="all,delete")
    probes = relationship("Probe", backref="basestation", cascade="all,delete")
    uploaded = Column(Boolean, default=False)
    
    
class Photo(Base):
    __tablename__ = 'photo'
    photo_id = Column(Integer, primary_key=True)
    bs_id = Column(Integer, ForeignKey('bsdata.id'))
    photo_filename  = Column(Text())
    label = Column(String(255))
    uploaded = Column(Boolean, default=False)
    camname = Column(String(255))
    camposition = Column(Integer)
