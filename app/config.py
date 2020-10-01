#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from os import getenv

ex_host = 'mail-mx10.yamoney.ru'
ex_user = getenv('secret_exchange_user')
ex_pass = getenv('secret_exchange_pass')
ex_cal = 'adminsonduty@yamoney.ru'
ex_tz = 'Europe/Moscow'

those_who_need_send_statistics = {'dyvorobev': 279933948, 'atampel': 61941403, 'agaidai': 568795685}

jira_host = 'https://jira.yamoney.ru/'
# через secret задается в кубере
jira_user = getenv('secret_jira_user')
jira_pass = getenv('secret_jira_pass')
jira_options = {'server': jira_host, 'verify': False}
jira_filter_returned = 'project = ADMSYS AND ' \
                       'issuetype = "Release (conf)" AND ' \
                       '(status not in (Closed, Resolved) OR updated >= startOfDay() ' \
                       'AND status in (Resolved)) AND ' \
                       'text ~ возвращена ORDER BY priority DESC, Rank ASC, key ASC'

jira_resolved_today = 'project = ADMSYS AND ' \
                      'issuetype = "Release (conf)" AND ' \
                      'status = Resolved AND updated >= startOfDay() AND ' \
                      'resolution not in (Rollback) ' \
                      'ORDER BY priority DESC, Rank ASC, key ASC'

jira_rollback_today = 'project = ADMSYS AND ' \
                      'issuetype = "Release (conf)" AND ' \
                      'resolutiondate >= startOfDay() AND ' \
                      'updated >= startOfDay() AND ' \
                      'resolution = Rollback ' \
                      'ORDER BY priority DESC, Rank ASC, key ASC'

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

api = 'http://xerxes-api-v1/api-v1'
api_chat_id = f'{api}/chat-id'
api_aerospike_read = f'{api}/aerospike/read'
api_aerospike_write = f'{api}/aerospike/write'
api_tg_send = f'{api}/tg/send'

#MySQL configuration
db_host = 'mysql.xerxes.svc.ugr-base1.kube.yamoney.ru'
db_user = getenv('secret_mysql_user')
db_pass = getenv('secret_mysql_pass')
db_name = 'xerxes'

# AD configuration
ad_host = 'ivan-voucher.yamoney.ru'
base_dn = 'OU=Сотрудники Компании,DC=yamoney,DC=ru'
ldap_filter = '(&(objectCategory=person)(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))'
ldap_attrs = ['cn','sAMAccountName','distinguishedName','extensionattribute4','memberOf','mail']

informer = 'http://ugr-informer1.admsys.yamoney.ru'
informer_send_message_url = f'{informer}/send_message'
informer_inform_duty_url = f'{informer}/inform_duty'