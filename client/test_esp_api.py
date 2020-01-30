from fastapi import FastAPI

app = FastAPI()


@app.get("/info")
async def info():
    data = [{"UUID": "24:6F:28:97:0F:54"},
             {"ptype": "temp", "label": "T1", "value": 22.20},
             {"ptype": "temp", "label": "T2", "value": 24.40}, 
             {"ptype": "light", "label": "L", "value": 584}, 
    ]
    return data
