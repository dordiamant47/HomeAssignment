"""
Graceful shutdown handling, shared by every worker process.

Kubernetes sends SIGTERM to a pod before killing it (and gives it
`terminationGracePeriodSeconds` to exit cleanly). This module wires SIGTERM
and SIGINT to an asyncio.Event so `bootstrap.run_worker()` can:

  1. Flip readiness to False immediately (so K8s stops routing new work to
     this pod via the Service, if applicable).
  2. Let any in-flight activity/workflow task finish.
  3. Cleanly close the Temporal worker's poller and client connection.
  4. Exit 0.

This is intentionally a small, standalone module so it can be unit-tested
by simulating signal delivery without needing a real Temporal connection.
"""

from __future__ import annotations

import asyncio
import logging
import signal

logger = logging.getLogger(__name__)


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop, shutdown_event: asyncio.Event
) -> None:
    """
    Register SIGTERM and SIGINT handlers on the given event loop that set
    `shutdown_event`. Safe to call once per process/loop.
    """

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info(
            "Received shutdown signal, beginning graceful shutdown",
            extra={"signal": sig.name},
        )
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except NotImplementedError:
            # add_signal_handler isn't available on some platforms (e.g.
            # native Windows event loops). Fall back to the classic
            # signal.signal() API, which still works but must dispatch back
            # onto the loop thread-safely.
            signal.signal(
                sig,
                lambda signum, frame, _sig=sig: loop.call_soon_threadsafe(
                    _handle_signal, _sig
                ),
            )
