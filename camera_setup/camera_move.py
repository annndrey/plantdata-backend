from time import sleep

from onvif import ONVIFCamera

XMAX = 1
XMIN = -1
YMAX = 1
YMIN = -1

def perform_move(ptz, request, timeout):
    # Start continuous move
    print(request)
    ptz.ContinuousMove(request)
    # Wait a certain time
    sleep(timeout)
    request.PanTilt = 1
    # Stop continuous move
    ptz.Stop({'ProfileToken': request.ProfileToken})
    
def move_up(ptz, request, timeout=2):
    print('move up...')
    request.Velocity.PanTilt._x = 0
    request.Velocity.PanTilt._y = YMAX
    perform_move(ptz, request, timeout)
 
def move_down(ptz, request, timeout=2):
    print('move down...')
    request.Velocity.PanTilt._x = 0
    request.Velocity.PanTilt._y = YMIN
    perform_move(ptz, request, timeout)
 
def move_right(ptz, request, ptz_status, timeout=2):
    print('move right...', request)
    ptz_status.Position.PanTilt.x = XMAX
    ptz_status.Position.PanTilt.y = 0
    request.Velocity = ptz_status.Position
    
    perform_move(ptz, request, timeout)
 
def move_left(ptz, request, ptz_status, timeout=2):
    print('move left...')
    ptz_status.Position.PanTilt.x = XMIN
    ptz_status.Position.PanTilt.y = 0
    request.Velocity = ptz_status.Position
    perform_move(ptz, request, timeout)

def move_zoom(ptz, request, ptz_status, timeout=2):
    print('move left...')
    #ptz_status.Position.PanTilt.x = XMIN
    #ptz_status.Position.PanTilt.y = 0
    ptz_status.Position.Zoom.x = -20
    request.Velocity = ptz_status.Position
    perform_move(ptz, request, timeout)

    
def continuous_move():
    mycam = ONVIFCamera('testapi.me', 7089, 'admin', '123456', 'venv/lib/python3.8/site-packages/wsdl')
    # Create media service object
    media = mycam.create_media_service()
    # Create ptz service object
    ptz = mycam.create_ptz_service()
 
    # Get target profile
    media_profile = media.GetProfiles()[0];
    #print(media_profile)
 
    # Get PTZ configuration options for getting continuous move range
    request = ptz.create_type('GetConfigurationOptions')
    request.ConfigurationToken = media_profile.PTZConfiguration.token
    ptz_configuration_options = ptz.GetConfigurationOptions(request)
    
    ptz_status = ptz.GetStatus({'ProfileToken': media_profile.token})
    request = ptz.create_type('ContinuousMove')
    request.ProfileToken = media_profile.token
 
    # ptz.Stop({'ProfileToken': media_profile._token})
 
    # Get range of pan and tilt
    # NOTE: X and Y are velocity vector
    global XMAX, XMIN, YMAX, YMIN
    XMAX = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].XRange.Max
    XMIN = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].XRange.Min
    YMAX = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].YRange.Max
    YMIN = ptz_configuration_options.Spaces.ContinuousPanTiltVelocitySpace[0].YRange.Min
 
    # move right
    #move_right(ptz, request, ptz_status)
 
    # move left
    #move_left(ptz, request, ptz_status)
    move_zoom(ptz, request, ptz_status)
    # Move up
    #move_up(ptz, request)
 
    # move down
    #move_down(ptz, request)
 
if __name__ == '__main__':
  continuous_move()
