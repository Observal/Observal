{{/*
SPDX-FileCopyrightText: 2026 Ravi Chopra <shivamchopra1234567890@gmail.com>
SPDX-License-Identifier: AGPL-3.0-only
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "observal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "observal.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label.
*/}}
{{- define "observal.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "observal.labels" -}}
helm.sh/chart: {{ include "observal.chart" . }}
{{ include "observal.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels.
*/}}
{{- define "observal.selectorLabels" -}}
app.kubernetes.io/name: {{ include "observal.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name for the init Job.
*/}}
{{- define "observal.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (printf "%s-init" (include "observal.fullname" .)) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding all sensitive env vars.
*/}}
{{- define "observal.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secret" (include "observal.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Name of the Secret holding JWT signing keys (created by init Job).
*/}}
{{- define "observal.jwtSecretName" -}}
{{- printf "%s-jwt-keys" (include "observal.fullname" .) }}
{{- end }}

{{/*
Name of the ConfigMap holding non-sensitive env vars.
*/}}
{{- define "observal.configMapName" -}}
{{- printf "%s-config" (include "observal.fullname" .) }}
{{- end }}

{{/*
Image pull policy helper. Takes a dict with repository, tag, pullPolicy.
*/}}
{{- define "observal.image" -}}
{{- $registry := .global.imageRegistry -}}
{{- $repo := .image.repository -}}
{{- $tag := .image.tag | default "latest" -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end }}

{{/*
Standard initContainer: wait for Postgres readiness.
*/}}
{{- define "observal.initWaitPostgres" -}}
{{- if .Values.postgresql.enabled }}
- name: wait-for-postgres
  image: postgres:16
  imagePullPolicy: IfNotPresent
  command:
    - sh
    - -c
    - |
      until pg_isready -h {{ include "observal.fullname" . }}-db -U postgres; do
        echo "Waiting for Postgres..."; sleep 2;
      done
  env:
    - name: PGPASSWORD
      valueFrom:
        secretKeyRef:
          name: {{ include "observal.secretName" . }}
          key: POSTGRES_PASSWORD
{{- end }}
{{- end }}

{{/*
Standard initContainer: wait for ClickHouse readiness.
*/}}
{{- define "observal.initWaitClickhouse" -}}
{{- if .Values.clickhouse.enabled }}
- name: wait-for-clickhouse
  image: curlimages/curl:8.8.0
  imagePullPolicy: IfNotPresent
  command:
    - sh
    - -c
    - |
      until curl -sf http://{{ include "observal.fullname" . }}-clickhouse:8123/ping; do
        echo "Waiting for ClickHouse..."; sleep 2;
      done
{{- end }}
{{- end }}

{{/*
Standard initContainer: wait for Redis readiness.
*/}}
{{- define "observal.initWaitRedis" -}}
{{- if .Values.redis.enabled }}
- name: wait-for-redis
  image: redis:7-alpine
  imagePullPolicy: IfNotPresent
  command:
    - sh
    - -c
    - |
      until redis-cli -h {{ include "observal.fullname" . }}-redis ping | grep -q PONG; do
        echo "Waiting for Redis..."; sleep 2;
      done
{{- end }}
{{- end }}

{{/*
Standard initContainer: wait for init Job completion.
Polls the Job's succeeded count via the K8s API using the init ServiceAccount.
*/}}
{{- define "observal.initWaitInitJob" -}}
- name: wait-for-init
  image: bitnami/kubectl:latest
  imagePullPolicy: IfNotPresent
  command:
    - sh
    - -c
    - |
      JOB="{{ include "observal.fullname" . }}-init"
      NS="{{ .Release.Namespace }}"
      echo "Waiting for init Job $JOB to complete..."
      until [ "$(kubectl get job $JOB -n $NS -o jsonpath='{.status.succeeded}' 2>/dev/null)" = "1" ]; do
        echo "  init Job not yet succeeded, retrying in 5s..."; sleep 5;
      done
      echo "Init Job completed."
{{- end }}

{{/*
Standard container security context.
*/}}
{{- define "observal.securityContext" -}}
securityContext:
  allowPrivilegeEscalation: false
  runAsUser: 1001
  runAsGroup: 1001
  seccompProfile:
    type: RuntimeDefault
{{- end }}

{{/*
Standard pod security context.
*/}}
{{- define "observal.podSecurityContext" -}}
securityContext:
  seccompProfile:
    type: RuntimeDefault
{{- end }}
