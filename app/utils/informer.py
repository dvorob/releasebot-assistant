#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Методы информинга. Отправляют сообщения в Informer-а (отдельный модуль)
"""
from utils import logging
import requests
import config
import json

logger = logging.setup()

def inform_duty(areas: list, message: str):
    """
        (areas=['ADMSYS(биллинг)', 'ADMSYS(портал)'], message='Алярма! Сайт упал!')
        Отправить сообщение дежурным. AREAS - зоны ответственности. Соответствуют тем, что выдает команда /duty в Телеграмме.
        Хранятся в таблице Duty_list
    """
    logger.info('-- INFORM DUTY %s %s', areas, message)
    try:
        data = {'areas': areas, 'message': message}
        resp = requests.post(config.informer_inform_duty_url, data=json.dumps(data))
        if resp.ok:
            logger.info('Successfully inform duty %s %s ', areas, resp)
        else:
            logger.error('Error in inform duty %s %s ', areas, resp)
    except Exception as e:
        logger.exception('Exception in inform duty %s', str(e))


def send_message_to_users(accounts: list, message: str, disable_notification: bool = True):
    """
        (accounts=['ymvorobevda', ...], message="Hi!", disable_notification=True)
        Отправить сообщение в Informer в формате {'accounts': ['ymvorobevda'], 'text': 'Работает!', disable_notification=True}
        disable_notification=True - телега пришлет сообщение без звукового сигнала
    """
    logger.info('-- SEND MESSAGE TO USER %s %s', accounts, message)
    try:
        data = {'accounts': accounts, 'text': message}
        resp = requests.post(config.informer_send_message_url, data=json.dumps(data))
        logger.info('Sent message to %s %s response=%s', accounts, message, resp)
    except Exception as e:
        logger.exception('Exception in send message %s', str(e))


def inform_subscribers(notification: str, message: str):
    """
        (notification='all', message='Aloha')
        Отправить сообщение в Informer для всех, кто подписан на уведомления.
        Посмотреть типы подписки можно командой /who username в телеграмме, либо в БД ксеркса (Users.notifications)
    """
    logger.info('-- INFORM SUBSCRIBERS %s %s', notification, message)
    try:
        data = {'notification': notification, 'text': message}
        resp = requests.post(config.inform_subscribers_url, data=json.dumps(data))
        logger.info('Inform to subscribers %s %s response=%s', notification, message, resp)
    except Exception as e:
        logger.exception('Exception in inform to subscribers %s', str(e))


def send_timetable_to_users(accounts: list):
    """
        (accounts=['ymvorobevda', ...])
    """
    logger.info('-- SEND TIMETABLE TO USER %s ', accounts)
    try:
        data = {'accounts': accounts}
        resp = requests.post(config.informer_send_message_url, data=json.dumps(data))
        logger.info('Sent timetable to %s response=%s', accounts, resp)
    except Exception as e:
        logger.exception('Exception in send timetable to users %s', str(e))