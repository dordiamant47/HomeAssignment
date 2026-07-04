"""
Workflow worker entrypoint.

Unlike the 5 identical activity workers, this process is intentionally the
ONE exception: it hosts the CalculatorWorkflow definition itself, not a
generic/interchangeable activity. It gets its own dedicated task queue
(WORKFLOW_TASK_QUEUE) so it scales and fails independently of the
arithmetic workers.

It still goes through the exact same platform_sdk.run_worker() bootstrap
as every other worker - same health probes, same structured logging, same
graceful shutdown - only the `workflows=`/`activities=` arguments differ.

Run:
    python workflow_worker_main.py
    # (TEMPORAL_TASK_QUEUE may be overridden, but defaults to the
    #  canonical WORKFLOW_TASK_QUEUE if unset - unlike the activity
    #  workers, where it's always required and always op-specific.)
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))

from platform_sdk import load_config_from_env, run_worker  # noqa: E402
from task_queues import WORKFLOW_TASK_QUEUE  # noqa: E402
from workflows.calculator_workflow import CalculatorWorkflow  # noqa: E402


async def main() -> None:
    config = load_config_from_env(
        task_queue_override=os.environ.get("TEMPORAL_TASK_QUEUE", WORKFLOW_TASK_QUEUE)
    )
    # No `activities=` here at all - this process ONLY hosts the workflow.
    await run_worker(workflows=[CalculatorWorkflow], config=config)


if __name__ == "__main__":
    asyncio.run(main())
