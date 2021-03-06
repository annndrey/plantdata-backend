import random
import os
from fastapi import FastAPI

app = FastAPI()


def get_random(a=1, b=100, roundto=2):
    return round(random.uniform(a, b), roundto)

def get_macaddr():
    #mac = "02:00:00:%02x:%02x:%02x" % (random.randint(0, 255),
    #                             random.randint(0, 255),
    #                             random.randint(0, 255))
    MAC = os.environ.get("MAC")
    return MAC

@app.get("/sensor_data")
async def info():
    data = { "UUID": get_macaddr(),
             "data": [
                 {"ptype":"temp","label":"T0","value": get_random(16.4, 23.5)},
                 {"ptype":"temp","label":"T1","value": get_random(18.4, 22.5)},
                 {"ptype":"temp","label":"T2","value": get_random(17.4, 18.5)},
                 {"ptype":"humid","label":"H0","value": get_random(60.3, 70.3)},
                 {"ptype":"humid","label":"H1","value": get_random(65.3, 69.3)},
                 {"ptype":"pres","label":"P0","value": get_random(100, 101, 0)},
                 {"ptype":"co2","label":"C0","value": get_random(200, 300, 0)},
                 {"ptype":"co2","label":"C1","value": get_random(200, 300, 0)},
                 {"ptype":"light","label":"L0","value": get_random(0, 100)}
             ]
    }

    return data
