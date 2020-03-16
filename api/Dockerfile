FROM python:3.6
RUN apt-get -y  update && apt-get -y install tzdata mariadb-client
ENV TZ Europe/Moscow

COPY requirements.txt /tmp/requirements.txt
RUN pip install -U pip
RUN pip install -r /tmp/requirements.txt

WORKDIR /app
#EXPOSE 8000 9988
CMD /bin/bash /app/entrypoint.sh
