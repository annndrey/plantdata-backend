from onvif import ONVIFCamera
mycam = ONVIFCamera('192.168.1.78', 80, 'admin', '123456', './.local/lib/python3.8/site-packages/wsdl')
media = mycam.create_media_service()
media_profile = media.GetProfiles()[0]
media_profile.token
ptz = mycam.create_ptz_service()
obj_stream = media.create_type('GetStreamUri')
obj_img = media.create_type('GetSnapshotUri')
obj_img.ProfileToken = media_profile.token
obj_stream.ProfileToken = media_profile.token
obj_stream.StreamSetup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
print(media.GetStreamUri(obj_stream))
print(media.GetSnapshotUri(obj_img))
