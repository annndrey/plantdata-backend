FROM python:3.6

ARG APP_USER=gitlab-runner
RUN useradd --user-group --create-home --shell /bin/false ${APP_USER}
USER ${APP_USER}

COPY requirements.txt /tmp/requirements.txt
RUN pip install -U pip
RUN pip install -r /tmp/requirements.txt

WORKDIR /app
EXPOSE 8000 9988
CMD /bin/bash /app/entrypoint.sh
#CMD ls -latr /data