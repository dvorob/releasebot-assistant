{{ $conf := .Values.releasebot }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "releasebot.fullname" . }}
  labels:
    {{- include "releasebot.labels" . | nindent 4 }}
spec:
  replicas: {{ $conf.count_replicas }}
  selector:
    matchLabels:
      app: {{ $conf.name }}
  strategy:
    type: RollingUpdate
  template:
    metadata:
      labels:
        app: {{ $conf.name }}
        app_type: {{ $conf.app_type }}
        app_name: {{ $conf.app_name }}
        log_enabled: {{ $conf.log_enabled | quote }}
        kafka_log_topic: {{ $conf.kafka_log_topic }}
    spec:
      containers:
        - image: {{ $conf.image }}:{{ $conf.tag }}
          name: {{ $conf.name }}
          imagePullPolicy: Always
          resources:
{{ toYaml $conf.resources | indent 12  }}
          envFrom:
            - configMapRef:
                name: {{ include "releasebot.fullname" . }}
            - secretRef:
                name: {{ include "releasebot.fullname" . }}
      nodeSelector:
        node-role.kubernetes.io/node: "true"
