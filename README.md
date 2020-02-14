# plantdata-backend

The Plantdata API

To use the service, first get the auth token,

```
POST https://dev.plantdata.fermata.tech:5598/api/v2/token

{"username":"user@site.com", "password":"userpassword"}
```

Then add header `'Authorization': 'Bearer Replace-With-Auth-Token'` to every request

## deploy

Prerequisites: Python3, MySQL

```
python3 -m venv /path/to/new/virtual/environment
source /path/to/new/virtual/environment/bin/activate

pip3 install -p requirements.txt
```

Then create a database:

```
mysql -u your_user -p

> CREATE DATABASE DBNAME;
> GRANT ALL PRIVILEGES TO your_user;
> FLUSH PRIVILEGES

```


Update the config_dev.py file with the new DB settings

Set env vars,

```
export FLASK_APP=/path/to/the/api/file.py
export APPSETTINGS=/path/to/the/config/file.py

```

Create DB tables

```
flask db init
flask db migrate
flask db upgrade
```

Now start the app with the uwsgi

```
uwsgi --ini uwsgi.ini
```