import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from activities.math_activities import (  # noqa: E402
    ComputeInput,
    UnsupportedOperatorError,
    compute,
    compute_sync,
)


class TestComputeSyncPureLogic:
    """Zero Temporal machinery involved - just the arithmetic."""

    @pytest.mark.parametrize(
        "op,a,b,expected",
        [
            ("+", 2.0, 3.0, 5.0),
            ("-", 5.0, 3.0, 2.0),
            ("*", 4.0, 3.0, 12.0),
            ("/", 10.0, 4.0, 2.5),
            ("^", 2.0, 10.0, 1024.0),
        ],
    )
    def test_each_operator(self, op, a, b, expected):
        assert compute_sync(ComputeInput(op=op, a=a, b=b)) == expected

    def test_division_by_zero_raises(self):
        with pytest.raises(ZeroDivisionError):
            compute_sync(ComputeInput(op="/", a=1.0, b=0.0))

    def test_unsupported_operator_raises(self):
        with pytest.raises(UnsupportedOperatorError):
            compute_sync(ComputeInput(op="%", a=1.0, b=2.0))


@pytest.mark.asyncio
class TestComputeActivity:
    """
    Runs the actual @activity.defn-wrapped function through Temporal's own
    ActivityEnvironment test harness. This does NOT require a running
    Temporal server or any network access - it's a pure in-process test
    double the temporalio SDK ships specifically for this purpose.
    """

    async def test_activity_add(self):
        from temporalio.testing import ActivityEnvironment

        env = ActivityEnvironment()
        result = await env.run(compute, ComputeInput(op="+", a=7.0, b=8.0))
        assert result == 15.0

    async def test_activity_propagates_unsupported_operator(self):
        from temporalio.testing import ActivityEnvironment

        env = ActivityEnvironment()
        with pytest.raises(UnsupportedOperatorError):
            await env.run(compute, ComputeInput(op="%", a=1.0, b=1.0))
