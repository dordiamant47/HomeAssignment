#!/usr/bin/env bash
#
# Stands up everything: Kind cluster -> metrics-server -> KEDA -> a small
# Prometheus -> a throwaway Postgres -> the official Temporal Helm chart ->
# our calculator image + chart.
#
# Idempotent - safe to re-run. Usage:
#   ./scripts/deploy.sh          # deploy
#   ./scripts/deploy.sh --fresh  # delete the Kind cluster first

set -euo pipefail

CLUSTER_NAME="calculator-dev"
TEMPORAL_NS="temporal"
CALC_NS="calculator"
TEMPORAL_CHART_VERSION="1.5.0"
IMAGE_TAG="calculator:local"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }

for tool in kind kubectl helm docker; do
    command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: '$tool' not found on PATH." >&2; exit 1; }
done

[ "${1:-}" = "--fresh" ] && { log "Deleting cluster '${CLUSTER_NAME}'"; kind delete cluster --name "${CLUSTER_NAME}" || true; }

# 1. Kind cluster
if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
    log "Kind cluster already exists, reusing it"
else
    log "Creating Kind cluster"
    kind create cluster --name "${CLUSTER_NAME}"
fi
kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null

# 2. metrics-server - Kind doesn't ship this, and KEDA's cpu/memory
#    triggers need it just like plain HPA would.
if ! kubectl get deployment metrics-server -n kube-system >/dev/null 2>&1; then
    log "Installing metrics-server"
    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
    kubectl patch deployment metrics-server -n kube-system --type=json \
        -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
fi
kubectl rollout status deployment/metrics-server -n kube-system --timeout=120s

# 3. KEDA - the actual autoscaling engine (replaces plain HPA in our chart)
log "Installing/upgrading KEDA"
helm repo add kedacore https://kedacore.github.io/charts >/dev/null 2>&1 || true
helm repo update kedacore >/dev/null
helm upgrade --install keda kedacore/keda --namespace keda --create-namespace --wait

# 4. A small Prometheus - KEDA's Prometheus scaler needs a real instance
#    to query for the latency/request-rate triggers.
log "Applying dev Prometheus"
kubectl apply -f "${ROOT}/scripts/prometheus-dev.yaml"
kubectl rollout status deployment/prometheus -n monitoring --timeout=120s

# 5. Throwaway Postgres for Temporal's persistence (the official chart
#    ships no database of its own).
log "Applying dev Postgres"
kubectl create namespace "${TEMPORAL_NS}" --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic temporal-db-secret -n "${TEMPORAL_NS}" \
    --from-literal=password="dev-only-not-a-real-secret" \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "${ROOT}/scripts/postgres-dev.yaml"
kubectl rollout status deployment/postgres -n "${TEMPORAL_NS}" --timeout=120s

# 6. Official Temporal server
log "Installing/upgrading Temporal server (chart ${TEMPORAL_CHART_VERSION})"
helm upgrade --install temporal temporal \
    --repo https://go.temporal.io/helm-charts --version "${TEMPORAL_CHART_VERSION}" \
    --namespace "${TEMPORAL_NS}" -f "${ROOT}/scripts/temporal-values.yaml" \
    --timeout 900s --wait

# Discover the frontend Service name rather than hardcoding a guess.
FRONTEND_SVC="$(kubectl get svc -n "${TEMPORAL_NS}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    | grep -i frontend | grep -v headless | head -n1)"
[ -z "${FRONTEND_SVC}" ] && { echo "ERROR: no Temporal frontend Service found." >&2; exit 1; }
TEMPORAL_HOST="${FRONTEND_SVC}.${TEMPORAL_NS}.svc.cluster.local:7233"
log "Temporal frontend: ${TEMPORAL_HOST}"

# 7. Build + load our image
log "Building calculator image"
docker build -f "${ROOT}/calculator/Dockerfile" -t "${IMAGE_TAG}" "${ROOT}"
kind load docker-image "${IMAGE_TAG}" --name "${CLUSTER_NAME}"

# 8. Our chart
log "Installing/upgrading the calculator chart"
kubectl create namespace "${CALC_NS}" --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install calculator "${ROOT}/charts/calculator" \
    --namespace "${CALC_NS}" --set temporal.host="${TEMPORAL_HOST}" \
    --timeout 300s --wait

log "Waiting on all calculator Deployments"
for d in $(kubectl get deployments -n "${CALC_NS}" -o name); do
    kubectl rollout status "$d" -n "${CALC_NS}" --timeout=180s
done

log "Done."
echo "Try it:"
echo "  kubectl run -it --rm starter --image=${IMAGE_TAG} --restart=Never -n ${CALC_NS} \\"
echo "    --overrides='{\"spec\":{\"containers\":[{\"name\":\"starter\",\"image\":\"${IMAGE_TAG}\",\"args\":[\"starter\",\"1 + 5^3 * (2 - 5)\"],\"env\":[{\"name\":\"TEMPORAL_HOST\",\"value\":\"${TEMPORAL_HOST}\"}]}]}}'"
