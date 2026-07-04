"""
AST resolver - the core routing algorithm, deliberately isolated from
Temporal itself.

`resolve_ast` recursively walks a parsed expression tree and, for every
binary operation, asks an injected `execute` callable to actually perform
that one operation (looking up which task queue owns that operator along
the way). In production, `execute` is a small closure that calls
`workflow.execute_activity(...)` - but this function itself has ZERO
Temporal imports, so the entire "walk the tree, resolve children before
parents, route each op to its queue" algorithm can be unit tested with a
trivial in-memory fake executor, no live server or sandbox required.

This mirrors the same isolation principle used for the parser and the
activity's arithmetic: keep the deterministic, testable logic separate
from the thin Temporal-calling glue around it.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from activities.math_activities import ComputeInput
from parser.expression_parser import AstNode, BinaryOpNode, NumberNode
from task_queues import task_queue_for_op

# Given (task_queue_name, ComputeInput), return the numeric result.
# In production this is a closure around workflow.execute_activity; in
# tests it can be anything, e.g. a fake that just computes locally.
ActivityExecutor = Callable[[str, ComputeInput], Awaitable[float]]


async def resolve_ast(node: AstNode, execute: ActivityExecutor) -> float:
    """
    Recursively resolve an AST to a single float, awaiting `execute` once
    per BinaryOpNode (i.e. once per Activity call in production).

    Children are always resolved before their parent, since a parent op
    needs both operand values before it can be evaluated - this naturally
    enforces the correct bottom-up evaluation order regardless of how deep
    or unbalanced the tree is.
    """
    if isinstance(node, NumberNode):
        return node.value

    if isinstance(node, BinaryOpNode):
        left_value = await resolve_ast(node.left, execute)
        right_value = await resolve_ast(node.right, execute)
        queue = task_queue_for_op(node.op)
        return await execute(
            queue, ComputeInput(op=node.op, a=left_value, b=right_value)
        )

    raise TypeError(f"Unknown AST node type: {type(node)!r}")
