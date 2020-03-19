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

staff_url = 'https://xerxes-census:8444'

api = 'http://xerxes-api-v1/api-v1'
api_chat_id = f'{api}/chat-id'
api_aerospike_read = f'{api}/aerospike/read'
api_aerospike_write = f'{api}/aerospike/write'
api_tg_send = f'{api}/tg/send'

department_id = {'group-admsys': 90299, 'b-platform': 74126, 'group-project': 53652, 'depart-project': 53651,
                 'group-analytics': 53653, 'depart-mnt': 158, 'group-devops': 67645,
                 'group_dba': 90289, 'group_externall_mnt': 86039, 'group_internall_it': 80472,
                 'group_noc': 81241, 'group_ip-telephone': 81244, 'group_datacenter': 81245,
                 'group_bd_microsoft': 81246, 'group_virtualization_microsoft': 81247,
                 'head_monitoring': 46554, 'group_monitoring': 1268, 'group_tech_mnt': 22240,
                 'depart_proccessing':33997, 'group_support_proccessing': 30131,
                 'core_dev': 74328, 'f-platform': 989, 'group_qa': 170, 'group_mobile_qa': 53655,
                 'group_integration_qa': 53656, 'group_perfomance_qa': 53657, 'group_core_qa': 53658,
                 'group_bi': 990, 'head_mobile_dev': 8161, 'mobile_dev_ios': 67639,
                 'mobile_dev_android': 67641, 'jira_group': 47639, 'e-commerce_group': 156,
                 'group_security': 345, 'ecommerce_tech': 40194, 'it-director': 57881, 'b2b': 116361, 
                 'yandex_money_com_ecommerce_tech': 39918, 'yandex_money_com_ecommerce_tech': 39918,
                 'yandex_money_com_ecommerce_vip_supp_shopmaster': 40194, 'yandex_money_com_ecommerce_vip_supp': 32477}
