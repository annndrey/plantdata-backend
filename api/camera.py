#!/usr/bin/env python
# -*- coding: utf-8 -*-

#from picamera import PiCamera
#from time import sleep
#from ecapture import ecapture as ec

#ec.capture(0,False,"img0.jpg")
#ec.capture(1,False,"img1.jpg")


#print("Waiting for camera")
#camera = PiCamera()
#camera.resolution = (2592, 1944)
#camera.start_preview()
#sleep(3)
#camera.capture('image.jpg')
#print("Get image")
#camera.stop_preview()
#camera.close()
#print("camera closed")

# 0. CV_CAP_PROP_POS_MSEC Current position of the video file in milliseconds.
# 1. CV_CAP_PROP_POS_FRAMES 0-based index of the frame to be decoded/captured next.
# 2. CV_CAP_PROP_POS_AVI_RATIO Relative position of the video file
# 3. CV_CAP_PROP_FRAME_WIDTH Width of the frames in the video stream.
# 4. CV_CAP_PROP_FRAME_HEIGHT Height of the frames in the video stream.
# 5. CV_CAP_PROP_FPS Frame rate.
# 6. CV_CAP_PROP_FOURCC 4-character code of codec.
# 7. CV_CAP_PROP_FRAME_COUNT Number of frames in the video file.
# 8. CV_CAP_PROP_FORMAT Format of the Mat objects returned by retrieve() .
# 9. CV_CAP_PROP_MODE Backend-specific value indicating the current capture mode.
# 10. CV_CAP_PROP_BRIGHTNESS Brightness of the image (only for cameras).
# 11. CV_CAP_PROP_CONTRAST Contrast of the image (only for cameras).
# 12. CV_CAP_PROP_SATURATION Saturation of the image (only for cameras).
# 13. CV_CAP_PROP_HUE Hue of the image (only for cameras).
# 14. CV_CAP_PROP_GAIN Gain of the image (only for cameras).
# 15. CV_CAP_PROP_EXPOSURE Exposure (only for cameras).
# 16. CV_CAP_PROP_CONVERT_RGB Boolean flags indicating whether images should be converted to RGB.
# 17. CV_CAP_PROP_WHITE_BALANCE Currently unsupported
# 18. CV_CAP_PROP_RECTIFICATION Rectification flag for stereo cameras (note: only supported by DC1394 v 2.x backend currently)

import cv2
import time

v0 = cv2.VideoCapture(0)
v0.set(3,1280)
v0.set(4,960)

v1 = cv2.VideoCapture(1)
v1.set(3,1280)
v1.set(4,960)

for i in range(15):
    check, frame = v0.read()
    time.sleep(1)
    print(0,i)
    
showPic = cv2.imwrite("img0.jpg",frame)
v0.release()
for i in range(15):
    check, frame = v1.read()
    time.sleep(1)
    print(1,i)

showPic = cv2.imwrite("img1.jpg",frame)
v1.release()
