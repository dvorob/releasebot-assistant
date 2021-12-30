import consul
import yaml
import requests
from jinja2 import Template
from utils import logging


class ServiceDiscoveryAppRemotesTable:

    def __init__(self, wiki_username: str, wiki_password: str):
        self.consul_servers = {'prod': 'consul.yamoney.ru', 'pcidss': 'consul-pcidss.yooteam.ru'}
        self.session = requests.Session()
        self.session.auth = (wiki_username, wiki_password)
        self.wiki_page_url = 'https://wiki.yooteam.ru/rest/api/content/286591430'
        self.table = []
        self.logger = logging.setup()
        self.template_path = './app/utils/templates/wikitable.j2'

    def _get_all_app_descs(self, consul_dc: str, consul_server: str) -> list:
        """
        Обращается к consul-server для получения desc.yml всех зарегистрированных приложений
        Аргументы:
          consul_dc: str - prod или pcidss
          consul_server: str - fqdn consul-server
        Возвращает:
          app_desct: list - list of dict, dict получен чтением desc.yml из consul
        """
        app_descs = []
        try:
            c = consul.Consul(host=consul_server, port=443, scheme='https', dc=consul_dc)
        except Exception as e:
            self.logger.exception(f'Exception during connection to consul server{consul_server} {str(e)}')
        else:
            apps_list = c.kv.get('app/', dc=consul_dc, keys=True)[1]
            for app in apps_list:
                if 'latest' in app:
                    latest = str(c.kv.get(app, dc=consul_dc)[1].get('Value'), 'utf8')
                    app_addr = app.split('/')
                    app_addr[-1] = latest
                    app_latest_addr = '/'.join(app_addr)+'/description'
                    desc = str(c.kv.get(app_latest_addr, dc=consul_dc)[1].get('Value'), 'utf8')
                    app_descs.append(yaml.load(desc, Loader=yaml.Loader))
            return app_descs

    @staticmethod
    def get_single_app_desc(app: str, consul_server: str, consul_dc: str) -> dict:
        app_desc = []
        c = consul.Consul(host=consul_server, port=443, scheme='https', dc=consul_dc)
        app_vers_list = c.kv.get('app/'+app, dc=consul_dc, keys=True)[1]
        for app in app_vers_list:
            if 'latest' in app:
                latest = str(c.kv.get(app, dc=consul_dc)[1].get('Value'), 'utf8')
                app_addr = app.split('/')
                app_addr[-1] = latest
                app_latest_addr = '/'.join(app_addr)+'/description'
                desc = str(c.kv.get(app_latest_addr, dc=consul_dc)[1].get('Value'), 'utf8')
                app_desc = yaml.load(desc, Loader=yaml.Loader)
        return app_desc

    @staticmethod
    def _get_remotes(desc: dict) -> list:
        """
        Получает список remote из desc.yml и формирует из него список: приложение -> remote
        Принимает:
          desc: dict - loaded desc.yml
        Возвращает:
          list: (dict) - {'name': app name, 'remote': remote app name, 'proto': protocol}
        """
        remotes = []
        remotes_raw = desc['application'].get('remotes', {})

        for app, proto in remotes_raw.items():
            for pr in proto:
                remotes.append({'name': desc['application']['name'],
                                'remote': app,
                                'proto': pr})
        if remotes_raw == {}:
            remotes.append({'name': desc['application']['name'],
                            'remote': ' ',
                            'proto': ' '})
        return remotes

    def _create_table_data(self) -> bool:
        """
        Заполняет список table значениями полученными из key/value c consul_server
        методом _get_all_app_descs и подготовленный методом _get_remotes.
        Возвращает:
          bool - True в случае успеха, False в случае получения исключения
        """
        for consul_dc, consul_server in self.consul_servers.items():
            try:
                desc = self._get_all_app_descs(consul_dc, consul_server)
                for app in desc:
                    self.table += self._get_remotes(app)
            except Exception as e:
                self.logger.exception(f'Exception in _create_table_data {str(e)}')
                return False
        return True

    def create_html_table(self) -> str:
        """
        Создаёт html таблицу по jinja2-шаблону с данымми из table.
        Вовзращает:
          html: str - таблица с фильтром в html
        """
        res = self._create_table_data()
        if res is not False:
            table_template = Template(open(self.template_path, 'r').read())
            html = table_template.render(items=self.table)
            return html
        else:
            self.logger.error("Error in _create_table_data")
            return None

    def push_to_wiki(self, html: str) -> bool:
        """
        Проверяет наличие wiki-страницы по URL, в случае существования обновляет
        содержимое страницы строкой html.
        Принимает:
          html: str - строка с новым содержимым страницы в виде html
        Возвращает:
          bool: True/False в случае успеха/неудачи
        """
        try:
            response = self.session.request(method='GET', url=self.wiki_page_url, verify=False)
        except Exception as e:
            self.logger.exception(f'Exception during connect to wiki {str(e)}')
            return False
        else:
            if response.status_code == 200:
                page_data = response.json()
                payload = {
                    'id': page_data['id'],
                    'type': 'page',
                    'title': 'ServiceDiscovery.AppsRemotes',
                    'body': {'storage': {'value': html, 'representation': 'storage'}},
                    'version': {'number': page_data['version']['number'] + 1}
                }
                try:
                    response = self.session.request(method='PUT', url=self.wiki_page_url, json=payload, verify=False)
                except Exception as e:
                    self.logger.exception(f'Exception during connect to wiki {str(e)}')
                else:
                    if response.status_code == 200:
                        self.logger.info('Wiki-table update: SUCCESS')
                        return True
                    else:
                        self.logger.error(f'Status code: {response.status_code}, raw response: {response.text}')
                        return False
            else:
                self.logger.error(f'Status code: {response.status_code}, raw response: {response.text}')
                return False

