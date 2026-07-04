"""
CLI starter - the actual user-facing entrypoint.

Usage:
    python starter.py "1 + 5^3 * (2 - 5)"

Connects to Temporal, starts one CalculatorWorkflow execution on the
dedicated workflow task queue, waits for the result, and prints it.
Parsing/validation errors surface immediately and clearly, since a
malformed expression should never even reach Temporal.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from temporalio.client import Client  # noqa: E402

from parser.expression_parser import ExpressionParseError, parse_expression  # noqa: E402
from task_queues import WORKFLOW_TASK_QUEUE  # noqa: E402
from workflows.calculator_workflow import CalculatorRequest, CalculatorWorkflow  # noqa: E402

TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")


async def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python starter.py "<expression>"')
        sys.exit(1)

    expression = sys.argv[1]

    # Fail fast on malformed input before ever talking to Temporal -
    # this is the same parser the Workflow itself will use, so a locally
    # caught error here is guaranteed to also be one the Workflow would
    # have hit.
    try:
        parse_expression(expression)
    except ExpressionParseError as exc:
        print(f"Invalid expression: {exc}")
        sys.exit(1)

    client = await Client.connect(TEMPORAL_HOST)

    workflow_id = f"calculator-{uuid.uuid4()}"
    print(f"Starting workflow {workflow_id!r} for expression: {expression!r}")

    result = await client.execute_workflow(
        CalculatorWorkflow.run,
        CalculatorRequest(expression=expression),
        id=workflow_id,
        task_queue=WORKFLOW_TASK_QUEUE,
    )

    print(f"{expression} = {result}")


if __name__ == "__main__":
    asyncio.run(main())
