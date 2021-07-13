FROM python:3.9.1-slim

WORKDIR /opt

COPY requirements.txt ./

RUN pip3 install --no-cache-dir --trusted-host nexus.yamoney.ru -i https://nexus.yamoney.ru/repository/pypi-proxy-pypi.org/simple \
    -r requirements.txt && rm /etc/localtime /etc/apt/sources.list && ln -s /usr/share/zoneinfo/Europe/Moscow /etc/localtime

COPY app ./app

CMD [ "python3", "./app/assistant.py"]