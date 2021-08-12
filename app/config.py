#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from os import getenv
from playhouse.pool import PostgresqlDatabase, PooledPostgresqlDatabase

ex_host = 'mail-mx10.yamoney.ru'
ex_user = getenv('secret_exchange_user')
ex_pass = getenv('secret_exchange_pass')
ex_cal = 'adminsonduty@yamoney.ru'
ex_tz = 'Europe/Moscow'

jira_host = 'https://jira.yooteam.ru'
# через secret задается в кубере
jira_user = getenv('secret_jira_user')
jira_pass = getenv('secret_jira_pass')
jira_options = {'server': jira_host, 'verify': False}
jira_filter_returned = 'project in (ADMSYS, DEPLOY) AND ' \
                       'issuetype = "Release (conf)" AND ' \
                       '(status not in (Closed, Resolved) OR updated >= startOfDay() ' \
                       'AND status in (Resolved)) AND ' \
                       'text ~ возвращена ORDER BY summary DESC, key ASC'

jira_resolved_today = 'project in (ADMSYS, DEPLOY) AND ' \
                      'issuetype = "Release (conf)" AND ' \
                      'status = Resolved AND updated >= startOfDay() AND ' \
                      'resolution not in (Rollback) ' \
                      'ORDER BY summary DESC, key ASC'

jira_rollback_today = 'project in (ADMSYS, DEPLOY) AND ' \
                      'issuetype = "Release (conf)" AND ' \
                      'resolutiondate >= startOfDay() AND ' \
                      'updated >= startOfDay() AND ' \
                      'resolution = Rollback ' \
                      'ORDER BY summary DESC, key ASC'

jira_filter_full = 'project in (ADMSYS, DEPLOY) AND ' \
                   'issuetype = "Release (conf)" AND ' \
                   'status = "FULL DEPLOY" ' \
                   'ORDER BY priority DESC, updatedDate ASC'

jira_filter_without_waiting_full = 'project in (ADMSYS, DEPLOY) AND ' \
                                   'issuetype = "Release (conf)" AND ' \
                                   'status not in  ("FULL DEPLOY", "Waiting release", Closed, Resolved)  ' \
                                   'ORDER BY priority DESC, updatedDate ASC'

jira_filter_true_waiting = 'project in (ADMSYS, DEPLOY) AND ' \
                           'issuetype = "Release (conf)" AND ' \
                           'status = "Waiting release" ' \
                           'ORDER BY priority DESC, updatedDate ASC'

jira_filter_wip = 'project in (ADMSYS, DEPLOY) AND ' \
                  'issuetype = "Release (conf)" AND ' \
                  'status not in (Closed, Resolved, "Waiting release") ' \
                  'ORDER BY priority DESC, updatedDate ASC'

jira_filter_components = 'project = COM AND "Target Project" in (BACKEND, BACKEND-API, FRONTEND, YCAPI)'

api_chat_id = 'http://releasebot-api/api-v1/chat-id'
api_get_timetable = 'http://releasebot-api/exchange/get_timetable'

informer = 'http://ugr-informer1.admsys.yamoney.ru'
informer_inform_duty_url = f'{informer}/inform_duty'
informer_send_message_url = f'{informer}/send_message'
informer_send_timetable_url = f'{informer}/send_timetable'
inform_subscribers_url = f'{informer}/inform_subscribers'

staff_url = 'https://staff.yooteam.ru/'

#PG configuration
postgres = PooledPostgresqlDatabase(
    'release_bot',
    user=getenv('secret_postgres_user').rstrip(),
    password=getenv('secret_postgres_pass').rstrip(),
    host='iva-pgtools2.yamoney.ru',
    port=7432,
    max_connections=32,
    stale_timeout=300)

# AD configuration
ad_host = 'ldaps.yamoney.ru'
base_dn = 'OU=Сотрудники Компании,DC=yamoney,DC=ru'
ldap_filter = '(&(objectCategory=person)(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))'
ldap_attrs = ['cn','sAMAccountName','distinguishedName','extensionattribute4','memberOf','mail']

oneass_calendar_api = 'http://fin3.yamoney.ru:8080/sais/bp/calendar/getCalendar'

informer = 'http://ugr-informer1.admsys.yamoney.ru'
informer_send_message_url = f'{informer}/send_message'
informer_inform_duty_url = f'{informer}/inform_duty'