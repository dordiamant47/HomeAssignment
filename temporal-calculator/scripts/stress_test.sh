#!/usr/bin/env bash
#
# Fires a Job running load_generator.py (skewed 90% toward '+') against the
# cluster deploy.sh already stood up, then watches `add-worker`'s KEDA
# ScaledObject scale it up while the other 4 activity workers stay at their
# floor - the actual proof of "independent per-operator scaling."
#
# Usage:
#   ./scripts/stress_test.sh                  # 180s, concurrency 50, defaults
#   STRESS_DURATION_SECONDS=300 STRESS_CONCURRENCY=100 ./scripts/stress_test.sh

set -euo pipefail

TEMPORAL_NAMESPACE="temporal"
CALCULATOR_NAMESPACE="calculator"
IMAGE_TAG="calculator:local"
DURATION="${STRESS_DURATION_SECONDS:-180}"
CONCURRENCY="${STRESS_CONCURRENCY:-50}"
JOB_NAME="calculator-stress-test"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

for tool in kubectl; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: '$tool' is required but not found on PATH." >&2
        exit 1
    fi
done

# Re-discover the frontend Service the same way deploy.sh does, rather than
# requiring the caller to know/pass it - this script should work standalone
# any time after deploy.sh has run.
log "Discovering Temporal frontend Service"
FRONTEND_SVC="$(kubectl get svc -n "${TEMPORAL_NAMESPACE}" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    | grep -i frontend | grep -v headless | head -n1)"

if [ -z "${FRONTEND_SVC}" ]; then
    echo "ERROR: could not find a Temporal frontend Service. Has deploy.sh run yet?" >&2
    exit 1
fi
TEMPORAL_HOST="${FRONTEND_SVC}.${TEMPORAL_NAMESPACE}.svc.cluster.local:7233"
log "Temporal frontend: ${TEMPORAL_HOST}"

log "Cleaning up any previous stress test Job"
kubectl delete job "${JOB_NAME}" -n "${CALCULATOR_NAMESPACE}" --ignore-not-found

log "Launching load generator Job (duration=${DURATION}s concurrency=${CONCURRENCY})"
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${CALCULATOR_NAMESPACE}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: load-generator
          image: ${IMAGE_TAG}
          args: ["load-generator"]
          env:
            - name: TEMPORAL_HOST
              value: "${TEMPORAL_HOST}"
            - name: STRESS_DURATION_SECONDS
              value: "${DURATION}"
            - name: STRESS_CONCURRENCY
              value: "${CONCURRENCY}"
            - name: STRESS_SKEW_OP
              value: "+"
            - name: STRESS_SKEW_RATIO
              value: "0.9"
EOF

log "Streaming load generator logs (this blocks until the Job finishes)"
kubectl wait --for=condition=ready pod -l job-name="${JOB_NAME}" -n "${CALCULATOR_NAMESPACE}" --timeout=60s
kubectl logs -f "job/${JOB_NAME}" -n "${CALCULATOR_NAMESPACE}" &
LOGS_PID=$!

log "Watching scaling status - expect add-worker to climb while the other 4 stay flat"
log "(Ctrl+C stops watching, the Job keeps running in the background)"
kubectl get scaledobject,hpa -n "${CALCULATOR_NAMESPACE}" -w &
WATCH_PID=$!

kubectl wait --for=condition=complete "job/${JOB_NAME}" -n "${CALCULATOR_NAMESPACE}" --timeout="$((DURATION + 120))s" || true

kill "${WATCH_PID}" 2>/dev/null || true
wait "${LOGS_PID}" 2>/dev/null || true

log "Final snapshot:"
kubectl get scaledobject,hpa -n "${CALCULATOR_NAMESPACE}"

log "Stress test complete. Compare add-worker's CURRENT/REPLICAS column against the other 4 workers above."
