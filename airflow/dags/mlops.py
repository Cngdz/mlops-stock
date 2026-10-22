"""Airflow only schedules and orders: every task is a pod in kind running the mlops-pipeline image.

Training stops at @staging. @production is set only by a human (training.promote --approve), so no
task here may ever pass --approve.
"""
from datetime import datetime

from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

IMAGE = "mlops-pipeline:v1"
ENV = {  # in-cluster addresses: no port-forward from inside the cluster
    "MLFLOW_TRACKING_URI": "http://mlflow.mlops.svc.cluster.local",
    "MLFLOW_S3_ENDPOINT_URL": "http://minio.mlops.svc.cluster.local:9000",
}
DATA = k8s.V1Volume(
    name="data",
    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name="pipeline-data"),
)
DATA_MOUNT = k8s.V1VolumeMount(name="data", mount_path="/app/data")


def step(task_id: str, cmds: list[str], args: list[str], memory: str = "1Gi", retries: int = 1):
    return KubernetesPodOperator(
        task_id=task_id,
        name=task_id.replace("_", "-"),
        namespace="pipeline",
        image=IMAGE,
        image_pull_policy="Never",  # the image is loaded into kind with `kind load`, not pulled
        cmds=cmds,
        arguments=args,
        env_vars=ENV,
        volumes=[DATA],
        volume_mounts=[DATA_MOUNT],
        container_resources=k8s.V1ResourceRequirements(requests={"memory": "256Mi"}, limits={"memory": memory}),
        config_file="/opt/airflow/kubeconfig",
        in_cluster=False,
        get_logs=True,
        on_finish_action="delete_pod",
        startup_timeout_seconds=300,
        retries=retries,
    )


with DAG(
    "loan_propensity_train",
    start_date=datetime(2026, 10, 1),
    schedule="@weekly",
    catchup=False,
    max_active_runs=1,
    tags=["mlops"],
):
    train = step("train", ["python", "-m"], ["training.train", "--usecase", "loan_propensity"], memory="2Gi")
    # promote WITHOUT --approve: prints the gate result and exits 1 if REFUSED.
    # retries=0: a refusal is a verdict, not a transient failure.
    gate = step("report_gate", ["python", "-m"], ["training.promote", "--usecase", "loan_propensity"], retries=0)
    train >> gate


with DAG(
    "loan_propensity_predict",
    start_date=datetime(2026, 10, 1),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,
    tags=["mlops"],
):
    # Day 12 skeleton: only proves a pod can read the registry. Day 13 replaces it with batch scoring.
    step(
        "read_production",
        ["python", "-c"],
        [
            "from training import registry; c = registry.configure(); "
            "print({n: c.get_registered_model(n).aliases for n in ['loan_propensity_au']})"
        ],
    )
