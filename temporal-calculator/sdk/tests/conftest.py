import socket

import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def unused_tcp_port() -> int:
    """Return a free TCP port on localhost for tests that spin up a real
    HTTP server on a background thread."""
    return _free_port()


@pytest.fixture
def unused_tcp_port_2() -> int:
    """A second, distinct free port - for tests that need health and
    metrics servers running simultaneously on different ports."""
    return _free_port()
