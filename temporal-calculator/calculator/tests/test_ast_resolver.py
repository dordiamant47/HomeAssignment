"""
Tests for resolve_ast - the core multi-queue routing algorithm.

Because resolve_ast takes an injected `execute` callable, we can test the
ENTIRE routing behavior (which queue gets used for which operator, correct
bottom-up evaluation order, correct final result) with a trivial in-memory
fake executor. No Temporal server, no sandbox, no network - this is the
same offline-testing principle used for the parser and the activity's pure
arithmetic.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from activities.math_activities import ComputeInput, compute_sync  # noqa: E402
from ast_resolver import resolve_ast  # noqa: E402
from parser.expression_parser import parse_expression  # noqa: E402
from task_queues import OP_TASK_QUEUES  # noqa: E402


class RecordingFakeExecutor:
    """
    Stands in for `workflow.execute_activity`: actually computes the result
    locally (via the real, pure compute_sync - not a hardcoded value, so a
    wrong routing decision or wrong operand order would still be caught),
    while recording every (queue, ComputeInput) call it received so tests
    can assert on the *routing*, not just the final number.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, ComputeInput]] = []

    async def __call__(self, queue: str, compute_input: ComputeInput) -> float:
        self.calls.append((queue, compute_input))
        return compute_sync(compute_input)


@pytest.mark.asyncio
class TestResolveAst:
    async def test_single_number_no_activity_calls(self):
        executor = RecordingFakeExecutor()
        ast = parse_expression("42")
        result = await resolve_ast(ast, executor)
        assert result == 42.0
        assert executor.calls == []

    async def test_simple_addition_routes_to_add_queue(self):
        executor = RecordingFakeExecutor()
        ast = parse_expression("1 + 2")
        result = await resolve_ast(ast, executor)
        assert result == 3.0
        assert len(executor.calls) == 1
        queue, compute_input = executor.calls[0]
        assert queue == OP_TASK_QUEUES["+"]
        assert compute_input == ComputeInput(op="+", a=1.0, b=2.0)

    async def test_the_assignment_example_expression(self):
        # "1 + 5^3 * (2 - 5)" = 1 + 125 * (-3) = -374
        # Exercises all four of +, ^, *, - in one run - i.e. proves calls
        # get routed to 4 DIFFERENT queues within a single workflow
        # execution, which is exactly the multi-queue behavior M4 exists
        # to prove.
        executor = RecordingFakeExecutor()
        ast = parse_expression("1 + 5^3 * (2 - 5)")
        result = await resolve_ast(ast, executor)

        assert result == -374.0

        queues_used = {queue for queue, _ in executor.calls}
        assert queues_used == {
            OP_TASK_QUEUES["+"],
            OP_TASK_QUEUES["^"],
            OP_TASK_QUEUES["*"],
            OP_TASK_QUEUES["-"],
        }
        assert len(executor.calls) == 4  # one call per BinaryOpNode

    async def test_children_resolved_before_parent(self):
        # (2 - 5) must be fully resolved to -3.0 BEFORE the '*' call is
        # made, since '*' needs that value as an operand.
        executor = RecordingFakeExecutor()
        ast = parse_expression("5 * (2 - 5)")
        await resolve_ast(ast, executor)

        ops_in_call_order = [ci.op for _queue, ci in executor.calls]
        assert ops_in_call_order == ["-", "*"]
        # And the '*' call's right operand must be the '-' call's result.
        minus_queue, minus_input = executor.calls[0]
        mult_queue, mult_input = executor.calls[1]
        assert mult_input.b == compute_sync(minus_input)

    async def test_repeated_operator_reuses_same_queue(self):
        # Multiple '+' operations in one expression should all route to the
        # SAME add-task-queue - proving routing is purely operator-driven,
        # not e.g. accidentally keyed by tree position.
        executor = RecordingFakeExecutor()
        ast = parse_expression("1 + 2 + 3 + 4")
        result = await resolve_ast(ast, executor)

        assert result == 10.0
        queues_used = {queue for queue, _ in executor.calls}
        assert queues_used == {OP_TASK_QUEUES["+"]}
        assert len(executor.calls) == 3

    @pytest.mark.parametrize(
        "expression,expected",
        [
            ("2 ^ 3 ^ 2", 512.0),  # right-assoc power still routes correctly
            ("100 / 5 / 2", 10.0),
            ("((1 + 2) * (3 - 1)) / 2", 3.0),
        ],
    )
    async def test_matches_expected_for_various_expressions(self, expression, expected):
        executor = RecordingFakeExecutor()
        ast = parse_expression(expression)
        result = await resolve_ast(ast, executor)
        assert result == pytest.approx(expected)
