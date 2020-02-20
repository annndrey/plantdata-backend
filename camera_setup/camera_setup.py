#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from tkinter import *
import tkinter
import requests
from PIL import Image, ImageTk
from io import BytesIO
import time
from threading import Thread
import cv2

base_url = "http://admin:plantdata@cf-fungi-cam1.ngrok.io"

def on_change(e):
    print(e)
    global base_url
    base_url = e.widget.get()
    #open_img(url)

        
def open_img():
    global base_url
    img_url = base_url + "/jpgimage/1/image.jpg"
    cap = cv2.VideoCapture(img_url)
    _, frame = cap.read()
    #frame = cv2.flip(frame, 1)
    cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
    img = Image.fromarray(cv2image)
    imgtk = ImageTk.PhotoImage(image=img)
    
    label1.image = imgtk
    label1.configure(image = imgtk)
    label1.after(50, open_img)
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
    time.sleep(0.3)
    requests.post(cmd_url, data=cmd_data)

def preset_command(preset_num, cmd):
    cmd_url = base_url + '/form/presetSet'
    num = preset_num.get()
    try:
        num = int(num)
    except:
        return
    cmd_data = { 'flag': cmd,
                 'existFlag': 1,
                 'language': 'cn',
                 'presetNum': num
    }
    
    requests.post(cmd_url, data=cmd_data)
  
    
root = tkinter.Tk()
label1 = tkinter.Label(root, text = "")
label1.grid(row=0, column=0, columnspan=6, sticky=W+E+N+S, padx=5, pady=5)#pack()

b_zoomin = tkinter.Button(root, text = "zoom in", command = lambda: move_command(13))
b_zoomout = tkinter.Button(root, text = "zoom out", command = lambda: move_command(14))

b_up = tkinter.Button(root, text = "up", command = lambda: move_command(1))
b_down = tkinter.Button(root, text = "down", command = lambda: move_command(2))
b_left = tkinter.Button(root, text = "left", command = lambda: move_command(3))
b_right = tkinter.Button(root, text = "right", command = lambda: move_command(4))


b_zoomin.grid(row=1, column=0, sticky=W+E)#pack()
b_zoomout.grid(row=1, column=1, sticky=W+E)#pack()
b_up.grid(row=1, column=2, sticky=W+E)#pack()
b_down.grid(row=1, column=3, sticky=W+E)#pack()
b_left.grid(row=1, column=4, sticky=W+E)#pack()
b_right.grid(row=1, column=5, sticky=W+E)#pack()

preset_label = Label(root, text="preset")
preset_label.grid(row=2, column=0, sticky=W+E)
preset_num = Entry(root)
preset_num.grid(row=2, column=1, sticky=W+E)

b_set = tkinter.Button(root, text = "set", command = lambda: preset_command(preset_num, 3))
b_call = tkinter.Button(root, text = "call", command = lambda: preset_command(preset_num, 4))

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

open_img()

root.mainloop()
