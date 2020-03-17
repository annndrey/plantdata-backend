#!/bin/bash


# Wait for database
# chmod +x wait-for-it && ./wait-for-it database:3306
# Prepare and start webserver
rm -r migrations
export PYTHONDONTWRITEBYTECODE=1
mysql -u $DBUSER -h $HOST_ADDR -p$DBPASS -e "DROP TABLE alembic_version" $DBNAME
flask db init
flask db migrate
#export PYTHONPYCACHEPREFIX="/tmp/.cache/cpython/"
flask db upgrade
#ls /data
date
uwsgi --ini uwsgi-docker.ini --socket :8000 --protocol=http 
