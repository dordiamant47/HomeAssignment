"""
Structured JSON logging for all platform workers.

Every log line emitted by a worker process (workflow worker or any of the
identical activity workers) goes through this configuration, so logs are
uniformly machine-parseable regardless of which queue/role the pod is
running as. This is what a log aggregator (CloudWatch, Loki, etc.) expects
in a Kubernetes environment.

Usage:
    from platform_sdk.logging import configure_logging
    configure_logging()  # call once, at process start, before anything else logs
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any


class JsonFormatter(logging.Formatter):
    """
    Formats each log record as a single-line JSON object.

    Extra context passed via `logger.info(msg, extra={...})` is merged into
    the top-level JSON object, so callers can attach fields like
    `task_queue`, `workflow_id`, or `activity_id` without any special-casing
    here.
    """

    # Standard LogRecord attributes we should NOT re-emit as "extra" fields,
    # since they're already represented explicitly below.
    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            ) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str | None = None) -> None:
    """
    Configure the root logger to emit structured JSON to stdout.

    `level` defaults to the LOG_LEVEL env var, falling back to "INFO".
    Safe to call multiple times (idempotent: clears and resets handlers).
    """
    resolved_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    root = logging.getLogger()
    root.setLevel(resolved_level)

    # Remove any pre-existing handlers so re-configuration doesn't duplicate
    # log lines (e.g. if a test or a library called basicConfig earlier).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
