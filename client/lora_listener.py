import uvicorn
import json
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict

    

app = FastAPI()


@app.post("/")
def read_root(request: Dict[Any, Any]):
    sensor_data = json.loads(json.loads(request['objectJSON'])['DecodeDataString'])
    print(sensor_data)
    return request

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8181)
