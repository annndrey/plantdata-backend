#!/usr/bin/env python
# -*- coding: utf-8 -*-


import asyncio
import json
import websockets

clients = {}

async def counter(websocket, path):
    # register(websocket) sends user_event() to websocket
    client_id = websocket.request_headers.get("suuid")
    sendto = websocket.request_headers.get("sendto", None)
    #
    if client_id not in clients.keys():
        clients[client_id] = websocket
    print(f"Registered {client_id}")
    while True:
        try:
            data = await websocket.recv()
            # Simple redirect from 222 to 111
            if sendto:
                print(f"sending data to {sendto}")
                reciever = clients.get(sendto, None)
                if reciever:
                    await reciever.send(data)

        except websockets.ConnectionClosed:
            print(f"Connection closed for {client_id}")
            del clients[client_id]
            break


start_server = websockets.serve(counter, "192.168.1.4", 6789)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
