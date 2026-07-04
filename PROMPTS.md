# PROMPTS.md

The prompts from this project that actually shaped the final structure —
architecture, code, infra, or docs. Plain "yes" / "confirm" / "continue"
approvals are left out; each one below is verbatim.

---

### 1. Initial architecture & requirements

I have a home assignment for a Senior DevOps / Platform engineering role, and I want us to pair-program the whole thing from scratch. We are going to build a distributed calculator system using the Temporal Python SDK and Kubernetes.

CRITICAL RULE: Do NOT write or output any actual code yet. I want us to work in clean, iterative steps.
First, let's align on the architecture and planning. Once I approve the plan, we will move to the code.

1. What are we building? (The Component & Flow)
The user will trigger a script with a math expression string, for example: "1 + 5^3 * (2 - 5)".
- The App / Parser: A Python script will take this string, parse it by keeping the correct math precedence and parentheses.
- The Workflow (The Orchestrator): A Temporal Workflow will act as the brain. It reads the expression and calls the right math operation (Activity) step-by-step.
- The Queues (The Matrix): Every math operator (+, -, *, /, ^) must have its own separate, dedicated Task Queue inside Temporal (e.g., `add-task-queue`, `multiply-task-queue`). The workflow needs to dynamically route each operation to the correct queue.
- The Workers (The Muscle): Python workers running inside Kubernetes pods will listen to these queues, pull the tasks, execute the basic math operation, and return the result back to Temporal so the workflow can continue

2. My Personal Notes & Side Requirements:
- The Workers must be identical and configurable via Env: I don't want separate code for each worker.
The code should be exactly the same, but when a worker container starts in Kubernetes, it should read environment variables like `TEMPORAL_TASK_QUEUE` and `TEMPORAL_HOST` to know which queue to listen to and turn into the right worker automatically.
- Reusable Platform SDK: The core logic of bootstrapping the worker, connecting to Temporal, handling OS signals for a Graceful Shutdown, and configuring structured JSON logging must be abstracted into a clean, reusable Python package under `sdk/` (using setup.py or pyproject.toml).
- Zero-Code Health Probes: The SDK must automatically spin up a lightweight background HTTP server on a port like 8080 to expose `/live` and `/ready` endpoints for Kubernetes. Upgrading the SDK version should bring these probes to life without changing a single line of business logic in the calculator app.
- Independent Worker Autoscaling (HPA): In Kubernetes, we need to scale each worker deployment separately. If the addition worker gets a million requests and subtraction is empty, only the addition deployment should scale up. We will use standard CPU/Memory scaling for the assignment requirements, but I want us to document in the README why event-driven scaling (like queue depth via KEDA) is the proper way to do it.

### 3. What the final deliverable/Git structure should look like:
- `sdk/` -> Reusable python bootstrap package.
- `calculator/` -> The app code (workflow, basic math activities, main script).
- `charts/` -> A single, generic Helm Chart that uses a dynamic loop (matrix) in `values.yaml` to deploy the 5 different deployments using the exact same Docker image, changing only the Env variables.
- `scripts/` -> `deploy.sh` (to spin up a local Kind cluster, install Temporal via Helm, build our image, and deploy our app) and `stress_test.sh` (to flood the system and prove that HPA scaling works independently per worker).
- `README.md` -> A short, clean, precise documentation file with an ASCII art diagram showing the lifecycle.
- `PROMPTS.md` -> A file documenting our AI session journey and the prompts we used.

### What I need from you right now (First Response):
1. Give me a concise breakdown of each component and its exact role.
2. Create a clean ASCII art architecture diagram showing the full E2E lifecycle (including what happens AFTER a worker pod completes its isolated calculation and returns the state).
3. Show me the proposed complete folder tree layout for this Python project based on the structure above.
4. Give me a step-by-step joint execution roadmap divided into clean milestones.

Remember, NO code blocks yet. Let's get the design and plan sorted out first. Let me know if you understand the mission!
For each step i'll give you confirmation, you will execute, validate, and only then move to the next step

---

### 2. Local Temporal server requirement

Yes, we need Temporal Server running inside our local Kind cluster.
In our 'deploy.sh' script, please include the installation of the official Temporal Helm Chart (using their standard self-hosted setup).
This way, when I run 'deploy.sh', it will first spin up the Kind cluster, install the official Temporal server via Helm, and then build and deploy our custom calculator workers chart that connects to it.

---

### 3. Observability requirement

We want to implement basic observability (metric + logs) for the SDK Upgrade.
Lets implement it

---

### 4. Final wrap-up: docs, diagram, structure, requirements audit

lets go to the next step:

1. document everything we need in a most simple and readable way.
2. create a visual diagram of the whole flow and how it works.
3. seperate it to folders and files logically (folder for all workers manifets, file for all prompts)
4. readable and simple README.md file

Wrap up everything from the beginning to the end
Before you upload it - make sure we covered everything i've asked

---

### 5. KEDA with application metrics

Lets adjust the hpa by generating keda based on application metrics (not only cpu + mem for each one of the workers, also lean on latency + requests count)

--------------------------------------------

## How to reduce number of iterations :

1. **Architecture-First Enforcement:** By forcing the model to output a Component Matrix and Roadmap before writing code, architectural misalignment was caught at the concept stage rather than during debugging.
2. **Explicit Topology Declarations:** For example - Clearly defining that Workers must remain identical and behaviorally driven by `ENV` variables prevented the AI from generating redundant, decoupled codebases for each math operator.
3. **Pre-empting Egress Constraints (Lesson Learned):** Providing the precise environment limitations in the very first prompt would have completely eliminated the PoC troubleshooting phase, allowing the model to build the offline test harness natively from step one.