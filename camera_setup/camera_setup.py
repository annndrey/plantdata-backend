#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from tkinter import *
import tkinter
import requests
from PIL import Image, ImageTk
from io import BytesIO
import time

# base_url = "http://admin:plantdata@c56352d9.eu.ngrok.io"
# base_url = "http://admin:plantdata@192.168.0.201"
# base_url = "http://admin:plantdata@192.168.0.202"
base_url = "http://admin:plantdata@e3fd6634.eu.ngrok.io"

def open_img():
    #img_url = "https://placeimg.com/640/480/any"
    img_url = base_url + "/jpgimage/1/image.jpg"
    response = requests.get(img_url)
    img_data = response.content
    img = ImageTk.PhotoImage(Image.open(BytesIO(img_data)))
    label1.image = img
    label1.configure(image = img)
    root.update_idletasks()
    root.after(500, open_img)

    
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
    time.sleep(0.5)
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

open_img()

root.mainloop()
