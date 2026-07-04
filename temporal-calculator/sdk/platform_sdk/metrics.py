"""
Basic metrics for every worker process, via the Temporal SDK's own
built-in Prometheus exporter - not a hand-rolled metrics library.

Passing a Runtime configured with PrometheusConfig into Client.connect()
gets every worker a real, standards-compliant /metrics endpoint: task poll
counts, activity execution counts and latencies, workflow task latencies,
sticky cache stats, and more - entirely for free, with zero
instrumentation code anywhere in calculator/. This is deliberately the
same "upgrade the SDK, get it for free" pattern as the /live and /ready
probes in health.py: bump platform_sdk's version, every worker gets
metrics, no business logic touched.

The alternative - hand-rolling counters with something like
prometheus_client, incrementing them manually inside compute() or
CalculatorWorkflow.run() - was deliberately rejected: it would require
instrumentation code inside the calculator app itself (violating the
"zero-code" principle used everywhere else in this SDK), and would only
ever cover the handful of events we remembered to instrument, versus the
much broader set of Core SDK internals this approach exposes automatically.
"""

from __future__ import annotations

import logging

from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig

logger = logging.getLogger(__name__)


def build_metrics_runtime(port: int) -> Runtime:
    """
    Build a Temporal Runtime with a Prometheus metrics endpoint bound to
    0.0.0.0:<port>/metrics.

    Pass the result to `Client.connect(..., runtime=build_metrics_runtime(port))`.
    This starts a real HTTP server (independent of the Temporal gRPC
    connection itself - metrics are exposed even before/if the client
    successfully connects to a server).
    """
    bind_address = f"0.0.0.0:{port}"
    logger.info(
        "Starting Prometheus metrics endpoint", extra={"port": port, "path": "/metrics"}
    )
    runtime = Runtime(
        telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address=bind_address))
    )
    # Merely accessing metric_meter was NOT sufficient to reliably bring up
    # the exporter's HTTP listener (confirmed empirically - see git history
    # of sdk/tests/test_metrics.py for the failed attempt). Actually
    # recording one metric value is what triggers it. This dummy counter is
    # otherwise meaningless; it exists purely to force initialization so
    # readiness of the /metrics endpoint doesn't depend on some other code
    # path happening to record a real metric first.
    runtime.metric_meter.create_counter(
        "platform_sdk_metrics_exporter_initialized"
    ).add(1)
    return runtime
