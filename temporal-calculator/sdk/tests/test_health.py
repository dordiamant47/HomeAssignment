import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_sdk.health import HealthState, start_health_server  # noqa: E402


def _get(port: int, path: str) -> tuple[int, bytes]:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class TestHealthState:
    def test_defaults_to_not_ready(self):
        state = HealthState()
        assert state.ready is False

    def test_set_ready_toggles(self):
        state = HealthState()
        state.set_ready(True)
        assert state.ready is True
        state.set_ready(False)
        assert state.ready is False


class TestHealthServer:
    def test_live_always_200(self, unused_tcp_port):
        state = HealthState()
        server = start_health_server(state, port=unused_tcp_port)
        try:
            status, body = _get(unused_tcp_port, "/live")
            assert status == 200
            assert body == b"ok"
        finally:
            server.shutdown()

    def test_ready_returns_503_before_ready(self, unused_tcp_port):
        state = HealthState()
        server = start_health_server(state, port=unused_tcp_port)
        try:
            status, _ = _get(unused_tcp_port, "/ready")
            assert status == 503
        finally:
            server.shutdown()

    def test_ready_returns_200_once_ready(self, unused_tcp_port):
        state = HealthState()
        server = start_health_server(state, port=unused_tcp_port)
        try:
            state.set_ready(True)
            status, body = _get(unused_tcp_port, "/ready")
            assert status == 200
            assert body == b"ready"
        finally:
            server.shutdown()

    def test_unknown_path_404(self, unused_tcp_port):
        state = HealthState()
        server = start_health_server(state, port=unused_tcp_port)
        try:
            status, _ = _get(unused_tcp_port, "/nonexistent")
            assert status == 404
        finally:
            server.shutdown()
