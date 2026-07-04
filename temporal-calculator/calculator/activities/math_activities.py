"""
Math activities.

For this M3 PoC, all operators are handled by a single generic activity
function running on a single task queue. This intentionally mirrors what
M4 will split apart: in M4, this same `compute()` function's per-operator
logic gets separated so each operator can be deployed independently and
routed to its own dedicated task queue. Keeping the arithmetic itself
identical across milestones means M4 is purely a *topology/routing* change,
not a logic rewrite.

`ComputeInput` is a single dataclass argument (rather than positional
a/b/op params) per Temporal's own guidance: activities and workflows should
take one dataclass parameter so new fields can be added later without
breaking callers already encoded in running workflow history.
"""

from __future__ import annotations

from dataclasses import dataclass

from temporalio import activity


class UnsupportedOperatorError(ValueError):
    """Raised when an operator outside the supported set is requested."""


@dataclass(frozen=True)
class ComputeInput:
    op: str
    a: float
    b: float


_OPERATIONS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "^": lambda a, b: a ** b,
}


def compute_sync(request: ComputeInput) -> float:
    """
    Pure, synchronous, side-effect-free arithmetic - deliberately separated
    from the `@activity.defn`-decorated wrapper below so it can be unit
    tested with zero Temporal machinery involved at all.
    """
    try:
        op_fn = _OPERATIONS[request.op]
    except KeyError as exc:
        raise UnsupportedOperatorError(
            f"Unsupported operator {request.op!r}. "
            f"Supported operators: {sorted(_OPERATIONS)}"
        ) from exc

    if request.op == "/" and request.b == 0:
        raise ZeroDivisionError(f"Division by zero: {request.a} / {request.b}")

    return op_fn(request.a, request.b)


@activity.defn(name="compute")
async def compute(request: ComputeInput) -> float:
    activity.logger.info(
        "Executing compute activity",
        extra={"op": request.op, "a": request.a, "b": request.b},
    )
    return compute_sync(request)
