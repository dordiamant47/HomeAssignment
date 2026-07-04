"""
Tests for build_metrics_runtime.

These are NOT mocked - they build a real temporalio.runtime.Runtime with a
real Prometheus exporter bound to a real port, and scrape it with a real
HTTP request, exactly the way a cluster's Prometheus would. This works
fully offline: the Prometheus exporter is part of the SDK's local
telemetry pipeline, independent of any gRPC connection to an actual
Temporal server, so no live server or network access is needed to verify
this end to end.

IMPORTANT GOTCHA discovered while writing these tests: the Runtime object
returned by build_metrics_runtime() must be kept alive (assigned to a
variable held for the test's duration) - if the return value is discarded
immediately, the exporter's background thread appears to get torn down
along with it, and the /metrics endpoint stops responding. In production,
`bootstrap.run_worker()` naturally keeps this alive as a local variable for
the worker's entire lifetime, so this isn't a real-world concern there -
but it's exactly the kind of thing that would silently break metrics in a
worker if someone refactored run_worker() to not hold onto the Runtime
object it builds.
"""

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_sdk.metrics import build_metrics_runtime  # noqa: E402


def _scrape(port: int, retries: int = 20, delay: float = 0.1) -> tuple[int, str, str | None]:
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2)
            return resp.status, resp.read().decode(), resp.headers.get("Content-Type")
        except (urllib.error.URLError, ConnectionError) as exc:
            last_error = exc
            time.sleep(delay)
    raise AssertionError(f"metrics endpoint on port {port} never became reachable: {last_error}")


class TestBuildMetricsRuntime:
    def test_metrics_endpoint_is_reachable(self, unused_tcp_port):
        runtime = build_metrics_runtime(unused_tcp_port)  # noqa: F841 - must stay alive; see module docstring note

        status, _body, content_type = _scrape(unused_tcp_port)

        assert status == 200
        # Standard Prometheus text exposition format content type.
        assert content_type is not None and "text/plain" in content_type

    def test_a_recorded_metric_actually_appears_in_scrape_output(self, unused_tcp_port):
        runtime = build_metrics_runtime(unused_tcp_port)

        meter = runtime.metric_meter
        counter = meter.create_counter(
            "sdk_test_counter", description="proves the exposition pipeline works end to end"
        )
        counter.add(3)
        time.sleep(0.2)

        _status, body, _content_type = _scrape(unused_tcp_port)

        assert "sdk_test_counter" in body
        assert "3" in body

    def test_two_runtimes_on_different_ports_dont_collide(
        self, unused_tcp_port, unused_tcp_port_2
    ):
        runtime_a = build_metrics_runtime(unused_tcp_port)  # noqa: F841
        runtime_b = build_metrics_runtime(unused_tcp_port_2)  # noqa: F841

        status_a, _, _ = _scrape(unused_tcp_port)
        status_b, _, _ = _scrape(unused_tcp_port_2)

        assert status_a == 200
        assert status_b == 200
