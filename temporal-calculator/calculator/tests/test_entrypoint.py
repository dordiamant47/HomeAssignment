"""
Tests for entrypoint.sh's role-dispatch logic.

We can't run an actual `docker build`/`docker run` in this environment (no
Docker daemon here), but the dispatch logic itself - "given this role
argument, what command would run" - is pure shell logic we CAN test
directly, via the script's ENTRYPOINT_DRY_RUN=1 mode, which prints the
resolved command instead of exec'ing it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def run_dry(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(ENTRYPOINT), *args],
        env={"ENTRYPOINT_DRY_RUN": "1", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="entrypoint.sh is a bash script")
class TestEntrypointDispatch:
    def test_defaults_to_activity_worker_when_no_args(self):
        result = run_dry()
        assert result.returncode == 0
        assert result.stdout.strip().splitlines() == [
            "python",
            "/app/calculator/activity_worker_main.py",
        ]

    def test_activity_worker_role(self):
        result = run_dry("activity-worker")
        assert result.returncode == 0
        assert "/app/calculator/activity_worker_main.py" in result.stdout

    def test_workflow_worker_role(self):
        result = run_dry("workflow-worker")
        assert result.returncode == 0
        assert "/app/calculator/workflow_worker_main.py" in result.stdout

    def test_starter_role_passes_through_expression_arg(self):
        result = run_dry("starter", "1 + 5^3 * (2 - 5)")
        assert result.returncode == 0
        lines = result.stdout.strip().splitlines()
        assert lines == [
            "python",
            "/app/calculator/starter.py",
            "1 + 5^3 * (2 - 5)",
        ]

    def test_load_generator_role(self):
        result = run_dry("load-generator")
        assert result.returncode == 0
        assert result.stdout.strip().splitlines() == [
            "python",
            "/app/calculator/load_generator.py",
        ]

    def test_unknown_role_exits_nonzero_with_usage_message(self):
        result = run_dry("bogus-role")
        assert result.returncode == 1
        assert "Unknown role" in result.stderr
        assert "Usage" in result.stderr
