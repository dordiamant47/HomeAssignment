"""
Task queue naming - the single source of truth for which Temporal task
queue handles which operator.

Both the Workflow (to decide where to route each activity call) and the
Helm chart's values.yaml matrix (to decide which Deployments/HPAs to
create) are conceptually driven by this mapping, so if a 6th operator is
ever added, this is the one place in the Python code that needs to change.
"""

from __future__ import annotations

OP_TASK_QUEUES: dict[str, str] = {
    "+": "add-task-queue",
    "-": "sub-task-queue",
    "*": "mul-task-queue",
    "/": "div-task-queue",
    "^": "pow-task-queue",
}

# The workflow worker (hosting CalculatorWorkflow itself) gets its own
# dedicated queue, separate from all activity queues above - it is NOT one
# of the 5 identical activity workers, it's the orchestrator.
WORKFLOW_TASK_QUEUE = "calculator-workflow-queue"


def task_queue_for_op(op: str) -> str:
    """Return the dedicated task queue for a given operator, or raise
    ValueError for anything unrecognized."""
    try:
        return OP_TASK_QUEUES[op]
    except KeyError as exc:
        raise ValueError(
            f"No task queue configured for operator {op!r}. "
            f"Known operators: {sorted(OP_TASK_QUEUES)}"
        ) from exc
