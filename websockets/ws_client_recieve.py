#!/usr/bin/env python

# WS client example

import asyncio
import websockets
import json
import time


async def hello():
    uri = "ws://trololo.info:6789"
    async with websockets.connect(uri, extra_headers={"client":"111"}) as websocket:
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
            
asyncio.get_event_loop().run_until_complete(hello())
        
