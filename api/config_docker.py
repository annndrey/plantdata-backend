import os

DEBUG = True
DEVELOPMENT = True
SECRET_KEY='secretkeyformyapp'
SQLALCHEMY_DATABASE_URI='mysql+pymysql://plantdata:plantdatapass@192.168.1.4/plantdb'
SQLALCHEMY_TRACK_MODIFICATIONS = False
FILE_PATH = "/data/picts"
CF_LOGIN = "saladuser"
CF_PASSWORD = "saladpass1a1"
CF_HOST = "https://salad.fermata.tech/{}"
CLASSIFY_ZONES = True
FONT = "/data/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONTSIZE = 50
TEMPDIR = "/tmp"
REDIS_HOST = os.environ.get('HOST_ADDR', '')
REDIS_PORT = 6379
REDIS_DB = 3
CACHE_DB = 4
API_VERSION = 1
SEND_EMAILS = True

