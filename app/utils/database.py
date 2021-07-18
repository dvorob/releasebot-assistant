#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-
"""
Работа с БД в PostgreSQL
"""
# External
import json
from datetime import datetime
from peewee import *
# Internal
import config
import re
from utils import logging

logger = logging.setup()

__all__ = ['PostgresPool']

class BaseModel(Model):
    class Meta:
        database = config.postgres

class App_List(BaseModel):
    id = IntegerField(primary_key=True)
    app_name = CharField(unique=True)
    perimeter = CharField(default=None)
    release_mode = CharField(default=None)
    admins_team = CharField(default=None)
    queues = TextField(default=None)
    bot_enabled = BooleanField(default=None)
    dev_team = CharField(default=None)

class Chats(BaseModel):
    id = IntegerField()
    tg_id = CharField()
    title = CharField()
    started_by = CharField()
    date_start = TimestampField(default=datetime.now)
    notification = CharField(default='none')
    description = CharField()

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

class Option(BaseModel):
    name = CharField(unique=True)
    value = CharField()

class Parameters(BaseModel):
    id = IntegerField(index=True)
    name = CharField()
    value = CharField()
    description = CharField()

class Releases_List(BaseModel):
    id = IntegerField(primary_key=True)
    jira_task = CharField(unique=True)
    app_name = CharField(default=None)
    app_version = CharField(default=None)
    fullname = CharField(default=None)
    date_create = DateField(default=None)
    date_update = DateField(default=None)
    resolution = CharField(default=None)
    is_rollbacked = BooleanField(default=None)
    is_static_released = BooleanField(default=None)
    notifications_sent = TextField(default=None)

class Users(BaseModel):
    id = IntegerField(primary_key=True)
    account_name = CharField(unique=True)
    full_name = CharField()
    tg_login = CharField()
    tg_id = CharField()
    working_status = CharField()
    email = CharField()
    notification = CharField(default='none')
    admin = IntegerField(default=0)
    date_update = DateField(default=None)

class Workdays_List(BaseModel):
    ddate = DateField(primary_key=True)
    is_workday = IntegerField()

class User_Subscriptions(BaseModel):
    account_name = CharField()
    subscription = CharField()

class PostgresPool:

    def __init__(self):
        self.db = config.postgres

    # ---------------------------------
    # ----- AppList -------------------

    def get_application_metainfo(self, app_name) -> list:
        # Сходить в AppList и получить конфигурацию деплоя конкретного приложения - очереди, режим выкладки и прочее
        logger.debug('get application metainfo %s ', app_name)
        try:
            self.db.connect(reuse_if_open=True)
            result = []
            db_query = App_List.select().where(App_List.app_name == app_name)
            for v in db_query:
                result = vars(v)['__data__']
            return result
        except Exception as e:
            logger.exception('exception in get application metainfo %s', e)
        finally:
            self.db.close()

    def set_application_bot_enabled(self, app_name, value) -> list:
        # Выставить значение в конкретном поле bot_enabled
        # ('shiro', 'bot_enabled', False)
        logger.debug('set application bot enabled %s %s', app_name, value)
        try:
            self.db.connect(reuse_if_open=True)
            result = (App_List
                     .update(bot_enabled = value)
                     .where(App_List.app_name == app_name))
            result.execute()
        except Exception as e:
            logger.exception('exception in set application bot enabled %s', e)
            return result
        finally:
            self.db.close()

    def set_application_dev_team(self, app_name, value) -> list:
        # Выставить значение в конкретном поле dev_team
        # ('shiro', 'dev_team', 'PORTAL')
        try:
            self.db.connect(reuse_if_open=True)
            result = (App_List
                     .update(dev_team = value)
                     .where(App_List.app_name == app_name))
            result.execute()
        except Exception as e:
            logger.exception('exception in set application dev team %s', e)
            return result
        finally:
            self.db.close()

    # ---------------------------------
    # ----- Users ---------------------

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
            full_name = re.split(' ', value.replace('ё', 'е'))
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

    def set_users(self, account_name, tg_login, working_status, email):
        # Записать пользователя в таблицу Users. Переберет параметры и запишет только те из них, что заданы. 
        # Иными словами, если вычитали пользователя из AD с полным набором полей, запись будет создана, поля заполнены.
        # Если передадим tg_id для существующего пользователя, заполнится только это поле
        logger.debug('set users started for %s ', account_name)
        try:
            logger.info(f'{account_name}, {tg_login}, {working_status}, {email}')
            self.db.connect(reuse_if_open=True)
            db_users, _ = Users.get_or_create(account_name=account_name)
            # if full_name:
            #     db_users.full_name = full_name.replace('ё', 'е')
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

    # ---------------------------------
    # ----- Parameters ----------------

    def get_parameters(self, name) -> list:
        # Сходить в parameters
        logger.debug('get parameters %s ', name)
        try:
            self.db.connect(reuse_if_open=True)
            result = []
            db_query = Parameters.select().where(Parameters.name == name)
            for v in db_query:
                result.append((vars(v))['__data__'])
            logger.debug('get parameters for %s %s', name, result)
            return result
        except Exception as e:
            logger.exception('exception in get parameters %s', e)
        finally:
            self.db.close()

    def set_parameters(self, name, value):
        # Записать в parameters
        logger.info('set parameters %s %s ', name, value)
        try:
            self.db.connect(reuse_if_open=True)
            db_rec, _ = Parameters.get_or_create(name=name)
            db_rec.value = value
            db_rec.save()
        except Exception as e:
            logger.exception('exception in set parameters %s', e)
        finally:
            self.db.close()

    # ---------------------------------
    # ----- DutyList ------------------

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

    def set_dutylist(self, dl):
        try:
            self.db.connect(reuse_if_open=True)
            db_duty, _ = Duty_List.get_or_create(duty_date=dl['duty_date'], area=dl['area'])
            db_duty.full_name = dl['full_name'].replace('ё', 'е')
            db_duty.account_name = dl['account_name']
            db_duty.full_text = dl['full_text']
            db_duty.tg_login = dl['tg_login']
            db_duty.save()
        except Exception as e:
            logger.exception('error in set dutylist %s', str(e))
        finally:
            self.db.close()
    
    # ---------------------------------
    # ----- Workdays ------------------

    def get_workday(self, ddate) -> list:
        # Сходить в workdays_list и узнать, рабочий день или нет
        logger.debug('get workday %s ', ddate)
        try:
            self.db.connect(reuse_if_open=True)
            result = []
            db_query = Workdays_List.select().where(Workdays_List.ddate == ddate)
            for v in db_query:
                result = vars(v)['__data__']
            if 'is_workday' in result:
                result = True if result['is_workday'] == 1 else False
            else:
                result = None
            return result
        except Exception as e:
            logger.exception('exception in get workday %s', e)
        finally:
            self.db.close()

    def set_workday(self, ddate, is_workday):
        # Записать в workdays_list, рабочий день или нет
        logger.info('set workday %s %s ', ddate, is_workday)
        try:
            self.db.connect(reuse_if_open=True)
            db_users, _ = Workdays_List.get_or_create(ddate=ddate)
            db_users.is_workday = is_workday
            db_users.save()
        except Exception as e:
            logger.exception('exception in set workday %s', e)
        finally:
            self.db.close()

    # ---------------------------------
    # ----- ReleasesList -------------- 

    def upsert_release(self, jira_task, app_name, app_version, fullname, date_create, date_update, resolution):
        result = []
        try:    
            self.db.connect(reuse_if_open=True)
            result = (Releases_List
                .insert(jira_task=jira_task, app_name=app_name, app_version=app_version, fullname=fullname, date_create=date_create, 
                    date_update=date_update, resolution=resolution)
                .on_conflict(
                    conflict_target=[Releases_List.jira_task],
                    preserve=[Releases_List.date_create],
                    update={Releases_List.app_name: app_name, Releases_List.app_version: app_version, Releases_List.fullname: fullname, 
                            Releases_List.date_update: date_update, Releases_List.resolution: resolution})
                .execute())
            return result
        except Exception as e:
            logger.exception('exception in upsert release %s', e)
            return result
        finally:
            self.db.close()

    def get_release_notifications_sent(self, jira_task):
        # Вернет массив, построенный из строкового поля notifications_sent. Если оно пусто, вернет массив с пустой строкой
        try:
            self.db.connect(reuse_if_open=True)
            db_result = Releases_List.select(Releases_List.notifications_sent).where(Releases_List.jira_task == jira_task)
            for r in db_result:
                if r.notifications_sent:
                    result = r.notifications_sent
                else:
                    result = ''
            return (result).split(',')
        except Exception as e:
            logger.exception('exception in get release notification sent %s', e)
            return []
        finally:
            self.db.close()

    def set_release_notifications_sent(self, jira_task, notifications_sent):
        # Обновит всю инфу в ячейке notifications_sent. Неважно, что передано в качестве значения - будет сохранено целиком
        try:
            self.db.connect(reuse_if_open=True)
            result = (Releases_List
                     .update(notifications_sent = notifications_sent)
                     .where(Releases_List.jira_task == jira_task))
            result.execute()
        except Exception as e:
            logger.exception('exception in set release notification sent %s', e)
            return result
        finally:
            self.db.close()

    def append_release_notifications_sent(self, jira_task, notifications_sent):
        # Запишет инфу про отправленную нотификацию. Важно: функция работает с записью в ячейку как будто это сет данных
        # т.е. всякое значение встречается лишь единожды, порядок при этом неважен
        try:
            self.db.connect(reuse_if_open=True)
            notif_sent = self.get_release_notifications_sent(jira_task)
            if notifications_sent in notif_sent.split(','):
                notif_sent = notif_sent + ',' + notifications_sent
            else:
                notif_sent = notifications_sent
            result = (Releases_List
                     .update(notifications_sent = notif_sent)
                     .where(Releases_List.jira_task == jira_task))
            result.execute()
        except Exception as e:
            logger.exception('exception in append release notification sent %s', e)
            return result
        finally:
            self.db.close()

    def get_last_success_app_version(self, app_name):
        # Вернет последнюю версию компоненты, успешно выехавшую на бой. Для роллбека
        try:
            result = ''
            self.db.connect(reuse_if_open=True)
            db_result = (Releases_List
                        .select(Releases_List.app_version)
                        .where(Releases_List.app_name == app_name, Releases_List.resolution == 'Выполнен')
                        .order_by(Releases_List.jira_task.desc())
                        .limit(1))
            for r in db_result:
                if r.app_version:
                    result = r.app_version
                else:
                    result = ''
            return result
        except Exception as e:
            logger.exception('exception in get last success app version %s', e)
            return result
        finally:
            self.db.close()

    def delete_user_subscription(self, account_name, subscription):
        # Выставить в users_subscription подписку пользователя
        logger.debug('delete user subscription %s %s', account_name, subscription)
        try:
            self.db.connect(reuse_if_open=True)
            query = User_Subscriptions.delete().where(
                User_Subscriptions.account_name == account_name, User_Subscriptions.subscription == subscription)
            query.execute()
        except Exception as e:
            logger.exception('exception in delete user subscription %s', e)
        finally:
            self.db.close()

    def set_user_subscription(self, account_name, subscription):
        # Выставить в users_subscription подписку пользователя
        logger.debug('set user subscription %s ', account_name)
        try:
            self.db.connect(reuse_if_open=True)
            db_rec, _ = User_Subscriptions.get_or_create(account_name=account_name, subscription=subscription)
            db_rec.save()
        except Exception as e:
            logger.exception('exception in set user subscription %s', e)
        finally:
            self.db.close()

    def get_user_subscriptions(self, account_name) -> list:
        # Вернуть все подписки конкретного пользователя
        logger.debug('get user subscriptions %s ', account_name)
        try:
            self.db.connect(reuse_if_open=True)
            result = []
            db_query = User_Subscriptions.select().where(User_Subscriptions.account_name == account_name)
            for v in db_query:
                if ((vars(v))['__data__']):
                    result.append((vars(v))['__data__']['subscription'])
            logger.debug('get user subscriptions for %s %s', account_name, result)
            return result
        except Exception as e:
            logger.exception('exception in get user subscriptions %s', e)
        finally:
            self.db.close()

    def get_all_users_with_subscription(self, subscription) -> list:
        # Вернуть список пользователей (account_name) с конкретной подпиской
        logger.debug('get all users with subscription %s ', subscription)
        try:
            self.db.connect(reuse_if_open=True)
            result = []
            db_query = User_Subscriptions.select().where(User_Subscriptions.subscription == subscription)
            for v in db_query:
                if ((vars(v))['__data__']):
                    result.append((vars(v))['__data__']['account_name'])
            logger.debug('get all users with subscription %s %s', subscription, result)
            return result
        except Exception as e:
            logger.exception('exception in get all users with subscription %s', e)
        finally:
            self.db.close()