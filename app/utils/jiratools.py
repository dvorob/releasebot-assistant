#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обёртки вокруг методов Jira.
"""
from jira import JIRA
from utils import logging
from enum import Enum
import jira.exceptions
import config
import re

__all__ = ['JiraConnection']
logger = logging.setup()

class JiraTransitions(Enum):
    TODO_WAIT = '321'
    WAIT_TODO = '41'
    TODO_PARTIAL = '191'
    PARTIAL_CONFIRM = '211'
    PARTIAL_RESOLVED = '241'
    PARTIAL_WAIT = '321'
    CONFIRM_FULL = '101'
    CONFIRM_WAIT = '321'
    FULL_RESOLVED = '241'
    FULL_WAIT = '321'

class JiraConnection:

    def __init__(self):
        self.options = {
            'server': config.jira_host, 'verify': False
        }
        self.jira = JIRA(self.options, basic_auth=(config.jira_user, config.jira_pass))

    def issue(self, issue: str) -> jira.Issue:
        """
            Get Jira task information
        """
        try:
            issue = self.jira.issue(issue)
            return issue
        except Exception as e:
            logger.exception('jira issue %s', e)

    def search_issues(self, query: str) -> dict:
        """
            Get list of Jira tasks
        """
        try:
            issues = self.jira.search_issues(query, maxResults=1000)
            return issues
        except Exception as e:
            logger.exception('Error in JIRATOOLS SEARCH ISSUES %s', e)

    def add_comment(self, jira_issue_id: str, comment: str):
        """
            Add comment to Jira task
        """
        self.jira.add_comment(jira_issue_id, comment)

    def comments(self, jira_issue_id: str):
        """
            Add comment to Jira task
        """
        self.jira.comments(jira_issue_id)

    def assign_issue(self, jira_issue_id: str, for_whom_assign: str):
        """
            Assign task to for_whom_assign
            :param jira_issue_id - ADMSYS-12345
            :param for_whom_assign - None, Xerxes, anybody else
        """
        self.jira.assign_issue(jira_issue_id, for_whom_assign)

    def transition_issue(self, jira_issue_id: str, transition_id: str, assignee: str = None):
        try:
            if assignee:
                self.jira.transition_issue(jira_issue_id, transition_id, assignee=assignee)
            else:
                self.jira.transition_issue(jira_issue_id, transition_id)
        except jira.exceptions.JIRAError as err:
            logger.error('transition_issue %s', err)

    def transition_issue_with_resolution(self, jira_issue_id: str, transition_id: str, resolution: str):
        try:
            self.jira.transition_issue(jira_issue_id, transition_id, resolution=resolution)
        except jira.exceptions.JIRAError as err:
            logger.error('transition_issue %s', err)

#########################################################################################
#        Custom functions
#########################################################################################

def jira_get_approvers_list(issue_key: str) -> list:
    """
       Отобрать список имейлов согласующих из jira_таски и обрезать от них email, оставив только account_name
    """
    try:
        issue = JiraConnection().issue(issue_key)
        approvers = [re.sub('@.*$', '', item.emailAddress) for item in issue.fields.customfield_15408
                    if "@" in item.emailAddress]
        logger.info('-- JIRA GET APPROVERS LIST %s %s', issue, approvers)
        return approvers
    except Exception as e:
        logger.exception('Exception in JIRA GET APPROVERS LIST %s', e)

def jira_get_components() -> list:
    issues = JiraConnection().search_issues(config.jira_filter_components)
    components = []
    # Отберём компоненты по фильтру
    # Имя компоненты возьмем из поля RepoSlug (19193), уберём префиксы, если они есть
    # Команда - в поле 16890.
    try:
        for issue in issues:
            if issue.fields.customfield_19193 != None:
                app_name = (issue.fields.customfield_19193).replace('yamoney-backend-', '').replace('yamoney-frontend-', '')
            else:
                app_name = issue.fields.summary
            if issue.fields.customfield_16890 != None:
                dev_team = issue.fields.customfield_16890.key
            if issue.fields.customfield_19192 != None:
                repo_project = issue.fields.customfield_19192.value
            components.append({'app_name': app_name, 'dev_team': dev_team, 'repo_project': repo_project})
        return components
    except Exception as e:
        logger.exception(f'Error in jira get components {str(e)}')
        