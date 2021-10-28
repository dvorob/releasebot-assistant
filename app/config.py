#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from playhouse.pool import PostgresqlDatabase, PooledPostgresqlDatabase

ex_host = 'mail-mx10.yamoney.ru'
ex_user = os.environ.get('exchange_user')
ex_pass = os.environ.get('exchange_pass')
ex_cal = 'adminsonduty@yamoney.ru'
ex_tz = 'Europe/Moscow'

jira_host = 'https://jira.yooteam.ru'
# через secret задается в кубере
jira_user = os.environ.get('jira_user')
jira_pass = os.environ.get('jira_pass')
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

jira_filter_components = 'project = COM AND "Target Project" in (BACKEND, BACKEND-API, FRONTEND, YCAPI, BI, ATLASS)'

class JiraFilters(Enum):
    UNASSIGNED_ADMSYS_GALEON = '37402'
    UNASSIGNED_ADMSYS_BAY = '37403'
    UNASSIGNED_ADMSYS_WHEEL = '37404'
    UNASSIGNED_ADMSYS_INFRA_AND_SECOPS = '37405'
    UNASSIGNED_ADMSYS_ALL = '37406'

bot_api_url = 'http://releasebot-api.intools.yooteam.ru'
api_lock_unlock = f'{bot_api_url}/api/tasks/lock_unlock'
api_get_timetable = f'{bot_api_url}/exchange/get_timetable'

informer = 'http://informer.intools.yooteam.ru'
informer_inform_duty_url = f'{informer}/inform_duty'
informer_send_message_url = f'{informer}/send_message'
informer_send_timetable_url = f'{informer}/send_timetable'
inform_subscribers_url = f'{informer}/inform_subscribers'

staff_url = 'https://staff.yooteam.ru/'

#PG configuration
postgres = PooledPostgresqlDatabase(
    'release_bot',
    user=os.environ.get('postgres_user').rstrip(),
    password=os.environ.get('postgres_pass').rstrip(),
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

jira_unassigned_tasks_groups_inform = {
    'Admsys Bay': {
        'channel': 'YM Бухта',
        'filter': JiraFilters.UNASSIGNED_ADMSYS_BAY.value
    },
    'Admsys Galeon': {
        'channel': 'YM Галеон',
        'filter': JiraFilters.UNASSIGNED_ADMSYS_GALEON.value
    },
    'Admsys Infra and SecOps': {
        'channel': 'Admsys.Backoffice',
        'filter': JiraFilters.UNASSIGNED_ADMSYS_INFRA_AND_SECOPS.value
    },
    'Admsys Wheel': {
        'channel': 'YM Штурвал',
        'filter': JiraFilters.UNASSIGNED_ADMSYS_WHEEL.value
    },
    'Admsys All': {
        'channel': 'ym_admsys_newtask_inform',
        'filter': JiraFilters.UNASSIGNED_ADMSYS_ALL.value
    }
}