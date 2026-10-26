"""airflow/dags/mlops.py without Airflow installed: stub the few Airflow/Kubernetes names it imports, load the file,
and check the DAGs, task order and pod arguments it declares."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class Task:
    def __init__(self, task_id, **kwargs):
        self.task_id, self.kwargs, self.downstream = task_id, kwargs, []
        Dag.current.tasks[task_id] = self

    def __rshift__(self, other):
        self.downstream.append(other.task_id)
        return other


class Dag:
    current = None
    all = {}

    def __init__(self, dag_id, **kwargs):
        self.dag_id, self.kwargs, self.tasks = dag_id, kwargs, {}

    def __enter__(self):
        Dag.current = Dag.all[self.dag_id] = self
        return self

    def __exit__(self, *exc):
        Dag.current = None


STUBS = ["airflow", "airflow.operators.trigger_dagrun", "airflow.providers.cncf.kubernetes.operators.pod",
         "airflow.providers.common.sql.sensors.sql", "kubernetes", "kubernetes.client"]


def stub(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module


@pytest.fixture(scope="module")
def dags():
    saved = {name: sys.modules.get(name) for name in STUBS}
    pod = lambda task_id, **kw: Task(task_id, kind="pod", **kw)  # noqa: E731
    stub("airflow", DAG=Dag)
    stub("airflow.operators.trigger_dagrun", TriggerDagRunOperator=lambda task_id, **kw: Task(task_id, kind="trigger", **kw))
    stub("airflow.providers.cncf.kubernetes.operators.pod", KubernetesPodOperator=pod)
    stub("airflow.providers.common.sql.sensors.sql", SqlSensor=lambda task_id, **kw: Task(task_id, kind="sensor", **kw))
    models = types.SimpleNamespace(**{n: (lambda **kw: kw) for n in (
        "V1Volume", "V1PersistentVolumeClaimVolumeSource", "V1VolumeMount", "V1ResourceRequirements",
        "V1LocalObjectReference")})
    stub("kubernetes")
    stub("kubernetes.client", models=models)
    spec = importlib.util.spec_from_file_location("mlops_dags", ROOT / "airflow/dags/mlops.py")
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    yield Dag.all
    for name, module in saved.items():  # put back only what was stubbed
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def chain(dag):
    """Task ids in dependency order (each DAG here is a single chain)."""
    order, task = [], next(t for t in dag.tasks.values()
                           if not any(t.task_id in o.downstream for o in dag.tasks.values()))
    while task:
        order.append(task.task_id)
        task = dag.tasks[task.downstream[0]] if task.downstream else None
    return order


def args(task):
    return task.kwargs["arguments"]


def test_one_dag_set_per_use_case(dags):
    from training.config import load_usecases
    expected = {"feature_store_daily", "feature_store_maintenance"} | {
        f"{u}_{kind}" for u in load_usecases() for kind in ("train", "predict", "evaluate")}
    assert set(dags) == expected


def test_feature_store_daily_follows_the_documented_steps(dags):
    dag = dags["feature_store_daily"]
    assert dag.kwargs["schedule"] == "0 23 * * *" and dag.kwargs["max_active_runs"] == 1
    assert chain(dag) == ["check_source", "compute_features", "write_partitions", "quality_gate", "publish_marker"]
    modules = [args(dag.tasks[t])[0] for t in chain(dag)]
    assert modules == ["features.check_source", "features.compute", "features.write", "features.quality",
                       "features.publish"]
    assert dag.tasks["quality_gate"].kwargs["retries"] == 0  # a failed gate is a verdict
    out = args(dag.tasks["compute_features"])
    staging = args(dag.tasks["write_partitions"])
    assert out[out.index("--out") + 1] == staging[staging.index("--staging") + 1]


@pytest.mark.parametrize("usecase", ["loan_propensity", "overdue_risk", "campaign_response"])
def test_use_case_dags_pass_their_use_case(dags, usecase):
    predict = dags[f"{usecase}_predict"]
    assert chain(predict) == ["wait_features", "predict", "drift", "retrain_check", "trigger_retrain"]
    assert predict.tasks["wait_features"].kwargs["kind"] == "sensor"
    assert "control.fs_status" in predict.tasks["wait_features"].kwargs["sql"]
    assert predict.tasks["trigger_retrain"].kwargs["trigger_dag_id"] == f"{usecase}_train"
    train = dags[f"{usecase}_train"]
    assert chain(train) == ["build_training", "train", "report_gate"]
    run_id = args(train.tasks["build_training"])[-1]
    assert args(train.tasks["train"])[-1].endswith(run_id)  # train reads the run its DAG run built
    for dag in (predict, train, dags[f"{usecase}_evaluate"]):
        for task in dag.tasks.values():
            if task.kwargs["kind"] == "pod" and args(task)[0] != "features.build_training":
                assert args(task)[args(task).index("--usecase") + 1] == usecase
                assert "--approve" not in args(task)  # @production stays a human decision


def test_pods_run_in_cluster_from_the_registry(dags):
    pods = [t for d in dags.values() for t in d.tasks.values() if t.kwargs["kind"] == "pod"]
    assert pods and all(t.kwargs["in_cluster"] and "config_file" not in t.kwargs for t in pods)
    assert all(t.kwargs["image_pull_policy"] != "Never" and "/" in t.kwargs["image"] for t in pods)
