#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from os import getenv
from playhouse.pool import PostgresqlDatabase, PooledPostgresqlDatabase

ex_host = 'mail-mx10.yamoney.ru'
ex_user = getenv('secret_exchange_user')
ex_pass = getenv('secret_exchange_pass')
ex_cal = 'adminsonduty@yamoney.ru'
ex_tz = 'Europe/Moscow'

jira_host = 'https://jira.yamoney.ru'
# через secret задается в кубере
jira_user = getenv('secret_jira_user')
jira_pass = getenv('secret_jira_pass')
jira_options = {'server': jira_host, 'verify': False}
jira_filter_returned = 'project = ADMSYS AND ' \
                       'issuetype = "Release (conf)" AND ' \
                       '(status not in (Closed, Resolved) OR updated >= startOfDay() ' \
                       'AND status in (Resolved)) AND ' \
                       'text ~ возвращена ORDER BY summary DESC, key ASC'

jira_resolved_today = 'project = ADMSYS AND ' \
                      'issuetype = "Release (conf)" AND ' \
                      'status = Resolved AND updated >= startOfDay() AND ' \
                      'resolution not in (Rollback) ' \
                      'ORDER BY summary DESC, key ASC'

jira_rollback_today = 'project = ADMSYS AND ' \
                      'issuetype = "Release (conf)" AND ' \
                      'resolutiondate >= startOfDay() AND ' \
                      'updated >= startOfDay() AND ' \
                      'resolution = Rollback ' \
                      'ORDER BY summary DESC, key ASC'

jira_filter_full = 'project = ADMSYS AND ' \
                   'issuetype = "Release (conf)" AND ' \
                   'status = "FULL DEPLOY" ' \
                   'ORDER BY priority DESC, updatedDate ASC'

jira_filter_without_waiting_full = 'project = ADMSYS AND ' \
                                   'issuetype = "Release (conf)" AND ' \
                                   'status not in  ("FULL DEPLOY", "Waiting release", Closed, Resolved)  ' \
                                   'ORDER BY priority DESC, updatedDate ASC'

jira_filter_true_waiting = 'project = ADMSYS AND ' \
                           'issuetype = "Release (conf)" AND ' \
                           'status = "Waiting release" ' \
                           'ORDER BY priority DESC, updatedDate ASC'

jira_filter_wip = 'project = ADMSYS AND ' \
                  'issuetype = "Release (conf)" AND ' \
                  'status not in (Closed, Resolved, "Waiting release") ' \
                  'ORDER BY priority DESC, updatedDate ASC'

api_chat_id = 'http://releasebot-api/api-v1/chat-id'
api_get_timetable = 'http://releasebot-api/exchange/get_timetable'

informer = 'http://ugr-informer1.admsys.yamoney.ru'
informer_inform_duty_url = f'{informer}/inform_duty'
informer_send_message_url = f'{informer}/send_message'
informer_send_timetable_url = f'{informer}/send_timetable'
inform_subscribers_url = f'{informer}/inform_subscribers'

#MySQL configuration
# mysql = PooledMySQLDatabase(
#     'xerxes',
#     host='mysql.xerxes.svc.ugr-base1.kube.yamoney.ru',
#     user=getenv('secret_mysql_user'),
#     passwd=getenv('secret_mysql_pass'),
#     max_connections=8,
#     stale_timeout=300)

#PG configuration
postgres = PooledPostgresqlDatabase(
    'release_bot',
    user=getenv('secret_postgres_user').rstrip(),
    password=getenv('secret_postgres_pass').rstrip(),
    host='ugr-pgtools.yamoney.ru',
    port=7432,
    max_connections=32,
    stale_timeout=300)

# AD configuration
ad_host = 'ldaps.yamoney.ru'
base_dn = 'OU=Сотрудники Компании,DC=yamoney,DC=ru'
ldap_filter = '(&(objectCategory=person)(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))'
ldap_attrs = ['cn','sAMAccountName','distinguishedName','extensionattribute4','memberOf','mail']

informer = 'http://ugr-informer1.admsys.yamoney.ru'
informer_send_message_url = f'{informer}/send_message'
informer_inform_duty_url = f'{informer}/inform_duty'