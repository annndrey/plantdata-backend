#!/usr/bin/env python
# -*- coding: utf-8 -*-


import asyncio
import json
import logging
import websockets

clients = {}

async def counter(websocket, path):
    # register(websocket) sends user_event() to websocket
    
    client_id = websocket.request_headers.get("client")
    if client_id not in clients.keys():
        clients[client_id] = websocket
    while True:
        try:
            name = await websocket.recv()
            print(clients)
            if client_id == "222":
                print("sending message to 111")
                sendto = clients.get('111', None)
                if sendto:
                    await sendto.send(str("Hello from {}".format(client_id)))

        except websockets.ConnectionClosed:
            print(f"Terminated")
            del clients[client_id]
            break


start_server = websockets.serve(counter, "192.168.1.4", 6789)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
