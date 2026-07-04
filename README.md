# Distributed Calculator on Temporal

A math expression (`"1 + 5^3 * (2 - 5)"`) goes in. A Temporal Workflow
parses it, routes each operator to its own Kubernetes worker, and the
result comes out. One Docker image runs all 6 worker roles — only one
argument and one env var differ between them.

## How it works

```
                         ┌─────────────┐
                         │   Client    │  "1 + 5^3 * (2 - 5)"
                         │ starter.py  │
                         └──────┬──────┘
                                │ 1. start workflow
                                ▼
                    ┌────────────────────────┐
                    │     Temporal Server      │
                    │ persists history, routes │
                    │  workflow & activity     │
                    │        tasks             │
                    └───────────┬──────────────┘
                                │ 2. workflow task
                                ▼
                    ┌────────────────────────┐
                    │    workflow-worker       │  own Deployment
                    │  parses expr -> AST      │  own queue
                    │  routes each op ->       │  no ScaledObject
                    │  its dedicated queue     │
                    └──┬───────┬───────┬────┬──┘
              3. route by operator (dynamic, per AST node)
                 │       │       │       │       │
                 ▼       ▼       ▼       ▼       ▼
              add-q   sub-q   mul-q   div-q   pow-q
                 │       │       │       │       │
                 ▼       ▼       ▼       ▼       ▼
              add-w   sub-w   mul-w   div-w   pow-w   <- same image, 5x
                                                          only TEMPORAL_TASK_QUEUE differs
                                                          KEDA: cpu + mem + latency + req/s

                 4. activity result -> recorded in workflow history
                 5. workflow-worker REPLAYS history, resumes at next node
                    (loops 2-5 until the AST is fully reduced)
                                │
                                ▼
                         back to Client
```

1. `starter.py` parses the expression and starts a `CalculatorWorkflow`.
2. The **workflow worker** (its own Deployment, its own queue) walks the
   expression tree bottom-up.
3. Each operator routes to its own dedicated task queue.
4. The matching **activity worker** (same image, 5 copies, only
   `TEMPORAL_TASK_QUEUE` differs) does the arithmetic and returns it.
5. Temporal replays the workflow's history to resume exactly where it
   left off, and moves to the next node — repeat until done.

## Structure

```
calculator/                    the app
├── parser/                     expression string -> AST
├── activities/                 the arithmetic (all 5 ops)
├── workflows/                  CalculatorWorkflow
├── task_queues.py              op -> queue name mapping
├── ast_resolver.py              walks the AST, routes each op to its queue
├── activity_worker_main.py      generic activity worker (deployed 5x)
├── workflow_worker_main.py       the one non-interchangeable worker
├── starter.py                   CLI: python starter.py "1 + 2"
├── load_generator.py            skewed load, used by stress_test.sh
├── Dockerfile / entrypoint.sh    one image, all worker roles
└── tests/                       92 tests

sdk/platform_sdk/               reusable worker SDK (every worker uses this)
├── bootstrap.py                 connects to Temporal, runs the worker
├── health.py                    /live + /ready
├── metrics.py                   /metrics (Temporal's built-in Prometheus exporter)
├── logging.py                   structured JSON logs
└── shutdown.py                  graceful shutdown on SIGTERM/SIGINT
sdk/tests/                       26 tests

charts/calculator/               the Helm chart - all k8s manifests come from here
├── values.yaml                   the matrix: one entry per worker
└── templates/
    ├── deployment.yaml            generates all 6 worker Deployments
    └── scaledobject.yaml          KEDA autoscaling for the 5 activity workers

scripts/
├── deploy.sh                    Kind + KEDA + Prometheus + Temporal + our chart
├── stress_test.sh                proves independent per-worker scaling
├── postgres-dev.yaml             throwaway Postgres for Temporal
├── prometheus-dev.yaml           scrapes worker metrics for KEDA
└── temporal-values.yaml          values for the official Temporal Helm chart

PROMPTS.md                      the original prompt that started this project
README.md                       this file
```

## Setup

**Prerequisites:** Docker, [Kind](https://kind.sigs.k8s.io/docs/user-guide/quick-start/#installation), `kubectl`, `helm`. All four are single-binary installs (or `brew install kind kubectl helm` on macOS).

**1. Run the tests first** — no cluster needed, confirms the code itself is sound before touching Kubernetes:

```bash
cd sdk && pip install -e ".[dev]" && pytest tests/    # 26 passed
cd ../calculator && PYTHONPATH=../sdk pytest tests/   # 86 passed, 6 skipped
```

**2. Stand up the cluster** — one script does everything: Kind, metrics-server, KEDA, a small Prometheus, the official Temporal server chart, and our calculator chart.

```bash
./scripts/deploy.sh
```

Takes a few minutes on first run (pulling images). Ends by printing a ready-to-run `kubectl` command and the resolved Temporal host — copy that command as-is for step 3.

**3. Run a calculation:**

```bash
kubectl run -it --rm starter --image=calculator:local --restart=Never -n calculator \
  --overrides='{"spec":{"containers":[{"name":"starter","image":"calculator:local","args":["starter","1 + 5^3 * (2 - 5)"],"env":[{"name":"TEMPORAL_HOST","value":"<paste the host deploy.sh printed>"}]}]}}'
# expect: 1 + 5^3 * (2 - 5) = -374.0
```

**4. Prove independent scaling** — fires skewed load (90% `+`), watch `add-worker` climb while the rest stay flat:

```bash
./scripts/stress_test.sh
```

**Cleanup:**

```bash
kind delete cluster --name calculator-dev
```

## Scaling

Each activity worker scales independently via its own **KEDA
`ScaledObject`** (`charts/calculator/templates/scaledobject.yaml`), on
four signals at once:

- CPU utilization
- Memory utilization
- p95 queue wait time (`temporal_activity_schedule_to_start_latency`) — is
  this queue backed up right now?
- Requests/sec (`temporal_activity_execution_latency_count`) — actual
  throughput, not a CPU proxy

Latency and request-rate come straight from Temporal's own built-in
Prometheus metrics (`sdk/platform_sdk/metrics.py` — zero app code
involved), scraped by a small Prometheus `deploy.sh` installs for this
purpose. CPU/memory alone can miss a backed-up queue on an otherwise idle
worker; these two extra signals catch that case directly. `workflow-worker`
has no `ScaledObject` — it's the one non-interchangeable worker, not
scaled like the other five.

Per-worker thresholds live in `charts/calculator/values.yaml`; `pow-worker`
is tuned to scale out earlier since `^` is the heaviest op per task.

## Observability

Every worker gets this for free via `sdk/platform_sdk/` — none of it
lives in the app's business logic:

- **Logs** — structured JSON to stdout (`logging.py`)
- **Metrics** — `/metrics`, via Temporal's built-in Prometheus exporter (`metrics.py`)
- **Health** — `/live` + `/ready` (`health.py`), wired into the chart's probes
