"""
Activity worker entrypoint.

This is THE ONE binary/image deployed 5 times (add/sub/mul/div/pow). There
is no per-operator code anywhere in this file or in math_activities.py -
each deployment is byte-for-byte identical, differentiated purely by which
TEMPORAL_TASK_QUEUE environment variable Kubernetes injects into it.

The `compute` activity itself already handles all 5 operators (see
task_queues.py for the queue-to-operator mapping used at the Workflow
routing layer); this process just polls whichever single queue its env
var points it at.

Run:
    TEMPORAL_TASK_QUEUE=add-task-queue python activity_worker_main.py
    TEMPORAL_TASK_QUEUE=sub-task-queue python activity_worker_main.py
    # ...etc, same file, same image, only the env var changes.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))

from platform_sdk import run_worker  # noqa: E402
from activities.math_activities import compute  # noqa: E402


async def main() -> None:
    # No `workflows=` here at all - this process ONLY hosts the activity.
    # The workflow lives in a completely separate deployment/queue (see
    # workflow_worker_main.py), by design.
    await run_worker(activities=[compute])


if __name__ == "__main__":
    asyncio.run(main())
