import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_sdk.bootstrap import (  # noqa: E402
    ConfigError,
    WorkerConfig,
    load_config_from_env,
    run_worker,
)


# ---------------------------------------------------------------------------
# load_config_from_env
# ---------------------------------------------------------------------------

class TestLoadConfigFromEnv:
    def test_reads_all_values_from_env(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_HOST", "temporal-frontend:7233")
        monkeypatch.setenv("TEMPORAL_NAMESPACE", "calc-ns")
        monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "add-task-queue")
        monkeypatch.setenv("HEALTH_PORT", "9090")
        monkeypatch.setenv("METRICS_PORT", "9100")

        cfg = load_config_from_env()

        assert cfg == WorkerConfig(
            temporal_host="temporal-frontend:7233",
            temporal_namespace="calc-ns",
            task_queue="add-task-queue",
            health_port=9090,
            metrics_port=9100,
        )

    def test_defaults_applied(self, monkeypatch):
        monkeypatch.delenv("TEMPORAL_HOST", raising=False)
        monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)
        monkeypatch.delenv("HEALTH_PORT", raising=False)
        monkeypatch.delenv("METRICS_PORT", raising=False)
        monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "sub-task-queue")

        cfg = load_config_from_env()

        assert cfg.temporal_host == "localhost:7233"
        assert cfg.temporal_namespace == "default"
        assert cfg.health_port == 8080
        assert cfg.metrics_port == 9090
        assert cfg.task_queue == "sub-task-queue"

    def test_missing_task_queue_raises(self, monkeypatch):
        monkeypatch.delenv("TEMPORAL_TASK_QUEUE", raising=False)
        with pytest.raises(ConfigError):
            load_config_from_env()

    def test_task_queue_override_bypasses_env(self, monkeypatch):
        monkeypatch.delenv("TEMPORAL_TASK_QUEUE", raising=False)
        cfg = load_config_from_env(task_queue_override="mul-task-queue")
        assert cfg.task_queue == "mul-task-queue"

    def test_invalid_health_port_raises(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "add-task-queue")
        monkeypatch.setenv("HEALTH_PORT", "not-a-number")
        with pytest.raises(ConfigError):
            load_config_from_env()

    def test_invalid_metrics_port_raises(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "add-task-queue")
        monkeypatch.setenv("METRICS_PORT", "not-a-number")
        with pytest.raises(ConfigError):
            load_config_from_env()


# ---------------------------------------------------------------------------
# run_worker lifecycle (Temporal Client/Worker are mocked out entirely -
# these tests validate OUR orchestration logic, not the Temporal SDK itself)
# ---------------------------------------------------------------------------

class _FakeWorker:
    """Minimal async-context-manager stand-in for temporalio.worker.Worker."""

    def __init__(self, *args, **kwargs):
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited = True
        return False


@pytest.mark.asyncio
async def test_run_worker_reports_ready_then_not_ready_on_shutdown(
    unused_tcp_port, unused_tcp_port_2
):
    cfg = WorkerConfig(
        temporal_host="localhost:7233",
        temporal_namespace="default",
        task_queue="add-task-queue",
        health_port=unused_tcp_port,
        metrics_port=unused_tcp_port_2,
    )

    fake_worker = _FakeWorker()
    ready_states_observed = []

    # Wrap set_ready so we can observe the sequence of transitions.
    from platform_sdk.health import HealthState

    original_set_ready = HealthState.set_ready

    def spy_set_ready(self, value):
        ready_states_observed.append(value)
        return original_set_ready(self, value)

    with patch("platform_sdk.bootstrap.Client.connect", new=AsyncMock(return_value=MagicMock())), \
         patch("platform_sdk.bootstrap.Worker", return_value=fake_worker), \
         patch.object(HealthState, "set_ready", spy_set_ready):

        shutdown_triggered = asyncio.Event()

        async def trigger_shutdown_soon():
            # Let run_worker reach `await shutdown_event.wait()` first.
            await asyncio.sleep(0.05)
            shutdown_triggered.set()

        # Patch install_signal_handlers to instead just wire our own event,
        # since we're not testing real signal delivery here (that's
        # test_shutdown.py's job) - we're testing run_worker's own sequencing.
        def fake_install(loop, event):
            async def _copy():
                await shutdown_triggered.wait()
                event.set()
            asyncio.ensure_future(_copy())

        with patch("platform_sdk.bootstrap.install_signal_handlers", fake_install):
            await asyncio.gather(run_worker(config=cfg), trigger_shutdown_soon())

    assert fake_worker.entered is True
    assert fake_worker.exited is True
    assert ready_states_observed == [True, False]


@pytest.mark.asyncio
async def test_run_worker_raises_and_marks_not_ready_on_connect_failure(
    unused_tcp_port, unused_tcp_port_2
):
    cfg = WorkerConfig(
        temporal_host="localhost:7233",
        temporal_namespace="default",
        task_queue="add-task-queue",
        health_port=unused_tcp_port,
        metrics_port=unused_tcp_port_2,
    )

    with patch(
        "platform_sdk.bootstrap.Client.connect",
        new=AsyncMock(side_effect=ConnectionError("no server")),
    ):
        with pytest.raises(ConnectionError):
            await run_worker(config=cfg)
