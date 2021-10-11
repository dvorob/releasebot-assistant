{{ $conf := .Values.releasebot }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "releasebot.fullname" . }}
  labels:
    {{- include "releasebot.labels" . | nindent 4 }}
---
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "releasebot.fullname" . }}
data:
  exchange_pass: {{ $conf.secrets.exchange.pass | b64enc | quote }}
  exchange_user: {{ $conf.secrets.exchange.user | b64enc | quote }}
  jenkins_base_pass: {{ $conf.secrets.jenkins.base_pass | b64enc | quote }}
  jenkins_base_token: {{ $conf.secrets.jenkins.base_token | b64enc | quote }}
  jenkins_base_user: {{ $conf.secrets.jenkins.base_user | b64enc | quote }}
  jenkins_pass: {{ $conf.secrets.jenkins.pass | b64enc | quote }}
  jenkins_pcidss_pass: {{ $conf.secrets.jenkins.pcidss_pass | b64enc | quote }}
  jenkins_pcidss_token: {{ $conf.secrets.jenkins.pcidss_token | b64enc | quote }}
  jenkins_pcidss_user: {{ $conf.secrets.jenkins.pcidss_user | b64enc | quote }}
  jira_pass: {{ $conf.secrets.jira.pass | b64enc | quote }}
  jira_user: {{ $conf.secrets.jira.user | b64enc | quote }}
  postgres_pass: {{ $conf.secrets.postgres.pass | b64enc | quote }}
  postgres_user: {{ $conf.secrets.postgres.user | b64enc | quote }}
  staff_token: {{ $conf.secrets.staff.token | b64enc | quote }}
  telegram_value: {{ $conf.secrets.telegram.value | b64enc | quote }}
  zabbix_pass: {{ $conf.secrets.zabbix.pass | b64enc | quote }}
  zabbix_user: {{ $conf.secrets.zabbix.user | b64enc | quote }}
  