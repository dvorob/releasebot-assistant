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
        self.wiki_page_url = 'https://wiki.yamoney.ru/rest/api/content/286591430'
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
        except:
            self.logger.exception(f'Exception during connection to consul server{consul_server}')
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
    def _get_remotes(desc: dict) -> tuple:
        """
        Получает список remote из desc.yml и формирует из него читаемый
        список строк формата [remote1:proto, remote2:proto, ..., remoteN:proto]
        Принимает:
          desc: dict - loaded desc.yml
        Возвращает:
          tuple: (app_name, remotes) - (str имя приложения, list remote:proto)
        """
        remotes = []
        remotes_raw = desc['application']['remotes']
        for app, proto in remotes_raw.items():
            for pr in proto:
                remotes.append(app+':'+pr)
        return desc['application']['name'], remotes

    def _create_table_data(self) -> bool:
        """
        Заполняет список table значениями полученными из key/value c consul_server
        методом _get_all_app_descs и подготовленный методом _get_remotes.
        Возвращает:
          bool - True в случае успеха, False в случае получения исключения
        """
        for consul_dc, consul_server in self.consul_servers.items():
            try:
                self.table.append(({'app_name': 'base' if consul_dc == 'prod' else consul_dc, 'remotes': ' '}))
                desc = self._get_all_app_descs(consul_dc, consul_server)
                for app in desc:
                    app_name, app_remotes = self._get_remotes(app)
                    self.table.append({'app_name': app_name,
                                       'remotes': ', '.join(app_remotes) if app_remotes != [] else ' '})
            except:
                self.logger.exception('Exception in _create_table_data')
                return False
        return True

    def create_html_table(self) -> str:
        """
        Создаёт html таблицу по jinja2-шаблону с данымми из table.
        Вовзращает:
          html: str - таблица в html
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
        except:
            self.logger.exception('Exception during connect to wiki')
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
                except:
                    self.logger.exception('Exception during connect to wiki')
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
