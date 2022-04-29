FROM docker.nexus.yooteam.ru/yamoney/ubuntu-20-04-ym:1.0.3

WORKDIR /opt

COPY requirements.txt ./

RUN apt-get update -y && apt-get -fy install ca-certificates gcc libffi-dev openssl libpq-dev \
    python3.9 \
    python3-stdeb \
    python3-all \
    python3-dev \
    python3-pip \
    && apt-get -y autoremove \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Layer to install pip packages
RUN mkdir -p /root/.pip && \
    pip3 install --no-cache-dir --trusted-host nexus.yooteam.ru -i https://nexus.yooteam.ru/repository/pypi-proxy-pypi.org/simple --upgrade \
    -r requirements.txt && rm /etc/localtime /etc/apt/sources.list && ln -s /usr/share/zoneinfo/Europe/Moscow /etc/localtime

ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY app ./app

CMD [ "python3", "./app/assistant.py"]