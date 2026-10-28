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
         "kubernetes", "kubernetes.client"]


def stub(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module


@pytest.fixture(scope="module")
def dags():
    saved = {name: sys.modules.get(name) for name in STUBS}
    Dag.all = {}
    pod = lambda task_id, **kw: Task(task_id, kind="pod", **kw)  # noqa: E731
    stub("airflow", DAG=Dag)
    stub("airflow.operators.trigger_dagrun", TriggerDagRunOperator=lambda task_id, **kw: Task(task_id, kind="trigger", **kw))
    stub("airflow.providers.cncf.kubernetes.operators.pod", KubernetesPodOperator=pod)
    models = types.SimpleNamespace(**{n: (lambda **kw: kw) for n in (
        "V1Volume", "V1PersistentVolumeClaimVolumeSource", "V1VolumeMount", "V1ResourceRequirements")})
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


def test_the_declared_dags(dags):
    assert set(dags) == {"feature_store_daily", "feature_store_maintenance", "loan_propensity_train",
                         "loan_propensity_predict", "loan_propensity_evaluate"}


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
    assert out[out.index("--out") + 1] == staging[staging.index("--staging") + 1]  # write reads what compute staged


def test_maintenance_runs_weekly_with_the_documented_options(dags):
    dag = dags["feature_store_maintenance"]
    assert dag.kwargs["schedule"] == "0 20 * * 6"
    options = args(dag.tasks["iceberg_maintenance"])
    assert options[0] == "features.maintenance" and "--retention-months" in options
    assert options[options.index("--retention-months") + 1] == "12"
    assert {"--expire-snapshots", "--remove-orphans"} <= set(options)


def test_predict_waits_for_the_feature_store_day_first(dags):
    predict = dags["loan_propensity_predict"]
    assert chain(predict) == ["wait_features", "predict", "drift", "retrain_check", "trigger_retrain"]
    wait = args(predict.tasks["wait_features"])
    assert wait[:2] == ["features.status", "--date"] and "--wait" in wait
    assert wait[wait.index("--date") + 1] == "{{ params.score_date }}"   # the day it is about to score
    assert predict.tasks["trigger_retrain"].kwargs["trigger_dag_id"] == "loan_propensity_train"


def test_nothing_here_may_approve_production(dags):
    for dag in dags.values():
        for task in dag.tasks.values():
            if task.kwargs["kind"] == "pod":
                assert "--approve" not in args(task)  # @production stays a human decision


def test_pods_use_the_image_loaded_into_kind(dags):
    pods = [t for d in dags.values() for t in d.tasks.values() if t.kwargs["kind"] == "pod"]
    assert pods and all(t.kwargs["image_pull_policy"] == "Never" and t.kwargs["image"] == "mlops-pipeline:v1"
                        for t in pods)