#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""""
    Ассистент релизного бота
    запуск джоб по расписанию, статистика и прочее
"""
# External
import aiohttp
from bs4 import BeautifulSoup
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
from ldap3 import Server, Connection, SIMPLE, SYNC, ASYNC, SUBTREE, ALL
from peewee import *
from requests_ntlm import HttpNtlmAuth
# Internal
import config as config
import utils.informer as informer
from utils import logging
from utils.database import PostgresPool as db
from utils.jiratools import JiraConnection, jira_get_components
from utils.consultowiki import ServiceDiscoveryAppRemotesTable


def calculate_statistics():
    """
        Considers statistics, format in human readable format
        and send
    """
    logger.info('-- CALCULATE STATISTICS')
    try:
        today = datetime.today().strftime("%Y-%m-%d")

        if db().get_workday(today):
            msg = f'Статистика по релизам за сегодня.\n'

            rollback = JiraConnection().search_issues(config.jira_rollback_today)
            msg += f'\n<b>{len(rollback)} откачено</b>:\n'
            msg += '\n'.join([f'<a href="{config.jira_host}/browse/{issue.key}">{issue.fields.summary}</a>' for issue in rollback])

            resolved = JiraConnection().search_issues(config.jira_resolved_today)
            msg += f'\n<b>{len(resolved)} выложено</b>:\n'
            msg += '\n'.join([f'<a href="{config.jira_host}/browse/{issue.key}">{issue.fields.summary}</a>' for issue in resolved])

            informer.inform_subscribers('statistics', msg)
            # Пока не выделил отдельный тип в подписке - 'subscribers', будет так.
            logger.info('Statistics:\n %s\n Has been sent')
        else:
            logger.info('No, today is a holiday, I don\'t want to count statistics')
    except Exception as e:
        logger.exception('Error in CALCULATE STATISTICS %s', e)


def get_dismissed_users():
    """
    Проверяет, не уволился ли пользователь.
    Берёт всех пользователей из внутренней БД бота. Проверяет каждый account_name на предмет увольнения в AD (учетка попадет в OU="Уволенные...")
    """
    logger.info('-- GET DISMISSED USERS')
    try:
        server = Server(config.ad_host, use_ssl=True)
        conn = Connection(server, user=config.ex_user, password=config.ex_pass)
        conn.bind()
        db_users = []
        td = datetime.today() - timedelta(1)
        db_users = db().get_users('working_status', 'working', 'equal')
        logger.info('Found potential dismissed users in count %s', len(db_users))

        for v in db_users:
            conn.search(config.base_dn,'(&(objectCategory=person)(objectClass=user)(sAMAccountName='+v["account_name"]+'))',SUBTREE,attributes=config.ldap_attrs)
            for entry in conn.entries:
                if re.search("Уволенные", str(entry.distinguishedName)):
                    logger.info('%s was dismissed', v['account_name'])
                    db().set_users(v['account_name'], full_name=None, tg_login=None, working_status='dismissed', email=None)
                else:
                    logger.debug('get dismissed found that %s is still working', v["account_name"])
    except Exception as e:
        logger.exception('Error in GET DISMISSED USERS', str(e))


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
    dutymen_array = db().get_duty_in_area(duty_date, area)
    logger.info(f'Duty informing from schedule {after_days} {area} {msg} {dutymen_array}')
    if len(dutymen_array) > 0:
        for d in dutymen_array:
            try:
                logger.debug('try to send message to %s %s', d, msg)
                informer.send_message_to_users([d['account_name']], msg)
            except BotBlocked:
                logger.info('YM release bot was blocked by %s', d['tg_login'])
            except ChatNotFound:
                logger.error('Chat not found with: %s', d['tg_login'])


def timetable_reminder():
    """
        Отправить уведомление с расписанием на день.
        У каждого пользователя свой календарь, поэтому отправить всё в ручку informer/inform_subscribers не получится.
    """
    logger.info('-- TIMETABLE REMINDER')
    today = datetime.today().strftime("%Y-%m-%d")

    if db().get_workday(today):
        for acc in db().get_all_users_with_subscription('timetable'):
            try:
                db_users = db().get_users('account_name', acc, 'equal')
                if db_users[0]['working_status'] != 'dismissed':
                    header = {'calendar_email': db_users[0]['email'], 'afterdays': str(0)}
                    responses = []
                    with requests.session() as session:
                        resp = session.get(config.api_get_timetable, headers=header)
                        msg = (resp.json())['message']
                    informer.send_message_to_users([acc], msg)
                else:
                    logger.info('Timetable doesn\'t work for dismissed user %s', db_users)
            except Exception as e:
                logger.exception('exception in timetable %s', str(e))
    else:
        logger.info('No, today is a holiday, I don\'t want to send timetable reminder')


def duty_reminder_daily_morning():
    msg = 'Крепись, ты сегодня дежуришь. С 10:00, если что.'
    duty_informing_from_schedule(1, 'ADMSYS(биллинг)', msg)
    duty_informing_from_schedule(1, 'ADMSYS(портал)', msg)
    duty_informing_from_schedule(1, 'ADMSYS(инфра)', msg)


def duty_reminder_daily_evening():
    msg = 'Напоминаю, ты <b>завтра</b> дежуришь по проду. Будь готов :)'
    duty_informing_from_schedule(1, 'ADMSYS(биллинг)', msg)
    duty_informing_from_schedule(1, 'ADMSYS(портал)', msg)
    duty_informing_from_schedule(1, 'ADMSYS(инфра)', msg)


def duty_reminder_weekend():
    """
        Send message to admin, who will duty on weekend
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


def duty_reminder_tststnd_daily():
    """
        Уведомления дежурных по стендам
    """
    logger.info('duty reminder tststnd daily started')
    msg = f"Будь сильным: <b>ты дежуришь по стендам сегодня</b>.\nПроверь, что:\n\
       1. Автообновление <b>int</b> прошло успешно и <a href='https://jira.yamoney.ru/issues/?jql=labels%20%3D%20jenkins.SchemeUpdate%20and%20status%20!%3D%20Closed%20and%20status%20!%3D%20Resolved'>здесь</a>\
       нет задач. Перезапусти обновление, если оно не прошло.\n\
       2. Ночные синки успешны и <a href='https://jira.yamoney.ru/issues/?jql=labels%20%3D%20cloud%20and%20status%20!%3D%20Closed%20and%20status%20!%3D%20Resolved'>здесь</a> нет задач.\n\
       Днем проверь как <a href='https://jenkins-dev.yamoney.ru/job/CLOUD/job/Base/job/recreate_basetest/lastBuild'>пересоздалась btest</a>. Важно дотолкать ее до тестов, чтобы QA было что разбирать.\n\
       Если в результате чекапа есть повторяющиеся проблемы – сделай задачи на плановую починку."
    duty_informing_from_schedule(1, 'ADMSYS(tststnd)', msg)


def sync_duties_from_exchange():
    """
        Ходит в Exchange и выгребает информацию о дежурствах. Помещает в PG duty_list
        Все остальные методы ходят за инфой о дежурных в БД.
        Вызывается по cron-у, следовательно изменения в календаре отразятся в боте
    """
    try:
        logger.info('-- SYNC DUTIES FROM EXCHANGE')
        duty_areas = ['ADMSYS', 'NOC', 'ADMWIN', 'IPTEL', 'ADMMSSQL', 'PROCESS', 'DEVOPS', 'TECH', 'INFOSEC', 'ora', 'pg']

        # Go to Exchange calendar and get duites for 30 next days
        for i in range(0, 30):
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

            logger.info('I find duty for %s : %s', duty_date.strftime("%Y-%m-%d"), msg)
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
                            search_duty_name = db().get_user_by_fullname(dl["full_name"])
                            if search_duty_name:
                                if len(search_duty_name) == 1:
                                    dl["account_name"] = search_duty_name[0]["account_name"]
                                    dl["tg_login"] = search_duty_name[0]["tg_login"]
                logger.debug('Duty result %s',dl)
                db().set_dutylist(dl)

    except Exception as e:
        logger.exception('exception in sync duties from exchange %s', str(e))


def ex_connect():
    """
        Connect to exchange
        :return:
    """
    try:
        # Отключаем верификацию SLL сертификатов Exchange
        BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

        ex_cred = Credentials(config.ex_user, config.ex_pass)
        ex_cfg = Configuration(server=config.ex_host, credentials=ex_cred)
        ex_acc = Account(primary_smtp_address=config.ex_cal, config=ex_cfg,
                         access_type=DELEGATE, autodiscover=False)
        return ex_acc
    except Exception as e:
        logger.exception('exception in ex_connect %s', str(e))


def ex_duty(d_start, d_end):
    """
        Получить из календаря Exchange AdminsOnDuty информацию о дежурных.
    """
    ex_acc = ex_connect()

    result = ''
    duty_list = []
    logger.debug(f"ex duty {d_start} {d_end}")
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


def update_app_list_by_commands():
    """
    Запускается по расписанию, выгребает из Jira названия компонент и ответственные команды (из справочника COM)
    Обновляет команды в таблице app_list в БД бота.
    """
    logger.info('-- UPDATE APP LIST BY COMMANDS has started')
    try:
        components = jira_get_components()
        for c in components:
            db().set_application_dev_team(c['app_name'], c['dev_team'])
    except Exception as e:
        logger.exception('Error in update app list %s', str(e))


def call_who_is_next():
    """
    УБРАТЬ ОТСЮДА ЦЕЛИКОМ. ЕЙ МЕСТО В REMASTER
    """
    try:
        run_mode = db().get_parameters('run_mode')[0]['value']
        logger.debug('Remaster: run_mode = %s', run_mode)

        if not run_mode:
            run_mode = 'off'
            # 0 - спать, 1 - доделывать, 2 - штатный режим

        if run_mode == 'on':
            name_task_will_release_next = who_is_next()
            if not name_task_will_release_next:
                logger.error('I can\'t find task_will_release_next')
            else:
                issues = JiraConnection().search_issues(config.jira_filter_true_waiting)

                for issue in issues:
                    if name_task_will_release_next in issue.fields.summary:
                        finding_issue = issue
                        logger.info('I find, this is %s', finding_issue)
                        break

                notifications_sent = db().get_release_notifications_sent(rl_obj.jira_task)
                if 'next_release' in notifications_sent:
                    logger.warning('Already sent notification to %s', str(finding_issue))
                else:
                    logger.info('I ready sent notification about next release: %s ', finding_issue)
                    db().append_release_notifications_sent(finding_issue, 'next_release')

                    message = f"Релиз [{finding_issue.fields.summary}]({finding_issue.permalink()}) \
                                будет искать согласующих в ближайшие 10-20 минут. Но это не точно."
                    informer.send_message_to_approvers(task_json['jira_task'], message)
        else:
            # Если продолжать нет необходимости, просто спим
            logger.debug('sleeping')
    except Exception:
        logger.exception('call_who_is_next')


def who_is_next():
    """
        Test write function for notificication about you release will be next
    """

    metaconfig_yaml = {'apps': []}

    metaconfig_yaml_apps = metaconfig_yaml['apps']

    tasks_wip = JiraConnection().search_issues(config.jira_filter_wip)
    true_waiting_task = JiraConnection().search_issues(config.jira_filter_true_waiting)
    task_full_deploy = JiraConnection().search_issues(config.jira_filter_full)
    task_without_waiting_full = JiraConnection().search_issues(config.jira_filter_without_waiting_full)
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

#########################################################################################
#                      1C Calendar
#########################################################################################


def sync_calendar_daily():
    """
        Ежедневное обновление календаря в БД бота
    """
    logger.info('-- SYNC CALENDAR DAILY')
    # Вернёт массив по кол-ву дней в году
    soup = BeautifulSoup(get_calendar_from_1c(), 'lxml')
    today = datetime.today()
    today_for_calendar = today.strftime("%Y-%m-%d")
    # Возьмем номер текущего дня с начала года
    today_day_number = datetime.now().timetuple().tm_yday-1
    # Переберём дни текущего и на 14 вперед, чтобы иметь запас на случай недоступности 1С или проблем интеграции
    for day_number in range (today_day_number, today_day_number + 14):
        logger.debug('Today is %s', soup('workingcalendarday')[day_number]['typeofday'])
        if soup('workingcalendarday')[day_number]['typeofday'] in {'Рабочий', 'Предпраздничный'}:
            # Если сегодня рабочий день, положим в item work_day_or_not 1, set=remaster
            db().set_workday(soup('workingcalendarday')[day_number]['date'], 1)
        else:
            db().set_workday(soup('workingcalendarday')[day_number]['date'], 0)
            logger.debug('Isn\'t working day %s', soup('workingcalendarday')[day_number])


def get_calendar_from_1c() -> str:
    """
        Запрос в API 1C за календарем
    """
    logger.info('-- GET CALENDAR FROM 1C')
    try:
        cur_year = datetime.now().year
        req = requests.get(f"{config.oneass_calendar_api}?year={cur_year}")
        logger.debug('GET CALENDAR FROM 1C: %s', req.text)
        return req.text
    except Exception as e:
        logger.exception('Error in GET CALENDAR FROM 1C %s', e)

#########################################################################################
#                      USER FROM AD
#########################################################################################

def sync_users_from_staff():
    """
        Сходить в Staff (staff.yooteam.ru) за сотрудниками
    """
    logger.info('-- SYNC USERS FROM STAFF')
    try:
        users_req = {}
        users_req = requests.get(config.staff_url + '1c82_lk/hs/staff/v1/persons?target=chat-bot', 
                                    auth=HttpNtlmAuth(config.ex_user, config.ex_pass), verify=False)
        logger.info(users_req)
        users_dict = users_req.json()
        logger.info(users_dict)
    except Exception as e:
        logger.exception('Error in sync users from staff %s', e)


def sync_users_from_ad():
    """
        Сходить в AD, забрать логины, tg-логины, рабочий статус с преобразованием в (working, dismissed)
    """
    logger.info('-- SYNC USERS FROM AD')
    try:
        server = Server(config.ad_host, use_ssl=True)
        conn = Connection(server, user=config.ex_user, password=config.ex_pass)
        conn.bind()
        conn.search(config.base_dn, config.ldap_filter, SUBTREE, attributes=config.ldap_attrs)
        users_dict = {}
    except Exception as e:
        logger.exception('exception in sync users from ad with connection %s', e)
        return e

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
            db().set_users(v['account_name'], v['full_name'], v['tg_login'], v['working_status'], v['email'])
        logger.info('DB: Users saving is completed')
    except Exception as e:
        logger.exception('exception in sync users from ad %s', str(e))


def update_service_discovery_remotes_wiki():
    """
    Читает из consul desc.yml всех зарегистрированных приложений, формирует из списка приложений и remotes
    html таблицу и отправляет её на wiki
    """
    logger.info('-- UPDATE SERVICE DISCOVERY REMOTES WIKI has started')
    consul_to_wiki = ServiceDiscoveryAppRemotesTable(config.jira_user, config.jira_pass)
    html = consul_to_wiki.create_html_table()
    consul_to_wiki.push_to_wiki(html)


if __name__ == "__main__":

    # Отключаем предупреждения от SSL
    warnings.filterwarnings('ignore')
    logger = logging.setup()
    logger.info('- - - START ASSISTANT - - - ')
    sync_users_from_staff()
    # --- SCHEDULING ---
    # Инициализируем расписание
    scheduler = BlockingScheduler(timezone='Europe/Moscow')

    # Сбор статистики
    scheduler.add_job(lambda: calculate_statistics(), 'cron', day_of_week='*', hour=19, minute=00)

    # Напоминания о дежурствах
    scheduler.add_job(duty_reminder_daily_morning, 'cron', day_of_week='*',  hour=9, minute=45)
    scheduler.add_job(duty_reminder_daily_evening, 'cron', day_of_week='mon,tue,wed,thu',  hour=18, minute=30)
    scheduler.add_job(duty_reminder_weekend, 'cron', day_of_week='fri', hour=14, minute=1)
    scheduler.add_job(duty_reminder_tststnd_daily, 'cron', day_of_week='mon-fri', hour=9, minute=25)
    scheduler.add_job(timetable_reminder, 'cron', day_of_week='*', hour=9, minute=30)

    # Забрать календарь из 1С
    scheduler.add_job(sync_calendar_daily, 'cron', day_of_week='*', hour=9, minute=10)

    # Проверка, не уволились ли сотрудники. Запускается раз в час
    scheduler.add_job(get_dismissed_users, 'cron', day_of_week='*', hour='*', minute='25')

    scheduler.add_job(sync_users_from_ad, 'cron', day_of_week='*', hour='*', minute='55')

    # Обновить команды, ответственные за компоненты
    scheduler.add_job(update_app_list_by_commands, 'cron', day_of_week='*', hour='*', minute='*/5')

    # Поскольку в 10:00 в календаре присутствует двое дежурных - за вчера и за сегодня, процедура запускается в 5, 25 и 45 минут, чтобы не натыкаться на дубли и не вычищать их
    scheduler.add_job(sync_duties_from_exchange, 'cron', day_of_week='*', hour='*', minute='*/3')

    # Обновление страницы ServiceDiscovery.AppsRemotes
    scheduler.add_job(update_service_discovery_remotes_wiki, 'cron', day_of_week='*', hour='*', minute='10')

    # Запускаем расписание
    scheduler.start()
