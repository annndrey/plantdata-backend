#!/usr/bin/env python3

# WS client example

import asyncio
import websockets
import json
import time

from client_parallel import get_base_station_uuid




SERVER_URL = "ws://dev.plantdata.fermata.tech:6789"

async def rpi_client():
    bsuuid, _ = get_base_station_uuid()
    print(f"Registering the BS {bsuuid}")
    async with websockets.connect(SERVER_URL, extra_headers={"suuid": bsuuid}) as websocket:
        while True:
            try:
                #await websocket.send(data)
                # print("> {}".format(name))
                print("Waiting for message")
                greeting = await websocket.recv()
                print("< {}".format(greeting))
            except websockets.ConnectionClosed:
                print("Terminated")
                break

print("Starting the ws app")
asyncio.get_event_loop().run_until_complete(rpi_client())
        
