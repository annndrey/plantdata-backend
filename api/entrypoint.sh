#!/bin/bash

# Wait for database
chmod +x wait-for-it && ./wait-for-it database:3306

# Prepare and start webserver
rm -r migrations
flask db init
flask db migrate
flask db upgrade
uwsgi --ini uwsgi-docker.ini --socket :8000 --protocol=http 
