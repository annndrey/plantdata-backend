DEBUG = True
DEVELOPMENT = True
SECRET_KEY='secretkey'
SQLALCHEMY_DATABASE_URI='mysql+pymysql://user:password@host/database'
SQLALCHEMY_TRACK_MODIFICATIONS = False
FILE_PATH = "/path/to/store/pictures"
CF_LOGIN = "user@site.com"
CF_PASSWORD = "userpass"
CF_HOST = "https://cityfarmer.fermata.tech:5444/api/v1/{}"
CLASSIFY_ZONES = True
FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONTSIZE = 50
TEMPDIR = "/path/to/temp/dir"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 3
CACHE_DB = 4
API_VERSION = 2