#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Use this lib for onvif:
# https://github.com/annndrey/python-onvif-zeep


from tkinter import *
import tkinter
import requests
from PIL import Image, ImageTk
from io import BytesIO
from threading import Thread
import cv2
from time import sleep
from onvif import ONVIFCamera
import copy

XMAX = 1
XMIN = -1
YMAX = 1
YMIN = -1



CAM_URL = "testapi.me"
CAM_PORT = 7089
CAM_ADMIN = "admin"
CAM_PASS = "123456"
CAM_WSDL = "venv/lib/python3.8/site-packages/wsdl"

base_url = "http://admin:123456@testapi.me:7081"


def perform_move(ptz, req, timeout=0.5):
    # Start continuous move
    print("move", req)
    ptz.ContinuousMove(req)
    # Wait a certain time
    sleep(timeout)
    # req.PanTilt = 1
    # Stop continuous move
    ptz.Stop({'ProfileToken': req.ProfileToken})

def move_left(ptz, request, ptz_status, timeout=0.5):
    print('move left...')
    ptz_status.Position.PanTilt.x = XMIN/3
    ptz_status.Position.PanTilt.y = 0 
    ptz_status.Position.Zoom.x = 0   
    request.Velocity = ptz_status.Position
    perform_move(ptz, request, timeout)

    
def move_right(ptz, request, ptz_status, timeout=0.5):
    print('move right...', request)
    ptz_status.Position.PanTilt.x = XMAX/3
    ptz_status.Position.PanTilt.y = 0
    ptz_status.Position.Zoom.x = 0    
    request.Velocity = ptz_status.Position
    perform_move(ptz, request, timeout)

def move_up(ptz, request, ptz_status, timeout=0):
    print('move up...')
    ptz_status.Position.PanTilt.x = 0
    ptz_status.Position.PanTilt.y = YMAX/3
    ptz_status.Position.Zoom.x = 0    
    request.Velocity = ptz_status.Position
    perform_move(ptz, request, timeout)

def move_down(ptz, request, ptz_status, timeout=1):
    print('move down...')
    ptz_status.Position.PanTilt.x = 0
    ptz_status.Position.PanTilt.y = YMIN/3
    ptz_status.Position.Zoom.x = 0
    request.Velocity = ptz_status.Position
    perform_move(ptz, request, timeout)
    
def move_zoom(ptz, request, ptz_status, val, timeout=2):
    print('zoom...')
    ptz_status.Position.Zoom.x = val
    ptz_status.Position.PanTilt.x = 0
    ptz_status.Position.PanTilt.y = 0
    request.Velocity = ptz_status.Position
    perform_move(ptz, request, timeout)

def ptz_preset_set(ptz, token, preset_num):
    r = ptz.create_type('SetPreset')
    r.ProfileToken = token
    r.PresetToken = str(preset_num.get())
    ptz.SetPreset(r)
    
def ptz_preset_call(ptz, token, preset_num):
    r = ptz.create_type('GotoPreset')
    r.ProfileToken = token
    r.PresetToken = str(preset_num.get())
    ptz.GotoPreset(r)


def on_change(e):
    global base_url
    base_url = e.widget.get()

        
def open_img():
    global base_url
    print(base_url)
    img_url = base_url + "/jpgimage/1/image.jpg"
    try:
        cap = cv2.VideoCapture(img_url)
        _, frame = cap.read()
        #frame = cv2.flip(frame, 1)
        cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        img = Image.fromarray(cv2image)
        imgtk = ImageTk.PhotoImage(image=img)
        label1.image = imgtk
        label1.configure(image = imgtk)
    except:
        pass
    label1.after(50, open_img)
    #except:
    #    pass
    #img_url = base_url + "/jpgimage/1/image.jpg"
    #response = requests.get(img_url)
    #print(response.status_code)
    #img_data = response.content
    #img = ImageTk.PhotoImage(Image.open(BytesIO(img_data)))
    #root.update_idletasks()
    #
    #root.after(50, open_img)
    #img_url = base_url + "/jpgimage/1/image.jpg"
    #response = requests.get(img_url, stream=True, timeout=3)
    #img_data = response.content
    #response.decode_content = True
    #print(response.status_code)
    #with BytesIO() as fdata:
    #    for block in response.iter_content(1024):
    #        fdata.write(block)
    #    img_obj = Image.open(fdata)
    #    #img_obj = img_obj.resize((640, 480), Image.ANTIALIAS)
    #    img = ImageTk.PhotoImage(img_obj)
    #    label1.image = img
    #    label1.configure(image = img)
    #root.update_idletasks()
    #root.after(100, open_img())


def ir_command(cmd):
    cmd_url = base_url + "/form/IRset"
    cmd_data = {"IRmode": 1,
                "c2bwthr": 20,
                "bw2cthr": 70,
                "IRenable": cmd,
                "IRdelay": 3
    }
    requests.post(cmd_url, data=cmd_data)
    
    
def move_command(cmd):
    cmd_url = base_url + "/form/setPTZCfg"
    cmd_data = {'command': cmd,
		'ZFSpeed': 8,
		'PTSpeed': 8,
		'panSpeed': 8,
		'tiltSpeed': 8,
		'focusSpeed': 8,
		'zoomSpeed': 8
    }
    requests.post(cmd_url, data=cmd_data)
    cmd_data['command'] = 0
    sleep(0.3)
    requests.post(cmd_url, data=cmd_data)

def preset_command(preset_num, cmd):
    cmd_url = base_url + '/form/presetSet'
    num = preset_num.get()
    try:
        num = int(num)
    except:
        return
    if num == 1:
        cmd_data = { 'flag': cmd,
                     'existFlag': 0,
                     'language': 'cn',
                     'presetNum': 0
        }
    else:
        cmd_data = { 'flag': cmd,
                     'existFlag': 1,
                     'language': 'cn',
                     'presetNum': num-1
        }
    requests.post(cmd_url, data=cmd_data)





    
def startui():
    ### CAM SETUP ###
    print("CAM setup start")
    #mycam = ONVIFCamera(CAM_URL, CAM_PORT, CAM_ADMIN, CAM_PASS, CAM_WSDL)
    mycam = ONVIFCamera('testapi.me', 7089, 'admin', '123456', 'venv/lib/python3.8/site-packages/wsdl')
    media = mycam.create_media_service()
    ptz = mycam.create_ptz_service()
    media_profile = media.GetProfiles()[0];
    request = ptz.create_type('GetConfigurationOptions')
    request.ConfigurationToken = media_profile.PTZConfiguration.token
    ptz_configuration_options = ptz.GetConfigurationOptions(request)
    
    ptz_status = ptz.GetStatus({'ProfileToken': media_profile.token})
    req = ptz.create_type('ContinuousMove')
    req.ProfileToken = media_profile.token
 
    # Get range of pan and tilt
    # NOTE: X and Y are velocity vector
    global XMAX, XMIN, YMAX, YMIN
    XMAX = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].XRange.Max
    XMIN = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].XRange.Min
    YMAX = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].YRange.Max
    YMIN = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].YRange.Min
    print("CAM setup end")
    ### CAM SETUP ###
    
    root = tkinter.Tk()
    label1 = tkinter.Label(root, text = "")
    label1.grid(row=0, column=0, columnspan=6, sticky=W+E+N+S, padx=5, pady=5)#pack()

    b_zoomin = tkinter.Button(root, text = "zoom in", command = lambda: move_zoom(ptz, req, ptz_status, 3))
    b_zoomout = tkinter.Button(root, text = "zoom out", command = lambda: move_zoom(ptz, req, ptz_status, -3))

    b_up = tkinter.Button(root, text = "up", command = lambda: move_up(ptz, req, ptz_status))
    b_down = tkinter.Button(root, text = "down", command = lambda: move_down(ptz, req, ptz_status))
    b_left = tkinter.Button(root, text = "left", command = lambda: move_left(ptz, req, ptz_status))
    b_right = tkinter.Button(root, text = "right", command = lambda: move_right(ptz, req, ptz_status))

    b_zoomin.grid(row=1, column=0, sticky=W+E)
    b_zoomout.grid(row=1, column=1, sticky=W+E)
    b_up.grid(row=1, column=2, sticky=W+E)
    b_down.grid(row=1, column=3, sticky=W+E)
    b_left.grid(row=1, column=4, sticky=W+E)
    b_right.grid(row=1, column=5, sticky=W+E)

    preset_label = Label(root, text="preset")
    preset_label.grid(row=2, column=0, sticky=W+E)
    preset_num = Entry(root)
    preset_num.grid(row=2, column=1, sticky=W+E)

    b_set = tkinter.Button(root, text = "set", command = lambda: ptz_preset_set(ptz, media_profile.token, preset_num))
    b_call = tkinter.Button(root, text = "call", command = lambda: ptz_preset_call(ptz, media_profile.token, preset_num))

    b_set.grid(row=2, column=2, sticky=W+E)
    b_call.grid(row=2, column=3, sticky=W+E)

    b_l_on = tkinter.Button(root, text = "IR on", command = lambda: ir_command(1))
    b_l_off = tkinter.Button(root, text = "IR off", command = lambda: ir_command(0))
    b_l_on.grid(row=2, column=4, sticky=W+E)
    b_l_off.grid(row=2, column=5, sticky=W+E)


    host_label = Label(root, text="camera URL")
    host_label.grid(row=3, column=0, sticky=W+E)
    entryText = tkinter.StringVar()
    entry = tkinter.Entry(root, textvariable=entryText)
    entryText.set(base_url)
    entry.grid(row=3, column=1, columnspan = 5, sticky=W+E)
    entry.bind("<Return>", on_change)

    #open_img()
    
    root.mainloop()

if __name__ == "__main__":
    startui()
    
