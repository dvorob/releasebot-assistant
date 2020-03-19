import requests

qbot_base_url = 'http://qbot.xerxes.svc.alpha.kube.yamoney.ru'


def send_comming_soon_release_notification(recipient: str, name: str, admsys_link: str):
    json_payload = {
        'event_type': 'rl_coming_soon',
        'recipient': recipient,
        'event_data': {
            'rl': {
                'name': name,
                'admsys_link': admsys_link
            }
        }
    }
    url = "%s/notify" % qbot_base_url
    requests.post(url, json=json_payload)
