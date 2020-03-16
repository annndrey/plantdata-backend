#!/bin/bash

# Wait for database
# chmod +x wait-for-it && ./wait-for-it database:3306
# Prepare and start webserver
#rm -r migrations
#flask db init
#flask db migrate
#export PYTHONPYCACHEPREFIX="/tmp/.cache/cpython/"
export PYTHONDONTWRITEBYTECODE=1
flask db upgrade
ls /data
date
uwsgi --ini uwsgi-docker.ini --socket :8000 --protocol=http 
