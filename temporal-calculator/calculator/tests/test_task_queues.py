import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from task_queues import OP_TASK_QUEUES, WORKFLOW_TASK_QUEUE, task_queue_for_op  # noqa: E402


class TestTaskQueueForOp:
    @pytest.mark.parametrize("op", ["+", "-", "*", "/", "^"])
    def test_all_five_operators_have_a_queue(self, op):
        assert task_queue_for_op(op) == OP_TASK_QUEUES[op]

    def test_all_queue_names_are_unique(self):
        queues = list(OP_TASK_QUEUES.values())
        assert len(queues) == len(set(queues))

    def test_workflow_queue_is_distinct_from_all_activity_queues(self):
        assert WORKFLOW_TASK_QUEUE not in OP_TASK_QUEUES.values()

    def test_unknown_operator_raises(self):
        with pytest.raises(ValueError):
            task_queue_for_op("%")
