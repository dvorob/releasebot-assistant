#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""""
    Ассистент релизного бота
    запуск джоб по расписанию, статистика и прочее
"""

import logging.config
import re
import warnings
from datetime import timedelta, datetime
import requests
from playhouse.pool import PooledMySQLDatabase
from peewee import *
from apscheduler.schedulers.background import BlockingScheduler
from jira import JIRA
from exchangelib import DELEGATE, Configuration, Credentials, \
    Account
from exchangelib.ewsdatetime import UTC_NOW
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
import config
import ldap3
from ldap3 import Server, Connection, SIMPLE, SYNC, ASYNC, SUBTREE, ALL

# Отключаем предупреждения от SSL
warnings.filterwarnings('ignore')

# Настраиваем работу с Mysql. Надо бы вынести это в ручку API
__all__ = ['MysqlPool']

config_mysql = PooledMySQLDatabase(
    config.db_name,
    host=config.db_host,
    user=config.db_user,
    passwd=config.db_pass,
    max_connections=8,
    stale_timeout=300)

class BaseModel(Model):
    class Meta:
        database = config_mysql

class Users(BaseModel):
    id = IntegerField()
    account_name = CharField(unique=True)
    full_name = CharField()
    tg_login = CharField()
    working_status = CharField()
    email = CharField()
    notification = CharField(default='none')
    admin = IntegerField(default=0)

class MysqlPool:
    def __init__(self):
        self.db = config_mysql

    def db_set_users(self, account_name, full_name, tg_login, working_status, email):
        try:
            self.db.connect()
            db_users, _ = Users.get_or_create(account_name=account_name)
            db_users.full_name = full_name
            db_users.tg_login = tg_login
            db_users.working_status = working_status
            db_users.email = email
            db_users.save()
        except Exception:
            print('exception in db_set_users')
        finally:
            self.db.close()


def statistics_json(jira_con):
    """
        Considers statistics, format in json
        and set to aerospike, item=dict_day_statistics, set=statistics
        :param jira_con: parameters jira connection
        :return: nothing
    """

    today = datetime.today().strftime("%Y-%m-%d")
    returned = jira_con.search_issues(config.jira_filter_returned, maxResults=1000)
    resolved = jira_con.search_issues(config.jira_resolved_today, maxResults=1000)
    rollback = jira_con.search_issues(config.jira_rollback_today, maxResults=1000)

    msg = {today: {'count_returned_to_queue': len(returned),
                   'count_rollback': len(rollback),
                   'count_resolved': len(resolved),
                   'rollback_tasks': {issue.key: issue.fields.summary for issue in rollback},
                   'resolved_tasks': {issue.key: issue.fields.summary for issue in resolved},
                   'returned_to_queue': {issue.key: issue.fields.summary for issue in returned}
                   }
           }

    request_write_aerospike(item='dict_day_statistics', aerospike_set='statistics', bins=msg)
    logger.info('Right now i calculate statistics and set to aerospike, '
                'item=dict_day_statistics, aerospike_set=statistics')


def request_read_aerospike(item, aerospike_set):
    """
        Read from aerospike via api-v1
        :param: item - item in aerospike
        :param: aerospike_set - set in aerospike
        :return: 'Response' object - response from api-v1, a lot of methods
    """
    logger.info('request_read_aerospike started: item=%s, set=%s', item, aerospike_set)
    headers = {'item': item, 'set': aerospike_set}
    all_return_queue_task = requests.get(config.api_aerospike_read, headers=headers)
    return all_return_queue_task.json()


def request_write_aerospike(item, bins, aerospike_set):
    """
        Write to aerospike via api-v1
        :param: item - item in aerospike
        :param: aerospike_set - set in aerospike
        :return: 'Response' object - response from api-v1, a lot of methods
    """
    logger.debug('request_write_aerospike started: item=%s, set=%s, bins=%s',
                 item, aerospike_set, bins)
    # json.dumps - for request we need str, not dict
    headers = {'item': item, 'set': aerospike_set}
    all_return_queue_task = requests.post(config.api_aerospike_write, headers=headers, json=bins)
    return all_return_queue_task


def request_telegram_send(telegram_message: dict) -> bool:
    """
        Send message to telegram channel
        :param: telegram_message - dict with list of chat_id, msg and optional field type
        :return: bool value depends on api response
    """
    try:
        req_tg = requests.post(config.api_tg_send, json=telegram_message)
        if req_tg.ok:
            logger.info('Successfully sent message to tg for %s via api',
                        telegram_message['chat_id'])
            feedback = True
        else:
            logger.error('Error in request_telegram_send for %s',
                         telegram_message['chat_id'])
            feedback = False
        return feedback
    except Exception:
        logger.exception('request_telegram_send')


def calculate_statistics(jira_con):
    """
        Considers statistics, format in human readable format
        and send
        :param jira_con: parameters jira connection
        :return: nothing
    """
    dict_work_day = request_read_aerospike(item='work_day_or_not', aerospike_set='remaster')
    today = datetime.today().strftime("%Y-%m-%d")

    if dict_work_day.get(today):
        returned = jira_con.search_issues(config.jira_filter_returned, maxResults=1000)
        msg = f'\nСегодня было <strong>возвращено в очередь {len(returned)}</strong> релизов:\n'
        msg += '\n'.join([f'{issue.key} = {issue.fields.summary}' for issue in returned])

        resolved = jira_con.search_issues(config.jira_resolved_today, maxResults=1000)
        msg += f'\nСегодня было <strong>выкачено {len(resolved)}</strong> релизов:\n'
        msg += '\n'.join([f'{issue.key} = {issue.fields.summary}' for issue in resolved])

        rollback = jira_con.search_issues(config.jira_rollback_today, maxResults=1000)
        msg += f'\nСегодня было <strong>откачено {len(rollback)}</strong> релизов:\n'
        msg += '\n'.join([f'{issue.key} = {issue.fields.summary}' for issue in rollback])

        telegram_message = {'chat_id': list(config.those_who_need_send_statistics.values()),
                            'text': msg, 'type': 'html'}
        request_telegram_send(telegram_message)
        logger.info('Statistics:\n %s\n Has been sent to %s', msg,
                    config.those_who_need_send_statistics.keys())
    else:
        logger.info('No, today is a holiday, I don\'t want to count statistics')


def fill_duty_info_from_exchange(after_days=None):
    """
        Go to Exchange to AdminsOnDuty Calendar
        Get the Info about dutymen
        Fill aerospike DB
    """
    try:
        logger.info('fill_duty_info_from_exchange started!')

        msg = 'Дежурят сейчас:\n'
        delta = 0 if not after_days else int(after_days) * 24 * 60

        cal_start = UTC_NOW() + timedelta(minutes=delta)
        cal_end = UTC_NOW() + timedelta(minutes=delta + 1)

        # go to exchange for knowledge
        msg += ex_duty(cal_start, cal_end)

        logger.info('I find duty\n%s', msg)
        # Запишем всех найденных дежурных на сегодня в aerospike, чтобы
        # ручка /id дергала не exchange, а aerospike
        if not after_days:
            request_write_aerospike(item='duty',
                                    bins={str(datetime.today().strftime("%Y-%m-%d")): msg},
                                    aerospike_set='duty_admin')
    except Exception:
        logger.exception('exception in fill_duty_info_from_exchange')

def get_duty_info(after_days=None):
    """
        Find out information about duty admin and send them
        Function is called in 10.01 without parameters.
        :param after_days - using in weekend_duty function
        :return: name of duty, if after_days
    """
    try:
        logger.info('get_duty_info started!')

        msg = 'Дежурят сейчас:\n'
        delta = 0 if not after_days else int(after_days) * 24 * 60

        cal_start = UTC_NOW() + timedelta(minutes=delta)
        cal_end = UTC_NOW() + timedelta(minutes=delta + 1)

        # go to exchange for knowledge
        msg += ex_duty(cal_start, cal_end)

        logger.info('I find duty\n%s', msg)

        # Если то, что мы нашли, не пусто,то вытащим дежурного по порталу, биллингу и инфре,
        # дальше get_key словаря, в котором лежат фио_tgusername админов и вытащим
        # chat_id сегодняшних дежурных
        if len(msg):
            billing_duty_adm = re.compile(r"ADMSYS\(биллинг\)\s?-([А-Яа-я\s]+ [А-Яа-я]+)")
            infra_duty_adm = re.compile(r"ADMSYS\(инфра\)\s?-([А-Яа-я\s]+ [А-Яа-я]+)")
            portal_duty_adm = re.compile(r"ADMSYS\(портал\)\s?-([А-Яа-я\s]+ [А-Яа-я]+)")

            find_billing_duty = billing_duty_adm.search(msg)
            find_infra_duty = infra_duty_adm.search(msg)
            find_portal_duty = portal_duty_adm.search(msg)

            if after_days:
                return find_billing_duty.group(1), find_portal_duty.group(1)
            else:
                today_duty_adm_name = set()
                today_duty_adm_name.add(str(find_billing_duty.group(1)).strip('\n'))
                today_duty_adm_name.add(str(find_infra_duty.group(1)).strip('\n'))
                today_duty_adm_name.add(str(find_portal_duty.group(1)).strip('\n'))

                logger.info('По порталу сегодня дежурит %s, биллинг %s, инфра %s',
                            find_portal_duty.group(1), find_billing_duty.group(1),
                            find_infra_duty.group(1))

                fio_chat_id = request_read_aerospike(item='all_production_admin',
                                                     aerospike_set='duty_admin')
                set_chat_id = set()
                for chat_id, name in fio_chat_id.items():
                    if name in today_duty_adm_name:
                        msg = 'Крепись сестрица, ты сегодня дежуришь.' \
                            if name == 'Антонина Ким' else 'Крепись брат, ты сегодня дежуришь.'
                        telegram_message = {'chat_id': [chat_id],
                                            'text': msg}
                        request_telegram_send(telegram_message)
                        set_chat_id.add(chat_id)
                        logger.info('I sent notification to %s=%s', name, chat_id)
                # we need put in aerospike dict with type value of list (was just set):
                # '2019-09-04': ['123', '456']
                # because further, when we will response via api json, we will get mistake
                # TypeError: Object of type set is not JSON serializable,
                request_write_aerospike(item='today_duty_adm_name',
                                        bins={str(datetime.today().strftime("%Y-%m-%d")):
                                                  list(set_chat_id)},
                                        aerospike_set='duty_admin')
    except Exception:
        logger.exception('get_duty_info')


def duties_sync_from_exchange():
    """
        Ходит в Exchange и выгребает информацию о дежурствах. Помещает информацию в БД (пока aerospike).
        Все остальные методы ходят за инфой о дежурных в БД.
        Вызывается по cron-у, следовательно изменения в календаре отразятся в боте
    """
    try:
        logger.info('get_duty_info started!')

        # Go to Exchange calendar and get duites for 7 next days
        for i in range(0, 7):

            msg = 'Дежурят сейчас:\n'

            cal_start = UTC_NOW() + timedelta(i+0.5)
            cal_end = UTC_NOW() + timedelta(i+0.5)
            str_date = str((datetime.today() + timedelta(i)).strftime("%Y-%m-%d"))

            # go to exchange for knowledge
            msg += ex_duty(cal_start, cal_end)

            logger.info('I find duty for %s %s', str_date, msg)
            request_write_aerospike(item='duty',
                                    bins={str_date: msg},
                                    aerospike_set='duty_admin')
    except Exception:
        logger.exception('exception in duties_sync_from_exchange')


def notify_today_duties():
    """
        Нотификация дежурным утром
    """
    duties_chat_id = request_read_aerospike(item='today_duty_adm_name', aerospike_set='duty_admin')
    logger.info('today duties to notify %s', duties_chat_id)

    today = datetime.today().strftime("%Y-%m-%d")

    for chat_id in duties_chat_id[today]:
        msg = 'Крепись, ты сегодня дежуришь.'
        telegram_message = {'chat_id': [chat_id], 'text': msg}
        request_telegram_send(telegram_message)
        logger.info('I sent today duty notification to %s', chat_id)


def ex_connect():
    """
        Connect to exchange
        :return:
    """
    # Отключаем верификацию SLL сертификатов Exchange
    BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

    ex_cred = Credentials(config.ex_user, config.ex_pass)
    ex_cfg = Configuration(server=config.ex_host, credentials=ex_cred)
    ex_acc = Account(primary_smtp_address=config.ex_cal, config=ex_cfg,
                     access_type=DELEGATE, autodiscover=False)
    return ex_acc


def ex_duty(d_start, d_end):
    """
        Получить из календаря Exchange AdminsOnDuty информацию о дежурных.
    """
    ex_acc = ex_connect()

    result = ''

    for msg in ex_acc.calendar.view(start=d_start, end=d_end) \
            .only('start', 'end', 'subject') \
            .order_by('start', 'end', 'subject'):
        admin_on_duty = msg.subject[:150]

        if result == '':
            result = '- %s' % admin_on_duty
        else:
            result += '\n- %s' % admin_on_duty

    logger.debug('Информация о дежурных %s', result)
    return result


def app_version(full_name_app):
    """
        Получить информацию о пакете
        :param full_name_app: Заголовок задачи
        :type full_name_app: str
        :return: имя приложения
        :except если бот не смог распарсить имя app в столбце "Ожидают релиз-мастера",
                то пропустить обработку NoneType
        :rtype: 'currency-storage'
    """
    app_name = re.match('^([0-9a-z-]+)', full_name_app.strip())
    return app_name[1] if app_name else \
        logger.warning('This task %s does not fit the required format' % full_name_app)


def call_who_is_next(jira_con):
    """
        call to who_is_next
        :return:
    """
    try:
        spiky_data = request_read_aerospike(item='deploy', aerospike_set='remaster')
        logger.debug('Remaster: spiky_data = %s', spiky_data)

        if not spiky_data:
            spiky_data = {'run': 0}
            # 0 - спать, 1 - доделывать, 2 - штатный режим

        if spiky_data['run'] == 2:
            name_task_will_release_next = who_is_next(jira_con)
            if not name_task_will_release_next:
                logger.error('I can\'t find task_will_release_next')
            else:
                issues = jira_con.search_issues(config.jira_filter_true_waiting, maxResults=1000)

                for issue in issues:
                    if name_task_will_release_next in issue.fields.summary:
                        finding_issue = issue
                        logger.info('I find, this is %s', finding_issue)
                        break

                already_sent = request_read_aerospike(item='next_release',
                                                      aerospike_set='next_release')
                if bool(already_sent.get(str(finding_issue))):
                    logger.warning('Already sent notification to %s', str(finding_issue))
                else:
                    request_write_aerospike(item='next_release', bins={str(finding_issue): 1},
                                            aerospike_set='next_release')
                    # get recipients for finding_issue
                    request_chat_id_api_v1 = requests.get(
                        f'{config.api_chat_id}/{finding_issue}')
                    recipients = request_chat_id_api_v1.json()

                    logger.error('I ready sent notification about next release: %s to %s',
                                 finding_issue, recipients)
                    txt_msg_to_recipients = 'Релиз [%s](%s) будет искать согласующих ' \
                                            'в ближайшие 10-20 минут. Но это не точно.' \
                                            % (finding_issue.fields.summary, finding_issue.permalink())
                    telegram_message = {'chat_id': recipients, 'text': txt_msg_to_recipients}
                    request_telegram_send(telegram_message)
        else:
            # Если продолжать нет необходимости, просто спим
            logger.debug('sleeping')
    except Exception:
        logger.exception('call_who_is_next')


def who_is_next(jira_con):
    """
        Test write function for notificication about you release will be next
        :param jira_con:
        :return:
    """

    metaconfig_yaml = request_read_aerospike(item='deploy', aerospike_set='remaster')
    # if metaconfig_yaml['run'] == 2:
    metaconfig_yaml_apps = metaconfig_yaml['apps']

    tasks_wip = jira_con.search_issues(config.jira_filter_wip, maxResults=1000)
    true_waiting_task = jira_con.search_issues(config.jira_filter_true_waiting, maxResults=1000)
    task_full_deploy = jira_con.search_issues(config.jira_filter_full, maxResults=1000)
    task_without_waiting_full = jira_con.search_issues(config.jira_filter_without_waiting_full,
                                                       maxResults=1000)
    # add to set only if app_version will return not None
    set_wip_tasks = {app_version(in_progress_issues.fields.summary)
                     for in_progress_issues in tasks_wip
                     if app_version(in_progress_issues.fields.summary)}
    logger.info('It\'s all in progress task: %s', set_wip_tasks)

    # множество блокировок на данный момент времени для всех in_progress task
    set_wip_lock = set()
    for release_name in set_wip_tasks:
        if release_name:
            for k, v in metaconfig_yaml_apps.items():
                if release_name in k:
                    if len(v['queues']) == 1:
                        set_wip_lock.add(''.join(v['queues']))
                    else:
                        for first_lock in v['queues']:
                            set_wip_lock.add(first_lock)
    logger.info('It\'s lock on this moment for wip task: %s', set_wip_lock)

    set_full_deploy_tasks = {app_version(full_deploy_issues.fields.summary)
                             for full_deploy_issues in task_full_deploy
                             if app_version(full_deploy_issues.fields.summary)}
    logger.info('It\'s all in full deploy task: %s', set_full_deploy_tasks)

    # множество блокировок на данный момент времени для всех full_deploy task
    set_full_deploy_lock = set()
    for i in set_full_deploy_tasks:
        for k, v in metaconfig_yaml_apps.items():
            if i in k:
                if len(v['queues']) == 1:
                    set_full_deploy_lock.add(''.join(v['queues']))
                else:
                    for first_lock in v['queues']:
                        set_full_deploy_lock.add(first_lock)
    logger.info('It\'s lock on this moment for full_deploy task: %s', set_full_deploy_lock)

    set_without_waiting_full = {app_version(without_waiting_full_issues.fields.summary)
                                for without_waiting_full_issues in task_without_waiting_full
                                if app_version(without_waiting_full_issues.fields.summary)}
    logger.info('It\'s all not in full and waiting status task: %s', set_without_waiting_full)

    # множество блокировок на данный момент времени для всех
    # not in full and waiting task
    set_without_waiting_lock = set()
    for i in set_without_waiting_full:
        for k, v in metaconfig_yaml_apps.items():
            if i in k:
                if len(v['queues']) == 1:
                    set_without_waiting_lock.add(''.join(v['queues']))
                else:
                    for first_lock in v['queues']:
                        set_without_waiting_lock.add(first_lock)
    logger.info('It\'s lock on this moment for not in '
                'full, waiting task: %s', set_without_waiting_lock)

    # имена всех ожидающих освобождения очереди таски
    name_wait_app = [app_version(wait_issues.fields.summary)
                     for wait_issues in true_waiting_task]
    logger.info('Name_wait_app %s', name_wait_app)

    # для всех ожидающих освобождения очереди тасок
    # если имя таски есть в metaconfig.yaml и длина ее очереди = 1,
    # то проверим
    # нужно добавить еще логику, что очередь из ожидающих не входит в те таски,
    # что на стэйдж 2-4.
    for task in name_wait_app:
        if task:
            for k, v in metaconfig_yaml_apps.items():
                if task in k:
                    # lock for waiting bot task
                    test_set = set(v['queues'])
                    logger.debug(test_set)
                    if test_set.issubset(set_full_deploy_lock):
                        logger.info('UP! This task: %s fully include in lock '
                                    'for full_deploy task', task)
                        if not test_set.issubset(set_without_waiting_lock):
                            logger.info('!FIND! I think this is next_release: %s '
                                        'because her lock in full deploy and not in'
                                        'full and waiting task.', task)
                            return task


def weekend_duty():
    """
        Send message to admin, who will duty on weekend
        :return: nothing
    """
    logger.info('weekend_duty started')
    admsys_admin = request_read_aerospike(item='all_production_admin',
                                          aerospike_set='duty_admin')
    # who will be duty on saturday?
    saturday_duty = get_duty_info(1)
    # who will be duty on sunday?
    sunday_duty = get_duty_info(2)
    chat_id_saturday = set()
    chat_id_sunday = set()
    for admin in saturday_duty:
        chat_id_saturday.add(list(admsys_admin.keys())[list(admsys_admin.values()).index(admin)])
    for admin in sunday_duty:
        chat_id_sunday.add(list(admsys_admin.keys())[list(admsys_admin.values()).index(admin)])
    for chat_id in chat_id_saturday:
        if chat_id in chat_id_sunday:
            telegram_message = {'chat_id': [chat_id],
                                'text': 'Много не пей, ты дежуришь в субботу и воскресенье'}
            request_telegram_send(telegram_message)
            chat_id_sunday.remove(chat_id)
        else:
            telegram_message = {'chat_id': [chat_id],
                                'text': 'Много не пей, ты дежуришь в субботу'}
            request_telegram_send(telegram_message)
    for chat_id in chat_id_sunday:
        telegram_message = {'chat_id': [chat_id],
                            'text': 'Много не пей, ты дежуришь в воскресенье'}
        request_telegram_send(telegram_message)
    logger.info('def weekend_duty successfully finished')


def get_ad_users():
    """
        Сходить в AD, забрать логины, tg-логины, рабочий статус с преобразованием в (working, dismissed)
    """
    logger.info('get_ad_users started')
    try:
        users_dict = {}
        server = Server(config.ad_host)
        conn = Connection(server,user=config.ex_user,password=config.ex_pass)
        conn.bind()
        conn.search(config.base_dn,config.ldap_filter,SUBTREE,attributes=config.ldap_attrs)
    except Exception:
        logger.exception('exception in get_ad_users')

    for entry in conn.entries:
        if not re.search("(?i)OU=_Служебные", str(entry.distinguishedName)): # Убрать служебные учетки
            users_dict [str(entry.sAMAccountName)] = {}
            users_dict [str(entry.sAMAccountName)] ['account_name'] = str(entry.sAMAccountName)
            users_dict [str(entry.sAMAccountName)] ['full_name'] = str(entry.cn)
            users_dict [str(entry.sAMAccountName)] ['email'] = str(entry.mail)
            if len(entry.extensionattribute4) == 0:
                tg_login = ''
            else:
                tg_login = str(entry.extensionattribute4).split(';')[0]

            users_dict [str(entry.sAMAccountName)] ['tg_login'] = tg_login

            if re.search("(?i)OU=_Уволенные сотрудники", str(entry.distinguishedName)):
                working_status = 'dismissed'
            else:
                working_status = 'working'
            users_dict [str(entry.sAMAccountName)] ['working_status'] = working_status
    
    logger.info('Mysql: trying to save users to Users table')
    mysql = MysqlPool()

    for k, v in users_dict.items():
        mysql.db_set_users(v['account_name'], v['full_name'], v['tg_login'], v['working_status'], v['email'])
    logger.info('Mysql: Users saving is completed')


if __name__ == "__main__":

    options = {
        'server': config.jira_host, 'verify': False
    }
    jira_connect = JIRA(options, basic_auth=(config.jira_user, config.jira_pass))

    # Настраиваем логи
    logging.config.fileConfig('/etc/xerxes/logging_assistant.conf')
    logger = logging.getLogger("assistant")
    logger.propagate = False

    # Инициализируем расписание
    scheduler = BlockingScheduler(timezone='Europe/Moscow')

    # Сбор статистики
    scheduler.add_job(lambda: calculate_statistics(jira_connect), 'cron', day_of_week='*',
                      hour=19, minute=0)
    scheduler.add_job(lambda: statistics_json(jira_connect), 'cron', day_of_week='*',
                      hour=23, minute=50)

    # Кто сегодня дежурит
    scheduler.add_job(get_duty_info, 'cron', day_of_week='*', hour=10, minute=1)

    # Who is next?
    scheduler.add_job(lambda: call_who_is_next(jira_connect),
                      'interval', minutes=1, max_instances=1)

    scheduler.add_job(get_ad_users, 'cron', day_of_week='*', hour='*', minute='*/30')

    scheduler.add_job(duties_sync_from_exchange, 'cron', day_of_week='*', hour='*', minute='*')

    scheduler.add_job(weekend_duty, 'cron', day_of_week='fri', hour=14, minute=1)

    # scheduler.add_job(notify_today_duties, 'cron', day_of_week='*', hour=9, minute=31)

    # Запускаем расписание
    scheduler.start()