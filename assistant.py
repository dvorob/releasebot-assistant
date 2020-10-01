#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""""
    Ассистент релизного бота
    запуск джоб по расписанию, статистика и прочее
"""
import config
import json
import ldap3
import logging.config
import re
import requests
import warnings
from apscheduler.schedulers.background import BlockingScheduler
from datetime import timedelta, datetime
from exchangelib import DELEGATE, Configuration, Credentials, Account
from exchangelib.ewsdatetime import UTC_NOW
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
from jira import JIRA
from ldap3 import Server, Connection, SIMPLE, SYNC, ASYNC, SUBTREE, ALL
from peewee import *
from playhouse.pool import PooledMySQLDatabase

# Отключаем предупреждения от SSL
warnings.filterwarnings('ignore')

# Настраиваем работу с Mysql. Надо бы вынести это в ручку API
__all__ = ['MysqlPool']


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


def send_message_to_users(accounts, message):
    """
        data = {'accounts': ['ymvorobevda'], 'text': 'Работает!'}
    """
    logger.info('Send message to users try for %s %s', accounts, message)
    try:
        data = {'accounts': accounts, 'text': message}
        resp = requests.post(config.informer_send_message_url, data=json.dumps(data))
        if resp.ok:
            logger.info('Successfully sent message to %s %s %s', accounts, message, resp)
        else:
            logger.error('Error in send message for %s %s %s', accounts, message, resp)
    except Exception as e:
        logger.exception('Exception in send message %s', str(e))

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


def get_dismissed_users():
    logger.info('start get dismissed users')
    try:
        server = Server(config.ad_host)
        conn = Connection(server,user=config.ex_user,password=config.ex_pass)
        conn.bind()
        db_users = []
        td = datetime.today() - timedelta(1)
        db_query = Users.select().where(Users.working_status == 'working',
            (
                (Users.date_update < td) |
                (Users.date_update.is_null())
             ))
        for v in db_query:
            db_users.append((vars(v))['__data__'])

        logger.info('Found potential dismissed users in count %s', len(db_users))

        for v in db_users:
            conn.search(config.base_dn,'(&(objectCategory=person)(objectClass=user)(sAMAccountName='+v["account_name"]+'))',SUBTREE,attributes=config.ldap_attrs)
            for entry in conn.entries:
                if re.search("Уволенные", str(entry.distinguishedName)):
                    logger.info('%s was dismissed', v['account_name'])
                    mysql.set_users(v['account_name'], full_name=None, tg_login=None, working_status='dismissed', email=None)
                else:
                    logger.info('get dismissed found that %s is still working', v["account_name"])
    except Exception as e:
        logger.exception('exception in get_users', str(e))


def get_duty_date(date):
    # Если запрошены дежурные до 10 утра, то это "вчерашние дежурные"
    # Это особенность дежурств в Департаменте
    if int(datetime.today().strftime("%H")) < int(10):
        return date - timedelta(1)
    else:
        return date

def duty_informing_from_schedule(after_days, area, msg):
    """
        Отправить уведомление дежурным на заданную дату, вычисляемую по отступу от текущей
    """
    duty_date = get_duty_date(datetime.today()) + timedelta(after_days)
    dutymen_array = mysql.get_duty_in_area(duty_date, area)
    logger.info('dutymen_array %s', dutymen_array)
    if len(dutymen_array) > 0:
        for d in dutymen_array:
            try:
                logger.info('try to send message to %s %s', d, msg)
                send_message_to_users([d['account_name']], msg)
            except BotBlocked:
                logger.info('YM release bot was blocked by %s', d['tg_login'])
            except ChatNotFound:
                logger.error('Chat not found with: %s', d['tg_login'])


def duty_reminder_daily():
    msg = 'Через 15 минут начинается твой дозор.'
    duty_informing_from_schedule(1, 'ADMSYS(биллинг)', msg)
    duty_informing_from_schedule(1, 'ADMSYS(портал)', msg)
    duty_informing_from_schedule(1, 'ADMSYS(инфра)', msg)


def duty_reminder_weekend():
    """
        Send message to admin, who will duty on weekend
        :return: nothing
    """
    logger.info('duty reminder weekend started')
    # Субботние дежурные
    msg = 'Ты дежуришь в субботу'
    duty_informing_from_schedule(1, 'ADMSYS(биллинг)', msg)
    duty_informing_from_schedule(1, 'ADMSYS(портал)', msg)
    duty_informing_from_schedule(1, 'ADMSYS(инфра)', msg)
    # Воскресные дежурные
    msg = 'Ты дежуришь в воскресенье'
    duty_informing_from_schedule(2, 'ADMSYS(биллинг)', msg)
    duty_informing_from_schedule(2, 'ADMSYS(портал)', msg)
    duty_informing_from_schedule(2, 'ADMSYS(инфра)', msg)


def sync_duties_from_exchange():
    """
        Ходит в Exchange и выгребает информацию о дежурствах. Помещает информацию в БД (пока aerospike).
        Все остальные методы ходят за инфой о дежурных в БД.
        Вызывается по cron-у, следовательно изменения в календаре отразятся в боте
    """
    try:
        logger.info('sync duties from exchange started!')
        duty_areas = ['ADMSYS', 'NOC', 'ADMWIN', 'IPTEL', 'ADMMSSQL', 'PROCESS', 'DEVOPS', 'TECH', 'INFOSEC', 'ora', 'pg']

        # Go to Exchange calendar and get duites for 7 next days
        for i in range(0, 13):
            msg = 'Дежурят сейчас:\n'   
            # Вычисляем правильный день для дежурств, с учетом наших 10-часовых особенностей
            if int(datetime.today().strftime("%H")) < int(10):
                duty_date = datetime.today() + timedelta(i) - timedelta(1)
            else:
                duty_date = datetime.today() + timedelta(i)
            cal_start = UTC_NOW() + timedelta(i)
            cal_end = UTC_NOW() + timedelta(i)

            # go to exchange for knowledge
            old_msg, new_msg = ex_duty(cal_start, cal_end)
            msg += old_msg

            logger.info('I find duty for %s %s', duty_date.strftime("%Y-%m-%d"), msg)
            request_write_aerospike(item='duty',
                                    bins={duty_date.strftime("%Y-%m-%d"): msg},
                                    aerospike_set='duty_admin')

            # Разобрать сообщение из календаря в формат ["area (зона ответственности)", "имя дежурного", "аккаунт деужурного"]
            duty_list = []
            for msg in new_msg:
                dl = {'duty_date': duty_date, 'full_text': msg, 'area' : '', 'full_name': '', 'account_name': '', 'tg_login': ''}
                for area in duty_areas:
                    if len(re.findall(area+".*-", msg)) > 0:
                        dl["area"] = re.sub(r' |-', '', (re.findall(area+'.*-', msg))[0])

                    if "area" in dl:
                        if len(re.findall(area+'.*-', msg)) > 0:
                            dl["full_name"] = re.sub(r'^ | +$ | ', '', msg[re.search(area+".*-", msg).end():])
                            search_duty_name = mysql.get_user_by_fullname(dl["full_name"])
                            if search_duty_name:
                                if len(search_duty_name) == 1:
                                    dl["account_name"] = search_duty_name[0]["account_name"]
                                    dl["tg_login"] = search_duty_name[0]["tg_login"]
                logger.debug('duty %s',dl)
                mysql.set_dutylist(dl)

    except Exception as e:
        logger.exception('exception in sync duties from exchange %s', str(e))


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
    duty_list = []
    for msg in ex_acc.calendar.view(start=d_start, end=d_end) \
            .only('start', 'end', 'subject') \
            .order_by('start', 'end', 'subject'):
        admin_on_duty = msg.subject[:150]

        if result == '':
            result = '- %s' % admin_on_duty #- ADMSYS(биллинг)-Никита Спиридонов
        else:
            result += '\n- %s' % admin_on_duty

        duty_list.append(admin_on_duty)

    logger.debug('Информация о дежурных %s %s', result, admin_on_duty)
    return result, duty_list


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


def sync_users_from_ad():
    """
        Сходить в AD, забрать логины, tg-логины, рабочий статус с преобразованием в (working, dismissed)
    """
    logger.debug('sync users from ad started')
    try:
        server = Server(config.ad_host)
        conn = Connection(server,user=config.ex_user,password=config.ex_pass)
        conn.bind()
        conn.search(config.base_dn,config.ldap_filter,SUBTREE,attributes=config.ldap_attrs)
        users_dict = {}
    except Exception:
        logger.exception('exception in get_ad_users')

    for entry in conn.entries:
        logger.debug('Sync users from ad entry %s', entry)
        if not re.search("(?i)OU=_Служебные", str(entry.distinguishedName)): # Убрать служебные учетки
            users_dict [str(entry.sAMAccountName)] = {}
            users_dict [str(entry.sAMAccountName)] ['account_name'] = str(entry.sAMAccountName)
            users_dict [str(entry.sAMAccountName)] ['full_name'] = str(entry.cn)
            users_dict [str(entry.sAMAccountName)] ['email'] = str(entry.mail)
            users_dict [str(entry.sAMAccountName)] ['tg_login'] = ''
            if len(entry.extensionattribute4) > 0:
                if len(str(entry.extensionattribute4).split(';')[0]) > 0:
                    users_dict [str(entry.sAMAccountName)] ['tg_login'] = str(entry.extensionattribute4).split(';')[0]

            if re.search("(?i)OU=_Уволенные сотрудники", str(entry.distinguishedName)):
                working_status = 'dismissed'
            else:
                working_status = 'working'
            users_dict [str(entry.sAMAccountName)] ['working_status'] = working_status
    try:
        for k, v in users_dict.items():
            logger.debug('Sync users from ad users_dict %s', v)
            mysql.set_users(v['account_name'], v['full_name'], v['tg_login'], v['working_status'], v['email'])
        logger.info('Mysql: Users saving is completed')
    except Exception as e:
        logger.exception('exception in sync users from ad %s', str(e))


if __name__ == "__main__":

    options = {
        'server': config.jira_host, 'verify': False
    }
    jira_connect = JIRA(options, basic_auth=(config.jira_user, config.jira_pass))
    mysql = MysqlPool()

    # Инициализируем расписание
    scheduler = BlockingScheduler(timezone='Europe/Moscow')

    # Сбор статистики
    scheduler.add_job(lambda: calculate_statistics(jira_connect), 'cron', day_of_week='*', hour=19, minute=0)
    scheduler.add_job(lambda: statistics_json(jira_connect), 'cron', day_of_week='*', hour=23, minute=50)

    # Напоминания о дежурствах
    scheduler.add_job(duty_reminder_daily, 'cron', day_of_week='*',  hour=9, minute=45)
    scheduler.add_job(duty_reminder_weekend, 'cron', day_of_week='fri', hour=14, minute=1)

    # Who is next?
    scheduler.add_job(lambda: call_who_is_next(jira_connect), 'interval', minutes=1, max_instances=1)

    # Проверка, не уволились ли сотрудники. Запускается раз в час
    scheduler.add_job(get_dismissed_users, 'cron', day_of_week='*', hour='*', minute='45')

    scheduler.add_job(sync_users_from_ad, 'cron', day_of_week='*', hour='*', minute='*/5')

    # Поскольку в 10:00 в календаре присутствует двое дежурных - за вчера и за сегодня, процедура запускается в 5, 25 и 45 минут, чтобы не натыкаться на дубли и не вычищать их
    scheduler.add_job(sync_duties_from_exchange, 'cron', day_of_week='*', hour='*', minute='5-59/20')

    # Запускаем расписание
    scheduler.start()