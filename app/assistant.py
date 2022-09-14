#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""""
    Ассистент релизного бота
    запуск джоб по расписанию, статистика и прочее
"""
# External
from pickle import NONE
import aiohttp
from bs4 import BeautifulSoup
import json
import ldap3
import logging.config
import re
import requests
import time
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


def _get_field_value(fields, customfield, key=False, value=False, name=False):
    # Обёртка для работы с customField джиры. Т.к. каждое поле содержит в себе вложенные конструкции
    # разной степени сложности, для упрощения прочего кода все костыли вынесены сюда.
    # К полю можно обратиться, зная, в чем именно содержится значение - в ключе, имени или значении.
    try:
        if hasattr(fields, customfield):
            field = getattr(fields, customfield)
            if field:
                if type(field) is list:
                    field = field[0]
                if key and hasattr(field, 'key'):
                    return field.key
                elif value and hasattr(field, 'value'):
                    return field.value
                elif name and hasattr(field, 'name'):
                    return field.name
                else:
                    return field
        return None
    except Exception as e:
        logger.exception(f'Error in get field value {str(e)} {fields} {customfield}')
        return False


def calculate_statistics():
    """
        Considers statistics, format in human readable format
        and send
    """
    logger.info('-- CALCULATE STATISTICS')
    try:
        today = datetime.today().strftime("%Y-%m-%d")

        if db().is_workday(today):
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


def looking_for_new_tasks():
    """
       Проверить релизную доску на наличие новых тасок
    """
    logger.info('-- LOOKING FOR NEW TASKS')
    total_tasks = 0
    tasks_id = ''
    for group in config.jira_new_tasks_groups_inform.keys():
        group_tasks = 0
        # получаем список задач из джиры
        new_tasks = JiraConnection().search_issues(f'filter={config.jira_new_tasks_groups_inform[group]["filter"]} AND assignee is EMPTY')

        # фильтруем список задач за последние 15 минут в dict где key имя группы и value список задач
        msg = ''
        for issue in new_tasks:
            if datetime.strptime(issue.fields.created[0:19], '%Y-%m-%dT%H:%M:%S') >= (datetime.now() - timedelta(minutes=15)):
                msg += f'<a href="{config.jira_host}/browse/{issue.key}">{issue.key}. {issue.fields.summary}</a>\n'
                group_tasks += 1
                tasks_id += ' '.join(str(issue.key))
        # Если новые задачи были - отправим получившееся уведомление
        if group_tasks > 0:
            total_tasks += group_tasks
            msg = f'\n<b>Уважаемые, {group}, у вас {str(group_tasks)} новых задач в очереди</b>:\n' + msg
            inform_admins_about_tasks(config.jira_unassigned_tasks_groups_inform[group], msg)
            # немного статистики по групам для анализа
            logger.info(f'For {group} found {len(new_tasks)} tasks: {[issue.key for issue in new_tasks]}')

    # общая статистика для анализа
    logger.info(f'Total tasks is {total_tasks}: {tasks_id}')


def unassigned_task_reminder():
    """
       Отправить весь список неразобранных тасок утром
    """
    logger.info('-- LOOKING FOR UNASSIGNED TASKS')
    tasks_id = ''
    for group in config.jira_unassigned_tasks_groups_inform.keys():
        # получаем список задач из джиры
        unassigned_tasks = JiraConnection().search_issues(f'filter={config.jira_unassigned_tasks_groups_inform[group]["filter"]} AND (issuetype = Request OR issuetype = Доступ) AND assignee is EMPTY')
        msg = f'\nУважаемые, {group}, у вас <b>нет</b> неразобранных задач в очереди\n'
        msg_tasks = ''
        if len(unassigned_tasks) > 0:
            msg = f'\n<b>Уважаемые, {group}, у вас {len(unassigned_tasks)} неразобранных задач в очереди</b>:\n'
            for issue in unassigned_tasks:
                sla_str = _get_field_value(issue.fields, 'customfield_17095', value=True)
                if sla_str != None:
                    # Подсветим в тексте, если подгорает SLA
                    if datetime.strptime(sla_str[0:19], '%Y-%m-%dT%H:%M:%S') - datetime.now() < timedelta(hours=8):
                        msg_tasks += f':fire:'
                msg_tasks += f' <a href="{config.jira_host}/browse/{issue.key}">{issue.key}. {issue.fields.summary}</a> \n'
                tasks_id += ' '.join([issue.key for issue in unassigned_tasks])
            # немного статистики по групам для анализа
            logger.info(f'For {group} found {len(unassigned_tasks)} tasks: {[issue.key for issue in unassigned_tasks]}')
        #informer.send_message_to_users(accounts='ymvorobevda', message=msg, emoji=True)
        # Т.к. в имени таски могут встретиться спецсимволы, которые сломают разметку HTML, и сообщение не отправится, отошлём его двумя отдельными месседжами
        # Первое точно уйдет, оно фиксированное. Если не уйдет второе, будет ясно, что что-то пошло не так.
        inform_admins_about_tasks(config.jira_unassigned_tasks_groups_inform[group], msg)
        if len(unassigned_tasks) > 0:
            inform_admins_about_tasks(config.jira_unassigned_tasks_groups_inform[group], msg_tasks)


def expiring_task_reminder():
    """
       Отправить список подгоряющих тасок с исполнителями (подгорающие неразобранные в методе unassigned_task_reminder)
    """
    logger.info('-- LOOKING FOR EXPIRING TASKS')
    for group in config.jira_unassigned_tasks_groups_inform.keys():
        is_something_expiring = False
        # получаем список задач из джиры
        expiring_tasks = JiraConnection().search_issues(f'filter={config.jira_unassigned_tasks_groups_inform[group]["filter"]} AND (issuetype = Request OR issuetype = Доступ) AND assignee is not EMPTY')
        if len(expiring_tasks) > 0:
            msg = f'\n<b>SLA просрачивается у следующих задач:</b>\n'
            for issue in expiring_tasks:
                sla_str = _get_field_value(issue.fields, 'customfield_17095', value=True)
                if sla_str != None:
                    # Подсветим в тексте, если подгорает SLA
                    if datetime.strptime(sla_str[0:19], '%Y-%m-%dT%H:%M:%S') - datetime.now() < timedelta(hours=8):
                        is_something_expiring = True
                        msg += f':fire: <a href="{config.jira_host}/browse/{issue.key}">{issue.key}. {issue.fields.summary} // {issue.fields.assignee}</a> \n'
        if is_something_expiring == True:
            inform_admins_about_tasks(config.jira_unassigned_tasks_groups_inform[group], msg)


def inform_admins_about_tasks(admins_group: dict, msg: str):
    """
        Отправка уведомление по таскам происходит только в рабочие дни и только с 10 до 20
    """
    if ((int(datetime.today().strftime("%H")) in range(10, 20)) and
        (db().is_workday(datetime.today().strftime("%Y-%m-%d")))):
        if 'channel' in admins_group:
            informer.send_message_to_users(accounts=[admins_group['channel']], message=msg, emoji=True)
        elif 'duty_area' in admins_group:
            informer.inform_duty([admins_group['duty_area']], msg)
        else:
            logger.info(f'-- INFORM ADMINS ABOUT TASKS: nowhere to send msg {admins_group} {msg}')


def locked_releases_reminder():
    """
       Отправит в чат ADMSYS инфу по залоченным релизам, в начале дня
    """
    try:
        app_list = db().get_applications('bot_enabled', False, 'equal')
        if len(app_list) > 0:
            msg = 'Залоченные приложения (релизы ботом отключены):\n'
            for app in app_list:
                msg += f'- <b>{app["app_name"]}</b> заблокировал {app["locked_by"]}\n'
        else:
            msg = 'Залоченных приложений нет'
        informer.send_message_to_users('localADMSYS', msg)
    except Exception as e:
        logger.exception(f'Error in locked releases reminder {str(e)}')


def duty_informing_from_schedule(after_days, area, msg):
    """
        Отправить уведомление дежурным на заданную дату, вычисляемую по отступу от текущей
    """
    duty_date = _get_duty_date(datetime.today()) + timedelta(after_days)
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

    if db().is_workday(today):
        for acc in db().get_all_users_with_subscription('timetable'):
            try:
                db_users = db().get_users('account_name', acc, 'equal')
                if db_users[0]['working_status'] != 'dismissed':
                    header = {'email': db_users[0]['email'], 'afterdays': str(0)}
                    with requests.session() as session:
                        resp = session.get(config.api_get_timetable, headers=header)
                        msg = (resp.json())['message']
                        status = (resp.json())['status']
                    if status == 'error':
                        msg = f"Доброго утра, {db_users[0]['first_name']} {db_users[0]['middle_name']}. Спешу сообщить о следующем: \n" + msg
                    informer.send_message_to_users([acc], msg)
                    # Exchange при массовых запросах отваливается по таймауту. Добавим sleep
                    time.sleep(2)
                else:
                    logger.info('TIMETABLE doesn\'t work for dismissed user %s', db_users)
            except Exception as e:
                logger.exception('exception in TIMETABLE %s', str(e))
    else:
        logger.info('No, today is a holiday, I don\'t want to send timetable reminder')


def _notify_duties_from_list(users: list, duties: list, msg: str):
    logger.info(f'--- NOTIFY DUTIES FROM LIST {users} {duties}')
    for acc in users:
        try:
            db_users = db().get_users('account_name', acc, 'equal')
            if db_users[0]['working_status'] != 'dismissed':
                for duty in duties:
                    if (duty['account_name'] == acc):
                        logger.info(f'--- {duty["area"]} {type(duty["area"])}')
                        message = msg % duty['area']
                        informer.send_message_to_users(accounts=acc, message=message, emoji=True, polite=True)
                        time.sleep(1)
        except Exception as e:
            logger.exception('exception in duty reminder %s', str(e))


def duty_reminder_daily_morning():
    msg = 'спешу сообщить, что вы сегодня дежурите по %s с 10:00. Хорошего дня!'
    # +1 день, т.к. проверка запускается до 10.00 - чтобы не уведомить вчерашних дежурных
    duty_date = _get_duty_date(datetime.today()) + timedelta(1)
    duties_list = db().get_duty(duty_date)
    subscribed_dutymen_list = db().get_all_users_with_subscription('duties')
    _notify_duties_from_list(users=subscribed_dutymen_list, duties=duties_list, msg=msg)


def duty_reminder_daily_evening():
    msg = 'спешу сообщить, что вы <b>завтра</b> дежурите по %s'
    duty_date = _get_duty_date(datetime.today()) + timedelta(1)
    duties_list = db().get_duty(duty_date)
    subscribed_dutymen_list = db().get_all_users_with_subscription('duties')
    _notify_duties_from_list(users=subscribed_dutymen_list, duties=duties_list, msg=msg)


def duty_reminder_weekend():
    """
        Send message to admin, who will duty on weekend
    """
    logger.info('duty reminder weekend started')
    # Субботние дежурные
    msg = 'смею напомнить, что вы дежурите в субботу по %s'
    duty_date = _get_duty_date(datetime.today()) + timedelta(1)
    duties_list = db().get_duty(duty_date)
    subscribed_dutymen_list = db().get_all_users_with_subscription('duties')
    _notify_duties_from_list(users=subscribed_dutymen_list, duties=duties_list, msg=msg)
    # Воскресные дежурные
    msg = 'смею напомнить, что вы дежурите в воскресенье по %s'
    duty_date = _get_duty_date(datetime.today()) + timedelta(2)
    duties_list = db().get_duty(duty_date)
    subscribed_dutymen_list = db().get_all_users_with_subscription('duties')
    _notify_duties_from_list(users=subscribed_dutymen_list, duties=duties_list, msg=msg)


def duty_reminder_tststnd_daily():
    """
        Уведомления дежурных по стендам
    """
    today = datetime.today().strftime("%Y-%m-%d")
    if db().is_workday(today):
        logger.info('duty reminder tststnd daily started')
        msg = f"Будь сильным: <b>ты дежуришь по стендам сегодня</b>.\nПроверь, что:\n\
        1. Автообновление <b>int</b> прошло успешно и <a href='https://jira.yooteam.ru/issues/?jql=labels%20%3D%20jenkins.SchemeUpdate%20and%20status%20!%3D%20Closed%20and%20status%20!%3D%20Resolved'>здесь</a>\
        нет задач. Перезапусти обновление, если оно не прошло.\n\
        1a. Автообновление остальных схем можно проверить тут <a href='https://grafana-dev.yooteam.ru/d/iPuc_si7k/cloud-scheme-update-failed-count?orgId=1'>дашборд</a>.\n\
        Если фейлов неприлично много, стоит уточнить причину.\n\
        2. Ночные синки успешны и <a href='https://jira.yooteam.ru/issues/?jql=labels%20%3D%20cloud%20and%20status%20!%3D%20Closed%20and%20status%20!%3D%20Resolved'>здесь</a> нет задач.\n\
        Днем проверь как <a href='https://jenkins-dev.yooteam.ru/job/CLOUD/job/Base/job/recreate_basetest/lastBuild'>пересоздалась btest</a>. Важно дотолкать ее до тестов, чтобы QA было что разбирать.\n\
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
        duty_areas = ['ADMSYS', 'NOC', 'ADMWIN', 'IPTEL', 'ADMMSSQL', 'PROCESS', 'DEVOPS', 'TECH', 'INFOSEC', 'ora', 'pg', 'ORACLE', 'POSTGRES']

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

            logger.debug('I find duty for %s : %s', duty_date.strftime("%Y-%m-%d"), msg)
            # Разобрать сообщение из календаря в формат ["area (зона ответственности)", "имя дежурного", "аккаунт деужурного"]
            for msg in new_msg:
                msg = re.sub(r'—', '-', msg)
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
#                      USER FROM Staff
#########################################################################################

def sync_users_from_staff():
    """
        Сходить в Staff (staff.yooteam.ru) за сотрудниками
    """
    logger.info('-- SYNC USERS FROM STAFF')

    users_req = {}
    users_req = requests.get(config.staff_url + '1c82_lk/hs/staff/v1/persons?target=chat-bot', 
                                auth=HttpNtlmAuth(config.ex_user, config.ex_pass), verify=False)
    users_dict = users_req.json()
    for user in users_dict:
        try:
            working_status = 'dismissed' if user['dismissed'] else 'working'
            # Если логин AD не заполнен (актуально для аутстафферов), обрежем email - есть шанс, что он совпадает с логином AD
            # Если не совпадет, пользователь не получит уведомления о своих релизах. 
            if (len(user['loginAD']) == 0 and len(user['workEmail']) > 0):
                user['loginAD'] = user['workEmail'][:user['workEmail'].index('@')]
            db().set_users(account_name=user['loginAD'], tg_login=user['telegrams'][0], 
                           working_status=working_status, email=user['workEmail'], staff_login=user['login'])
        except Exception as e:
            logger.exception(f'Error in sync users from staff {user} {str(e)}')


def sync_user_names_from_staff():
    """
        Сходить в Staff (staff.yooteam.ru) за именами сотрудников
    """
    logger.info('-- SYNC USER NAMES FROM STAFF')

    db_users = db().get_users('working_status', 'working', 'equal')
    for u in db_users:
        try:
            if ('staff_login' in u and u['staff_login'] != None and u['working_status'] != 'dismissed'):
                user_req = {}
                is_ops = None
                team_name = None
                team_key = None
                department = None
                is_admin = None
                staff_login = '' if u['staff_login'] == None else u['staff_login']
                user_req = requests.get(config.staff_url + '1c82_lk/hs/staff/v1/persons/' + staff_login, 
                                        auth=HttpNtlmAuth(config.ex_user, config.ex_pass), verify=False)
                if user_req.status_code == 404:
                    logger.info(f"User not found and will be dismissed {u}")
                    db().set_users(account_name=u['account_name'], working_status='dismissed')
                    continue
                user_staff = user_req.json()
                if 'departments'in user_staff:
                    if len(user_staff['departments']) > 0:
                        if 'name' in user_staff['departments'][0]:
                            team_name = user_staff['departments'][0]['name']
                    if len(user_staff['departments']) > 1:
                        if 'name' in user_staff['departments'][1]:
                            department = user_staff['departments'][1]['name']
                if team_name == 'Отдел сопровождения внешних систем':
                    is_admin = 1
                if department in ('Департамент эксплуатации', 'Департамент информационной безопасности и противодействия мошенничеству'):
                    team_key = db().get_team_key(team_name)
                    is_ops = 1
                db().set_users(account_name=user_staff['loginAD'], full_name=user_staff['firstName'] + ' ' + user_staff['lastName'], first_name=user_staff['firstName'], 
                               middle_name=user_staff['middleName'], is_ops=is_ops, team_name=team_name, department=department, team_key=team_key, is_admin=is_admin,
                               gender=user_staff['gender'])
                time.sleep(1)
        except Exception as e:
            logger.exception(f'Error in sync user names from staff {u} {user_req} {str(e)}')
            time.sleep(1)


def sync_users_from_ad():
    """
        OBSOLETE
        Использовалась, когда стафф был не готов. Оставим на всякий случай/
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


def _get_duty_date(date):
    # Если запрошены дежурные до 10 утра, то это "вчерашние дежурные"
    # Это особенность дежурств в Департаменте
    if int(datetime.today().strftime("%H")) < int(10):
        return date - timedelta(1)
    else:
        return date


if __name__ == "__main__":

    # Отключаем предупреждения от SSL
    warnings.filterwarnings('ignore')
    logger = logging.setup()
    logger.info('- - - START ASSISTANT - - - ')
    sync_user_names_from_staff()
    # unassigned_task_reminder()
    # --- SCHEDULING ---
    # Инициализируем расписание
    scheduler = BlockingScheduler(timezone='Europe/Moscow')

    # Сбор статистики
    scheduler.add_job(lambda: calculate_statistics(), 'cron', day_of_week='*', hour=19, minute=00)

    # Напоминания о дежурствах
    scheduler.add_job(duty_reminder_daily_morning, 'cron', day_of_week='*', hour=9, minute=45)
    scheduler.add_job(duty_reminder_daily_evening, 'cron', day_of_week='mon,tue,wed,thu,sun', hour=18, minute=30)
    scheduler.add_job(duty_reminder_weekend, 'cron', day_of_week='fri', hour=14, minute=1)
    scheduler.add_job(duty_reminder_tststnd_daily, 'cron', day_of_week='mon-fri', hour=9, minute=25)
    scheduler.add_job(timetable_reminder, 'cron', day_of_week='*', hour=9, minute=00)

    # Забрать календарь из 1С
    scheduler.add_job(sync_calendar_daily, 'cron', day_of_week='*', hour=9, minute=10)

    # Забирает всех пользователей из Стаффа, заливает в БД бота в таблицу Users. Используется для информинга
    scheduler.add_job(sync_users_from_staff, 'cron', day_of_week='*', hour='*', minute=35)
    scheduler.add_job(sync_user_names_from_staff, 'cron', day_of_week='*', hour=3, minute=10)

    # Обновить команды, ответственные за компоненты
    scheduler.add_job(update_app_list_by_commands, 'cron', day_of_week='*', hour='*', minute='*/5')

    # Поскольку в 10:00 в календаре присутствует двое дежурных - за вчера и за сегодня, процедура запускается в 5, 25 и 45 минут, чтобы не натыкаться на дубли и не вычищать их
    scheduler.add_job(sync_duties_from_exchange, 'cron', day_of_week='*', hour='*', minute='5-59/10')

    # Обновление страницы ServiceDiscovery.AppsRemotes
    scheduler.add_job(update_service_discovery_remotes_wiki, 'cron', day_of_week='*', hour='*', minute='32')

    # Проверить релизную доску на наличие новых тасок
    scheduler.add_job(looking_for_new_tasks, 'cron', day_of_week='*', hour='*', minute='*/15')

    # Проверить релизную доску на наличие неразобранных тасок
    scheduler.add_job(unassigned_task_reminder, 'cron', day_of_week='mon-fri', hour='10', minute='15')

    # Проверить релизную доску на наличие просрачиваемых тасок
    scheduler.add_job(expiring_task_reminder, 'cron', day_of_week='mon-fri', hour='10', minute='16')

    # Прислать нотификацию со списком залоченных релизов
    scheduler.add_job(locked_releases_reminder, 'cron', day_of_week='mon-fri', hour='10', minute='10')

    # Запускаем расписание
    scheduler.start()

    t_end = time.time() + 60 * 15
    while time.time() < t_end:
        TOKEN = '1325529740:AAHY0Z74zpi3SB4K4ksyEwLKPvhwJjx3Y2k'
        CHAT_ID = 279933948
        SEND_URL = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
        requests.post(SEND_URL, json={'chat_id': CHAT_ID, 'text': 'TEST***'})