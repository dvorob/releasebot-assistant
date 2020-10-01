#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-
"""
Input/output for mysql
"""
from datetime import datetime
from app.utils import logging
import app.config as config
from peewee import *
from playhouse.pool import PooledMySQLDatabase

logger = logging.setup()

__all__ = ['MysqlPool']

class BaseModel(Model):
    class Meta:
        database = PooledMySQLDatabase(
            config.db_name,
            host=config.db_host,
            user=config.db_user,
            passwd=config.db_pass,
            max_connections=8,
            stale_timeout=300)

class Users(BaseModel):
    id = IntegerField()
    account_name = CharField(unique=True)
    full_name = CharField()
    tg_login = CharField()
    tg_id = CharField()
    working_status = CharField()
    email = CharField()
    notification = CharField(default='none')
    admin = IntegerField(default=0)
    date_update = DateTimeField()

class Duty_List(BaseModel):
    id = IntegerField()
    duty_date = DateField(index=True)
    area = CharField()
    full_name = CharField()
    account_name = CharField()
    full_text = CharField()
    tg_login = CharField()

    class Meta:
        indexes = (
            (('duty_list', 'area'), True)
        )

class MysqlPool:
    def __init__(self):
        self.db = config_mysql

    def set_users(self, account_name, full_name, tg_login, working_status, email):
        # Записать пользователя в таблицу Users. Переберет параметры и запишет только те из них, что заданы. 
        # Иными словами, если вычитали пользователя из AD с полным набором полей, запись будет создана, поля заполнены.
        # Если передадим tg_id для существующего пользователя, заполнится только это поле
        logger.debug('set users started for %s ', account_name)
        try:
            self.db.connect(reuse_if_open=True)
            db_users, _ = Users.get_or_create(account_name=account_name)
            if full_name:
                db_users.full_name = full_name
            if tg_login:
                db_users.tg_login = tg_login
            if working_status:
                db_users.working_status = working_status
            if email:
                db_users.email = email
            db_users.date_update = datetime.now()
            db_users.save()
        except Exception as e:
            logger.exception('exception in set_users %s', str(e))
        finally:
            self.db.close()


    def set_dutylist(self, dl):
        try:
            self.db.connect(reuse_if_open=True)
            db_duty, _ = Duty_List.get_or_create(duty_date=dl['duty_date'], area=dl['area'])
            db_duty.full_name = dl['full_name']
            db_duty.account_name = dl['account_name']
            db_duty.full_text = dl['full_text']
            db_duty.tg_login = dl['tg_login']
            db_duty.save()
        except Exception as e:
            logger.exception('error in set dutylist %s', str(e))
        finally:
            self.db.close()

    def get_duty_in_area(self, duty_date, area) -> list:
        # Сходить в таблицу xerxes.duty_list за дежурными на заданную дату и зону ответственности
        try:
            self.db.connect(reuse_if_open=True)
            result = []
            db_query = Duty_List.select().where(Duty_List.duty_date == duty_date, Duty_List.area == area)
            for v in db_query:
                result.append((vars(v))['__data__'])
            logger.info('get duty for %s %s %s', duty_date, area, result)
            return result
        except Exception as e:
            logger.exception('exception in db get duty in area %s', str(e))
        finally:
            self.db.close()

    def get_users(self, field, value, operation) -> list:
        # сходить в таблицу Users и найти записи по заданному полю с заданным значением. Вернет массив словарей.
        # например, найти Воробьева можно запросом db_get_users('account_name', 'ymvorobevda')
        # всех админов - запросом db_get_users('admin', 1)
        logger.info('db_get_users param1 param2 %s %s', field, value)
        result = []
        try:
            self.db.connect(reuse_if_open=True)
            if operation == 'equal':
                db_users = Users.select().where(getattr(Users, field) == value)
            elif operation == 'like':
                db_users = Users.select().where(getattr(Users, field) % value)
            else:
                db_users = []
            for v in db_users:
                result.append((vars(v))['__data__'])
            return result
        except Exception:
            logger.exception('exception in db get users')
            return result
        finally:
            self.db.close()


    def get_user_by_fullname(self, value) -> list:
        # сходить в таблицу Users и найти записи по заданному полю с заданным значением. Вернет массив словарей.
        # например, найти Воробьева можно запросом db_get_users('account_name', 'ymvorobevda')
        # всех админов - запросом db_get_users('admin', 1)
        result = []
        try:
            self.db.connect(reuse_if_open=True)
            full_name = re.split(' ', value)
            if len(full_name) > 1:
                db_users = Users.select().where(
                    (Users.full_name.startswith(full_name[0]) & Users.full_name.endswith(full_name[1])) |
                    (Users.full_name.startswith(full_name[1]) & Users.full_name.endswith(full_name[0])))
            elif len(full_name) == 1:
                db_users = Users.select().where(Users.full_name.endswith(full_name[0]))
            else:
                db_users = ['Nobody']
            for v in db_users:
                result.append((vars(v))['__data__'])
            return result
        except Exception as e:
            logger.exception('exception in get user by fullname %s', str(e))
            return result
        finally:
            self.db.close()