FROM python:3.7.4-slim

WORKDIR /opt

COPY requirements.txt ./

RUN pip3 install --no-cache-dir --trusted-host nexus.yamoney.ru -i https://nexus.yamoney.ru/repository/pypi-proxy-pypi.org/simple \
    -r requirements.txt && rm /etc/localtime /etc/apt/sources.list && ln -s /usr/share/zoneinfo/Europe/Moscow /etc/localtime

COPY app ./app
COPY app/assistant.py ./

CMD [ "python3", "./assistant.py"]