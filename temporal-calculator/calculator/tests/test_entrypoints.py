"""
Smoke tests for the 4 entrypoint scripts and the Workflow/Activity
decorator wiring.

Why this file exists: activity_worker_main.py, workflow_worker_main.py,
and starter.py each import CalculatorWorkflow/CalculatorRequest/compute
directly, but until this file, nothing in the test suite actually
imported THOSE files - so a change to calculator_workflow.py's input
type, or a broken import anywhere in the chain, would only surface by
someone running a script by hand and it failing. (This is exactly the
class of bug that broke poc_starter.py earlier in this project, caught
only by manual inspection - see PROMPTS.md/session history.) These tests
close that gap: importing each entrypoint module is enough to catch a
broken import or a stale reference, without needing a live Temporal
server or Docker.
"""

import importlib.util
import sys
from pathlib import Path

CALCULATOR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CALCULATOR_DIR))
sys.path.insert(0, str(CALCULATOR_DIR.parent / "sdk"))


def _import_as_module(filename: str):
    """Import a top-level script by path without executing its
    `if __name__ == "__main__":` block (module name won't be __main__)."""
    path = CALCULATOR_DIR / filename
    spec = importlib.util.spec_from_file_location(filename, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEntrypointsImportCleanly:
    """If CalculatorWorkflow's input type ever changes again without
    updating these scripts, THIS is what should fail."""

    def test_activity_worker_main_imports(self):
        module = _import_as_module("activity_worker_main.py")
        assert hasattr(module, "run_worker")

    def test_workflow_worker_main_imports(self):
        module = _import_as_module("workflow_worker_main.py")
        assert hasattr(module, "CalculatorWorkflow")

    def test_starter_imports(self):
        module = _import_as_module("starter.py")
        assert hasattr(module, "CalculatorRequest")
        assert hasattr(module, "CalculatorWorkflow")

    def test_load_generator_imports(self):
        module = _import_as_module("load_generator.py")
        assert hasattr(module, "CalculatorWorkflow")
        assert hasattr(module, "CalculatorRequest")


class TestWorkflowAndActivityWiring:
    """Confirms the @workflow.defn/@activity.defn decorators produced
    well-formed definitions - the same check Temporal's own Worker does
    at construction time against a real client."""

    def test_calculator_request_has_expression_field(self):
        from workflows.calculator_workflow import CalculatorRequest

        request = CalculatorRequest(expression="1 + 2")
        assert request.expression == "1 + 2"

    def test_workflow_decorator_registered_correctly(self):
        from workflows.calculator_workflow import CalculatorWorkflow

        defn = CalculatorWorkflow.__dict__.get(
            "__temporal_workflow_definition"
        ) or getattr(CalculatorWorkflow, "__temporal_workflow_definition")
        assert defn.name == "CalculatorWorkflow"
        assert defn.run_fn is not None

    def test_activity_decorator_registered_correctly(self):
        from activities.math_activities import compute

        defn = getattr(compute, "__temporal_activity_definition")
        assert defn.name == "compute"
