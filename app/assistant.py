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
        new_tasks = JiraConnection().search_issues(f'filter={config.jira_new_tasks_groups_inform[group]["filter"]}')

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
    total_tasks = 0
    tasks_id = ''
    for group in config.jira_unassigned_tasks_groups_inform.keys():
        # получаем список задач из джиры
        unassigned_tasks = JiraConnection().search_issues(f'filter={config.jira_unassigned_tasks_groups_inform[group]["filter"]}')
        msg = f'\nУважаемые, {group}, у вас <b>нет</b> неразобранных задач в очереди\n'
        if len(unassigned_tasks) > 0:
            msg = f'\n<b>Уважаемые, {group}, у вас {len(unassigned_tasks)} неразобранных задач в очереди</b>:\n'
            msg += '\n'.join([f'<a href="{config.jira_host}/browse/{issue.key}">{issue.key}. {issue.fields.summary}</a>' for issue in unassigned_tasks])
            total_tasks += len(unassigned_tasks)
            tasks_id += ' '.join([issue.key for issue in unassigned_tasks])
            # немного статистики по групам для анализа
            logger.info(f'For {group} found {len(unassigned_tasks)} tasks: {[issue.key for issue in unassigned_tasks]}')
        inform_admins_about_tasks(config.jira_unassigned_tasks_groups_inform[group], msg)


def inform_admins_about_tasks(admins_group: dict, msg: str):
    """
        Отправка уведомление по таскам происходит только в рабочие дни и только с 10 до 20
    """
    if ((int(datetime.today().strftime("%H")) in range(10, 20)) and
        (db().is_workday(datetime.today().strftime("%Y-%m-%d")))):
        if 'channel' in admins_group:
            informer.send_message_to_users([admins_group['channel']], msg)
        elif 'duty_area' in admins_group:
            informer.inform_duty([admins_group['duty_area']], msg)
        else:
            logger.info(f'-- INFORM ADMINS ABOUT TASKS: nowhere to send msg {admins_group} {msg}')


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

    if db().is_workday(today):
        for acc in db().get_all_users_with_subscription('timetable'):
            try:
                db_users = db().get_users('account_name', acc, 'equal')
                if db_users[0]['working_status'] != 'dismissed':
                    header = {'email': db_users[0]['email'], 'afterdays': str(0)}
                    responses = []
                    with requests.session() as session:
                        resp = session.get(config.api_get_timetable, headers=header)
                        msg = (resp.json())['message']
                    informer.send_message_to_users([acc], msg)
                    # Exchange при массовых запросах отваливается по таймауту. Добавим sleep
                    time.sleep(2)
                else:
                    logger.info('TIMETABLE doesn\'t work for dismissed user %s', db_users)
            except Exception as e:
                logger.exception('exception in TIMETABLE %s', str(e))
    else:
        logger.info('No, today is a holiday, I don\'t want to send timetable reminder')


def duty_reminder_daily_morning():
    msg = 'Крепись, ты сегодня дежуришь по %s. С 10:00, если что.'
    duty_informing_from_schedule(1, 'ADMSYS(биллинг)', (msg % 'ADMSYS(биллинг)'))
    duty_informing_from_schedule(1, 'ADMSYS(портал)', (msg % 'ADMSYS(портал)'))
    duty_informing_from_schedule(1, 'ADMSYS(инфра)', (msg % 'ADMSYS(инфра)'))


def duty_reminder_daily_evening():
    msg = 'Напоминаю, ты <b>завтра</b> дежуришь по %s. Будь готов :)'
    duty_informing_from_schedule(1, 'ADMSYS(биллинг)', (msg % 'ADMSYS(биллинг)'))
    duty_informing_from_schedule(1, 'ADMSYS(портал)', (msg % 'ADMSYS(портал)'))
    duty_informing_from_schedule(1, 'ADMSYS(инфра)', (msg % 'ADMSYS(инфра)'))


def duty_reminder_weekend():
    """
        Send message to admin, who will duty on weekend
    """
    logger.info('duty reminder weekend started')
    # Субботние дежурные
    msg = 'Ты дежуришь в субботу по %s'
    duty_informing_from_schedule(1, 'ADMSYS(биллинг)', (msg % 'ADMSYS(биллинг)'))
    duty_informing_from_schedule(1, 'ADMSYS(портал)', (msg % 'ADMSYS(портал)'))
    duty_informing_from_schedule(1, 'ADMSYS(инфра)', (msg % 'ADMSYS(инфра)'))
    # Воскресные дежурные
    msg = 'Ты дежуришь в воскресенье по %s'
    duty_informing_from_schedule(2, 'ADMSYS(биллинг)', (msg % 'ADMSYS(биллинг)'))
    duty_informing_from_schedule(2, 'ADMSYS(портал)', (msg % 'ADMSYS(портал)'))
    duty_informing_from_schedule(2, 'ADMSYS(инфра)', (msg % 'ADMSYS(инфра)'))


def duty_reminder_tststnd_daily():
    """
        Уведомления дежурных по стендам
    """
    logger.info('duty reminder tststnd daily started')
    msg = f"Будь сильным: <b>ты дежуришь по стендам сегодня</b>.\nПроверь, что:\n\
       1. Автообновление <b>int</b> прошло успешно и <a href='https://jira.yooteam.ru/issues/?jql=labels%20%3D%20jenkins.SchemeUpdate%20and%20status%20!%3D%20Closed%20and%20status%20!%3D%20Resolved'>здесь</a>\
       нет задач. Перезапусти обновление, если оно не прошло.\n\
       2. Ночные синки успешны и <a href='https://jira.yooteam.ru/issues/?jql=labels%20%3D%20cloud%20and%20status%20!%3D%20Closed%20and%20status%20!%3D%20Resolved'>здесь</a> нет задач.\n\
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

            logger.debug('I find duty for %s : %s', duty_date.strftime("%Y-%m-%d"), msg)
            # Разобрать сообщение из календаря в формат ["area (зона ответственности)", "имя дежурного", "аккаунт деужурного"]
            duty_list = []
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
                staff_login = '' if u['staff_login'] == None else u['staff_login']
                user_req = requests.get(config.staff_url + '1c82_lk/hs/staff/v1/persons/' + staff_login, 
                                        auth=HttpNtlmAuth(config.ex_user, config.ex_pass), verify=False)
                if user_req.status_code == 404:
                    logger.info(f"User not found and will be dismissed {u}")
                    db().set_users(account_name=u['account_name'], working_status='dismissed')
                    continue
                logger.info(f'user_req {user_req}')
                user_staff = user_req.json()
                db().set_users(account_name=user_staff['loginAD'], full_name=user_staff['firstName'] + ' ' + user_staff['lastName'], 
                                                                   first_name=user_staff['firstName'], 
                                                                   middle_name=user_staff['middleName'])
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


if __name__ == "__main__":

    # Отключаем предупреждения от SSL
    warnings.filterwarnings('ignore')
    logger = logging.setup()
    logger.info('- - - START ASSISTANT - - - ')
    # sync_users_from_staff()
    # sync_user_names_from_staff()
    # --- SCHEDULING ---
    # Инициализируем расписание
    scheduler = BlockingScheduler(timezone='Europe/Moscow')

    # Сбор статистики
    scheduler.add_job(lambda: calculate_statistics(), 'cron', day_of_week='*', hour=19, minute=00)

    # Напоминания о дежурствах
    scheduler.add_job(duty_reminder_daily_morning, 'cron', day_of_week='*',  hour=9, minute=45)
    scheduler.add_job(duty_reminder_daily_evening, 'cron', day_of_week='mon,tue,wed,thu,sun',  hour=18, minute=30)
    scheduler.add_job(duty_reminder_weekend, 'cron', day_of_week='fri', hour=14, minute=1)
    scheduler.add_job(duty_reminder_tststnd_daily, 'cron', day_of_week='mon-fri', hour=9, minute=25)
    scheduler.add_job(timetable_reminder, 'cron', day_of_week='*', hour=9, minute=00)

    # Забрать календарь из 1С
    scheduler.add_job(sync_calendar_daily, 'cron', day_of_week='*', hour=9, minute=10)

    # Забирает всех пользователей из Стаффа, заливает в БД бота в таблицу Users. Используется для информинга
    scheduler.add_job(sync_users_from_staff, 'cron', day_of_week='*', hour='*', minute=35)
    scheduler.add_job(sync_user_names_from_staff, 'cron', day_of_week='*', hour=5, minute=10)

    # Обновить команды, ответственные за компоненты
    scheduler.add_job(update_app_list_by_commands, 'cron', day_of_week='*', hour='*', minute='*/5')

    # Поскольку в 10:00 в календаре присутствует двое дежурных - за вчера и за сегодня, процедура запускается в 5, 25 и 45 минут, чтобы не натыкаться на дубли и не вычищать их
    scheduler.add_job(sync_duties_from_exchange, 'cron', day_of_week='*', hour='*', minute='5-59/10')

    # Обновление страницы ServiceDiscovery.AppsRemotes
    scheduler.add_job(update_service_discovery_remotes_wiki, 'cron', day_of_week='*', hour='*', minute='10')

    # Проверить релизную доску на наличие новых тасок
    scheduler.add_job(looking_for_new_tasks, 'cron', day_of_week='*', hour='*', minute='*/15')

    # Проверить релизную доску на наличие неразобранных тасок
    scheduler.add_job(unassigned_task_reminder, 'cron', day_of_week='mon-fri', hour='10', minute='15')

    # Запускаем расписание
    scheduler.start()
