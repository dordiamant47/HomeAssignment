"""
CalculatorWorkflow - M4 version: full AST walking with per-operator queue
routing.

Supersedes the M3 single-op PoC. The Workflow now:
  1. Parses the raw expression string into an AST (pure, deterministic -
     safe to run directly inside workflow code, no Activity needed for
     this step).
  2. Recursively resolves the AST via `resolve_ast`, which is where the
     actual dynamic routing happens: each BinaryOpNode's operator decides
     which of the 5 dedicated task queues its Activity call is scheduled
     on. `resolve_ast` itself is pure/injectable (see ast_resolver.py) -
     this class only supplies the one Temporal-specific piece: the closure
     that actually calls `workflow.execute_activity`.

Determinism note: parsing and tree-walking are pure computation with no
side effects, so running them directly in workflow code (rather than
wrapping them in Activities) does not violate Temporal's determinism
requirement. Only the actual arithmetic (which could, in principle, later
gain side effects like calling out to a pricing service) lives in an
Activity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from activities.math_activities import ComputeInput, compute
    from ast_resolver import resolve_ast
    from parser.expression_parser import parse_expression


@dataclass(frozen=True)
class CalculatorRequest:
    expression: str


@workflow.defn(name="CalculatorWorkflow")
class CalculatorWorkflow:
    @workflow.run
    async def run(self, request: CalculatorRequest) -> float:
        workflow.logger.info(
            "CalculatorWorkflow started", extra={"expression": request.expression}
        )

        ast = parse_expression(request.expression)

        async def execute_on_temporal(queue: str, compute_input: ComputeInput) -> float:
            return await workflow.execute_activity(
                compute,
                compute_input,
                task_queue=queue,
                start_to_close_timeout=timedelta(seconds=10),
            )

        result = await resolve_ast(ast, execute_on_temporal)

        workflow.logger.info(
            "CalculatorWorkflow completed",
            extra={"expression": request.expression, "result": result},
        )
        return result
