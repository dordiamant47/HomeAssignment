"""
Load generator for stress_test.sh.

Fires a continuous stream of CalculatorWorkflow executions for a fixed
duration, deliberately SKEWED toward '+' expressions (90% by default). The
expected, observable outcome on a running cluster: `add-worker` scales up
via its HPA while `sub-worker`/`mul-worker`/`div-worker`/`pow-worker` stay
at their minimum replica count - this is the concrete proof that
per-operator independent scaling actually works, not just something
asserted in README.md.

Env vars:
    TEMPORAL_HOST              default: localhost:7233
    STRESS_DURATION_SECONDS    default: 180
    STRESS_CONCURRENCY         default: 50   (max in-flight workflow starts)
    STRESS_SKEW_OP             default: "+"
    STRESS_SKEW_RATIO          default: 0.9  (fraction of calls using STRESS_SKEW_OP)
"""

import asyncio
import os
import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from temporalio.client import Client  # noqa: E402

from task_queues import WORKFLOW_TASK_QUEUE  # noqa: E402
from workflows.calculator_workflow import CalculatorRequest, CalculatorWorkflow  # noqa: E402

TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
DURATION_SECONDS = int(os.environ.get("STRESS_DURATION_SECONDS", "180"))
CONCURRENCY = int(os.environ.get("STRESS_CONCURRENCY", "50"))
SKEW_OP = os.environ.get("STRESS_SKEW_OP", "+")
SKEW_RATIO = float(os.environ.get("STRESS_SKEW_RATIO", "0.9"))

OTHER_OPS = [op for op in ["+", "-", "*", "/", "^"] if op != SKEW_OP]


def random_expression() -> str:
    op = SKEW_OP if random.random() < SKEW_RATIO else random.choice(OTHER_OPS)
    a = random.randint(1, 50)
    b = random.randint(1, 20)
    if op == "^":
        b = random.randint(1, 4)  # keep exponents small - this is a load
        # test on scheduling/throughput, not on producing enormous numbers
    if op == "/" and b == 0:
        b = 1
    return f"{a} {op} {b}"


async def run_one(client: Client) -> None:
    expression = random_expression()
    workflow_id = f"stress-{uuid.uuid4()}"
    try:
        await client.execute_workflow(
            CalculatorWorkflow.run,
            CalculatorRequest(expression=expression),
            id=workflow_id,
            task_queue=WORKFLOW_TASK_QUEUE,
        )
    except Exception as exc:  # noqa: BLE001 - a load generator should log and continue, not crash
        print(f"[stress] call failed for {expression!r}: {exc}")


async def main() -> None:
    print(
        f"[stress] starting: duration={DURATION_SECONDS}s concurrency={CONCURRENCY} "
        f"skew_op={SKEW_OP!r} skew_ratio={SKEW_RATIO} temporal_host={TEMPORAL_HOST}"
    )
    client = await Client.connect(TEMPORAL_HOST)

    in_flight: set[asyncio.Task] = set()
    total_launched = 0
    end_at = time.monotonic() + DURATION_SECONDS

    while time.monotonic() < end_at:
        if len(in_flight) < CONCURRENCY:
            task = asyncio.create_task(run_one(client))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)
            total_launched += 1
            if total_launched % 100 == 0:
                print(f"[stress] launched {total_launched} workflow executions so far...")
        else:
            await asyncio.sleep(0.01)

    print(f"[stress] duration elapsed, launched {total_launched} total - draining in-flight...")
    if in_flight:
        await asyncio.gather(*in_flight, return_exceptions=True)

    print(f"[stress] done. {total_launched} workflow executions over {DURATION_SECONDS}s.")


if __name__ == "__main__":
    asyncio.run(main())
