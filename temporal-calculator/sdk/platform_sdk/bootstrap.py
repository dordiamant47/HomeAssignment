"""
Reusable worker bootstrap.

This is the SINGLE entrypoint that every worker process (the workflow
worker, and every one of the 5 identical activity workers) calls into. It
is what turns "some Python code defining workflows/activities" into "a
production-shaped Kubernetes pod": Temporal connection, structured logging,
health probes, and graceful shutdown are all handled here, once, so none of
that plumbing is duplicated across worker binaries.

The calculator app's own entrypoints (activity_worker_main.py,
workflow_worker_main.py) are expected to be a handful of lines each: import
their workflows/activities, then call `asyncio.run(run_worker(...))`.

Configuration is entirely environment-driven, per the assignment's
requirement that identical worker code differentiate itself purely via env
vars set by Kubernetes:

  TEMPORAL_HOST        - host:port of the Temporal frontend (default: localhost:7233)
  TEMPORAL_NAMESPACE   - Temporal namespace (default: "default")
  TEMPORAL_TASK_QUEUE  - the task queue this worker process should poll (required)
  HEALTH_PORT          - port for /live and /ready (default: 8080)
  LOG_LEVEL            - Python logging level name (default: "INFO")
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Sequence

from temporalio.client import Client
from temporalio.worker import Worker

from platform_sdk.health import HealthState, start_health_server
from platform_sdk.logging import configure_logging
from platform_sdk.metrics import build_metrics_runtime
from platform_sdk.shutdown import install_signal_handlers

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when required worker configuration is missing/invalid."""


@dataclass(frozen=True)
class WorkerConfig:
    temporal_host: str
    temporal_namespace: str
    task_queue: str
    health_port: int
    metrics_port: int


def load_config_from_env(
    *, task_queue_override: str | None = None
) -> WorkerConfig:
    """
    Build a WorkerConfig purely from environment variables.

    `task_queue_override` lets a caller (or a test) pin the task queue
    without touching the environment; in production this is left as None
    and TEMPORAL_TASK_QUEUE must be set.
    """
    task_queue = task_queue_override or os.environ.get("TEMPORAL_TASK_QUEUE")
    if not task_queue:
        raise ConfigError(
            "TEMPORAL_TASK_QUEUE must be set (or task_queue_override provided). "
            "This is how an otherwise-identical worker container knows which "
            "queue to listen to."
        )

    raw_port = os.environ.get("HEALTH_PORT", "8080")
    try:
        health_port = int(raw_port)
    except ValueError as exc:
        raise ConfigError(f"HEALTH_PORT must be an integer, got {raw_port!r}") from exc

    raw_metrics_port = os.environ.get("METRICS_PORT", "9090")
    try:
        metrics_port = int(raw_metrics_port)
    except ValueError as exc:
        raise ConfigError(
            f"METRICS_PORT must be an integer, got {raw_metrics_port!r}"
        ) from exc

    return WorkerConfig(
        temporal_host=os.environ.get("TEMPORAL_HOST", "localhost:7233"),
        temporal_namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
        task_queue=task_queue,
        health_port=health_port,
        metrics_port=metrics_port,
    )


async def run_worker(
    *,
    workflows: Sequence[type] = (),
    activities: Sequence[object] = (),
    config: WorkerConfig | None = None,
) -> None:
    """
    Bootstrap and run a Temporal worker until a shutdown signal arrives.

    A single call to this function is the entire content of a worker
    process's main(): it configures logging, starts the health server,
    connects to Temporal, runs the worker, and drains gracefully on
    SIGTERM/SIGINT.

    Either `workflows` or `activities` (or both) may be empty depending on
    whether this process is the workflow worker or one of the activity
    workers - the caller decides which it's running by what it passes in,
    while everything else (connection, health, shutdown, logging) is
    identical either way.
    """
    configure_logging()
    cfg = config or load_config_from_env()

    logger.info(
        "Starting worker",
        extra={
            "task_queue": cfg.task_queue,
            "temporal_host": cfg.temporal_host,
            "temporal_namespace": cfg.temporal_namespace,
            "workflow_count": len(workflows),
            "activity_count": len(activities),
            "metrics_port": cfg.metrics_port,
        },
    )

    health_state = HealthState()
    health_server = start_health_server(health_state, port=cfg.health_port)

    shutdown_event = asyncio.Event()
    install_signal_handlers(asyncio.get_running_loop(), shutdown_event)

    try:
        metrics_runtime = build_metrics_runtime(cfg.metrics_port)
        client = await Client.connect(
            cfg.temporal_host,
            namespace=cfg.temporal_namespace,
            runtime=metrics_runtime,
        )
    except Exception:
        logger.exception(
            "Failed to connect to Temporal",
            extra={"temporal_host": cfg.temporal_host},
        )
        health_server.shutdown()
        raise

    worker = Worker(
        client,
        task_queue=cfg.task_queue,
        workflows=list(workflows),
        activities=list(activities),
    )

    async with worker:
        # The worker is now actively polling its task queue - only now do we
        # report readiness to Kubernetes.
        health_state.set_ready(True)
        logger.info("Worker is ready and polling", extra={"task_queue": cfg.task_queue})

        await shutdown_event.wait()

        # Immediately stop advertising readiness so K8s (via the Service)
        # stops sending new traffic/work our way while we drain. The
        # `async with worker` block's __aexit__ (triggered as this `with`
        # scope ends below) performs Temporal's own graceful drain: it stops
        # polling for new tasks but lets any in-flight activity/workflow
        # task finish before the worker fully shuts down.
        health_state.set_ready(False)
        logger.info("Draining in-flight tasks before shutdown", extra={"task_queue": cfg.task_queue})

    health_server.shutdown()
    logger.info("Worker shut down cleanly", extra={"task_queue": cfg.task_queue})
