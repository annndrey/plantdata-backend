FROM python:3.8

COPY requirements.txt /tmp/requirements.txt
RUN pip install -U pip
RUN pip install -r /tmp/requirements.txt

WORKDIR /app
EXPOSE 8000 9988
CMD /bin/bash /app/entrypoint.sh
#CMD ls -latr /data