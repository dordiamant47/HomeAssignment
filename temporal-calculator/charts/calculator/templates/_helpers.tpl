{{/*
Fully-qualified resource name for one worker entry in the matrix.
Usage: {{ include "calculator.workerFullname" (dict "root" $ "worker" $worker) }}
*/}}
{{- define "calculator.workerFullname" -}}
{{- printf "%s-%s" .root.Release.Name .worker.name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Labels common to every resource this chart creates, regardless of worker.
*/}}
{{- define "calculator.commonLabels" -}}
app.kubernetes.io/part-of: calculator
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/*
Selector labels for one worker. Used on the Deployment's pod template AND
wherever else (HPA scaleTargetRef, any future Service) needs to reference
that exact same pod set, so these two must always stay in lockstep.
Usage: {{ include "calculator.workerSelectorLabels" (dict "root" $ "worker" $worker) }}
*/}}
{{- define "calculator.workerSelectorLabels" -}}
app.kubernetes.io/name: {{ .worker.name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}
