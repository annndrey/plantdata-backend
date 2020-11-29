#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import uvicorn
import json
import yaml
import datetime
import pytz


from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, or_, func

from client_parallel import get_token
from client_parallel import register_base_station
from client_parallel import get_base_station_uuid
from models import Base, BaseStationData, Photo, Probe, ProbeData

from fastapi.logger import logger as fastapi_logger
from logging.handlers import RotatingFileHandler
import logging



#logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
#                    datefmt='%H:%M:%S',
#                    level=logging.DEBUG)
#logger = logging.getLogger(__name__)

formatter = logging.Formatter(
    "[%(asctime)s.%(msecs)03d] %(levelname)s [%(thread)d] - %(message)s", "%Y-%m-%d %H:%M:%S")
handler = RotatingFileHandler("lora_listener.log", mode='a', maxBytes=1000000, backupCount=5, encoding='utf-8', delay=0)
logging.getLogger().setLevel(logging.DEBUG)
fastapi_logger.addHandler(handler)
handler.setFormatter(formatter)
fastapi_logger.info('****************** Starting Server *****************')


with open("config.yaml", 'r') as stream:
    try:
        CONFIG_FILE = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        fastapi_logger.debug(exc)

SERVER_LOGIN = CONFIG_FILE['SERVER_LOGIN']
SERVER_PASSWORD = CONFIG_FILE['SERVER_PASSWORD']
SERVER_HOST = CONFIG_FILE['SERVER_HOST'] 
tz = pytz.timezone('Europe/Moscow')

db_file = CONFIG_FILE['DB_FILE']
engine = create_engine('sqlite:///{}'.format(db_file))
Session = sessionmaker(bind=engine)
session = Session()
Base.metadata.create_all(engine, checkfirst=True)

app = FastAPI()


@app.on_event("startup")
async def startup_event():
    global base_station_uuid
    global token
    base_station_uuid, token = get_base_station_uuid()
    fastapi_logger.debug((["TOKEN", base_station_uuid, token]))
    if not base_station_uuid:
        token = get_token()
        base_station_uuid = register_base_station(token)
    

@app.post("/")
def read_root(request: Dict[Any, Any]):
    """
    A simple LoraWAN listener, working as an Application Server Integration.
    
    """
    req_json = request.get('objectJSON', None)
    fastapi_logger.debug(["Full request", request])
    if req_json:
        json_obj = json.loads(req_json)
        lora_data = json.loads(json_obj['DecodeDataString'])
        puuid = request.get('devEUI', None)
        plabel = request.get('deviceName', None)
        pdata = lora_data.get("data", None)

        sensordata = {}
        sensordata['uuid'] = base_station_uuid
        sensordata['TS'] = datetime.datetime.now(tz)

        bsrecord = BaseStationData(bs_uuid=sensordata['uuid'], ts=sensordata['TS'])
        session.add(bsrecord)
        session.commit()

        dbprobe = Probe(uuid=puuid, plabel=plabel)
        
        session.add(dbprobe)
        session.commit()
    
        bsrecord.probes.append(dbprobe)
        session.add(bsrecord)
        session.commit()
    
        for pd in pdata:
            if not pd['value']:
                pd['value'] = 0
            newpdata = ProbeData(probe=dbprobe, value=pd['value'], ptype=pd['ptype'], label=pd['label'])
            session.add(newpdata)
            session.commit()
        
    return request

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8181)
