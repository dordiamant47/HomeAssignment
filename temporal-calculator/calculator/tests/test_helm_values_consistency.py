"""
Cross-checks charts/calculator/values.yaml against
calculator/task_queues.py.

These two files encode the same information in two different languages
(Helm values vs Python) with no shared import between them - it is
entirely possible to edit one and forget the other. This test is cheap
insurance against that drift, and needs no Helm/Kubernetes/Temporal at
all, just PyYAML.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from task_queues import OP_TASK_QUEUES, WORKFLOW_TASK_QUEUE  # noqa: E402

VALUES_YAML_PATH = (
    Path(__file__).resolve().parents[2] / "charts" / "calculator" / "values.yaml"
)


@pytest.fixture(scope="module")
def helm_values() -> dict:
    if not VALUES_YAML_PATH.exists():
        pytest.skip(f"{VALUES_YAML_PATH} not present yet")
    with open(VALUES_YAML_PATH) as fh:
        return yaml.safe_load(fh)


class TestHelmValuesConsistency:
    def test_values_yaml_is_valid_yaml(self, helm_values):
        assert isinstance(helm_values, dict)
        assert "workers" in helm_values

    def test_exactly_five_activity_workers_and_one_workflow_worker(self, helm_values):
        workers = helm_values["workers"]
        activity = [w for w in workers if w["role"] == "activity-worker"]
        workflow = [w for w in workers if w["role"] == "workflow-worker"]
        assert len(activity) == 5
        assert len(workflow) == 1

    def test_activity_worker_queues_match_task_queues_py(self, helm_values):
        helm_queues = {
            w["taskQueue"]
            for w in helm_values["workers"]
            if w["role"] == "activity-worker"
        }
        assert helm_queues == set(OP_TASK_QUEUES.values())

    def test_workflow_worker_queue_matches_task_queues_py(self, helm_values):
        helm_queue = next(
            w["taskQueue"]
            for w in helm_values["workers"]
            if w["role"] == "workflow-worker"
        )
        assert helm_queue == WORKFLOW_TASK_QUEUE

    def test_no_duplicate_worker_names(self, helm_values):
        names = [w["name"] for w in helm_values["workers"]]
        assert len(names) == len(set(names))

    def test_no_duplicate_task_queues(self, helm_values):
        queues = [w["taskQueue"] for w in helm_values["workers"]]
        assert len(queues) == len(set(queues))

    def test_every_activity_worker_has_keda_config_if_enabled(self, helm_values):
        for w in helm_values["workers"]:
            if w.get("keda", {}).get("enabled"):
                keda = w["keda"]
                assert "minReplicas" in keda
                assert "maxReplicas" in keda
                assert keda["minReplicas"] <= keda["maxReplicas"]
                assert "cpuUtilization" in keda
                assert "memoryUtilization" in keda
                assert "latencyThresholdMs" in keda
                assert "requestsPerSecond" in keda
