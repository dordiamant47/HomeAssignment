#!/usr/bin/env bash
#
# Single entrypoint for the one calculator image, dispatching to one of
# three roles based on the first argument:
#
#   activity-worker   -> runs activity_worker_main.py
#                        (deployed 5x, differing only by TEMPORAL_TASK_QUEUE)
#   workflow-worker    -> runs workflow_worker_main.py
#   starter            -> runs starter.py "<expression>"
#   load-generator     -> runs load_generator.py (used by stress_test.sh)
#
# This is what makes "5 identical activity Deployments + 1 workflow
# Deployment, same image" possible: the Helm chart's matrix only ever
# changes the container's `args` (role) and env vars (TEMPORAL_TASK_QUEUE),
# never the image itself.
#
# Testability: set ENTRYPOINT_DRY_RUN=1 to print the resolved command
# instead of exec'ing it - this is how this script gets unit tested without
# a real Temporal connection or even Python being invoked at all.

set -euo pipefail

ROLE="${1:-activity-worker}"
if [ "$#" -gt 0 ]; then
    shift
fi

case "$ROLE" in
    activity-worker)
        CMD=(python /app/calculator/activity_worker_main.py)
        ;;
    workflow-worker)
        CMD=(python /app/calculator/workflow_worker_main.py)
        ;;
    starter)
        CMD=(python /app/calculator/starter.py "$@")
        ;;
    load-generator)
        CMD=(python /app/calculator/load_generator.py)
        ;;
    *)
        echo "Unknown role: '${ROLE}'" >&2
        echo "Usage: entrypoint.sh {activity-worker|workflow-worker|starter|load-generator} [args...]" >&2
        exit 1
        ;;
esac

if [ "${ENTRYPOINT_DRY_RUN:-0}" = "1" ]; then
    printf '%s\n' "${CMD[@]}"
    exit 0
fi

exec "${CMD[@]}"
