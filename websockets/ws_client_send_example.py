#!/usr/bin/env python

# WS client example

import asyncio
import websockets
import json
import time

async def hello():
    uri = "ws://trololo.info:6789"
    async with websockets.connect(uri, extra_headers={"client":"222"}) as websocket:
        while True:
            try:
                time.sleep(1)
                await websocket.send("ololo")
                # print("> {}".format(name))

                #greeting = await websocket.recv()
                #print("< {}".format(greeting))
            except websockets.ConnectionClosed:
                print("Terminated")
                break

asyncio.get_event_loop().run_until_complete(hello())
