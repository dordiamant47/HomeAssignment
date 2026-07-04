"""
Zero-code Kubernetes health probes.

Every worker process (workflow worker or any activity worker) gets a
background HTTP server exposing:

  GET /live   -> 200 as long as the process/thread is alive at all
  GET /ready  -> 200 once the Temporal worker has successfully connected
                 and started polling its task queue; 503 otherwise
                 (including during graceful shutdown, so K8s stops routing
                 new work to a pod that's draining)

This is intentionally "zero-code" from the calculator application's point
of view: business logic never touches this module directly. Only
`bootstrap.run_worker()` wires it up, so upgrading the SDK version brings
these probes to every worker without changing a single line of
calculator/workflow or calculator/activity code.

Implementation notes:
  - Uses only the Python standard library (http.server) running in a daemon
    thread, so the SDK carries no extra HTTP framework dependency.
  - State is a tiny thread-safe flag object (`HealthState`) that
    `bootstrap.py` flips as the worker's lifecycle progresses.
"""

from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)


class HealthState:
    """Thread-safe readiness flag shared between the worker lifecycle and
    the HTTP handler."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = False

    def set_ready(self, ready: bool) -> None:
        with self._lock:
            self._ready = ready

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._ready


def _make_handler(state: HealthState) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - required name by http.server
            if self.path == "/live":
                self._respond(200, b"ok")
            elif self.path == "/ready":
                if state.ready:
                    self._respond(200, b"ready")
                else:
                    self._respond(503, b"not ready")
            else:
                self._respond(404, b"not found")

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            # Silence http.server's default stderr access logging; our own
            # structured logger is the source of truth for this process.
            pass

    return HealthHandler


def start_health_server(state: HealthState, port: int = 8080) -> ThreadingHTTPServer:
    """
    Start the /live and /ready HTTP server on a background daemon thread.

    Returns the server instance so callers can call `.shutdown()` on it
    during graceful shutdown.
    """
    handler_cls = _make_handler(state)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler_cls)  # noqa: S104

    thread = threading.Thread(
        target=server.serve_forever, name="health-probe-server", daemon=True
    )
    thread.start()

    logger.info(
        "Health probe server started",
        extra={"port": port, "endpoints": ["/live", "/ready"]},
    )
    return server
