#!/usr/bin/env python

# WS client example

import asyncio
import websockets
import json
import time
import sys

# the code to be run in browser
async def hello():
    uri = "ws://trololo.info:6789"
    async with websockets.connect(uri, extra_headers={'suuid':'123asd', "sendto":"fe62aa26-9936-4aed-b6bb-81714fee630e"}) as websocket:
        #while True:
        try:
            #time.sleep(1)
            message = sys.argv[1]
            await websocket.send(message)
                
            # print("> {}".format(name))
            
            #greeting = await websocket.recv()
            #print("< {}".format(greeting))
        except websockets.ConnectionClosed:
            print("Terminated")
        #break

asyncio.get_event_loop().run_until_complete(hello())
