import os

DBUSER = os.environ.get('DBUSER', '')
DBPASS = os.environ.get('DBPASS', '')
DBNAME = os.environ.get('DBNAME', '')
HOST = os.environ.get('HOST_ADDR', '')

MAILUSER = os.environ.get('MAILUSER', '')
MAILPASS = os.environ.get('MAILPASS', '')

DEBUG = True
DEVELOPMENT = True
SECRET_KEY='secretkeyformyapp'
SQLALCHEMY_DATABASE_URI=f'mysql+pymysql://{DBUSER}:{DBPASS}@{HOST}/{DBNAME}'
SQLALCHEMY_TRACK_MODIFICATIONS = False
FILE_PATH = "/data/picts"
CF_LOGIN = "user"
CF_PASSWORD = "pass"
CF_HOST = "https://host/{}"
CLASSIFY_ZONES = True
FONT = "/data/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONTSIZE = 50
TEMPDIR = "/tmp"
REDIS_HOST = os.environ.get('REDIS_HOST', '')
REDIS_PORT = 6379
REDIS_DB = 3
CACHE_DB = 4
API_VERSION = 1
SEND_EMAILS = True

