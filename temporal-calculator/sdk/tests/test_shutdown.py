import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_sdk.shutdown import install_signal_handlers  # noqa: E402

# On Windows, os.kill(pid, SIGTERM) calls TerminateProcess and kills the
# process outright instead of delivering a catchable signal, so these tests
# can't simulate signal delivery there the way they can on POSIX.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="os.kill(SIGTERM) terminates the process on Windows"
)


@pytest.mark.asyncio
async def test_sigterm_sets_shutdown_event():
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    install_signal_handlers(loop, shutdown_event)
    try:
        assert not shutdown_event.is_set()

        os.kill(os.getpid(), signal.SIGTERM)

        # Give the loop a beat to dispatch the signal callback.
        await asyncio.wait_for(shutdown_event.wait(), timeout=2)

        assert shutdown_event.is_set()
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        loop.remove_signal_handler(signal.SIGINT)


@pytest.mark.asyncio
async def test_sigint_sets_shutdown_event():
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    install_signal_handlers(loop, shutdown_event)
    try:
        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.wait_for(shutdown_event.wait(), timeout=2)
        assert shutdown_event.is_set()
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        loop.remove_signal_handler(signal.SIGINT)
