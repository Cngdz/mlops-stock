"""Airflow only schedules and orders: every task is a pod in kind running the mlops-pipeline image.

Training stops at @staging. @production is set only by a human (training.promote --approve), so no
task here may ever pass --approve.

The synthetic data has no "today": its last feature day is 2026-01-30 and labels end 2025-12-31, so the dates are
DAG params (editable in "Trigger DAG w/ config"). In production they would be {{ ds }}-based.
"""
from datetime import datetime

from airflow import DAG
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from kubernetes.client import models as k8s

IMAGE = "mlops-pipeline:v1"
ENV = {  # in-cluster addresses: no port-forward from inside the cluster
    "MLFLOW_TRACKING_URI": "http://mlflow.mlops.svc.cluster.local",
    "MLFLOW_S3_ENDPOINT_URL": "http://minio.mlops.svc.cluster.local:9000",
    # Iceberg catalog (Postgres db iceberg_catalog); demo credentials, a real setup reads them from a Secret
    "ICEBERG_CATALOG_URI":
        "postgresql+psycopg2://postgres:mlflowpassword@postgres-postgresql.mlops.svc.cluster.local:5432/iceberg_catalog",
}
DATA = k8s.V1Volume(
    name="data",
    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name="pipeline-data"),
)
DATA_MOUNT = k8s.V1VolumeMount(name="data", mount_path="/app/data")


def step(task_id: str, cmds: list[str], args: list[str], memory: str = "1Gi", retries: int = 1, **kwargs):
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
        **kwargs,
    )


with DAG(
    "loan_propensity_train",
    start_date=datetime(2026, 10, 1),
    schedule="@weekly",
    catchup=False,
    max_active_runs=1,
    # as_of anchors the sliding train/validation/test split on the last day labeled by then. Empty = the run date,
    # so every scheduled retrain slides forward; trigger_retrain passes score_date.
    params={"as_of": ""},
    tags=["mlops"],
):
    train = step("train", ["python", "-m"],
                 ["training.train", "--usecase", "loan_propensity", "--as-of", "{{ params.as_of or ds }}"], memory="2Gi")
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
    params={"score_date": "2026-01-30", "cooldown_days": 7},
    tags=["mlops"],
):
    predict = step("predict", ["python", "-m"],
                   ["pipeline.predict", "--date", "{{ params.score_date }}"], memory="1536Mi")
    drift = step("drift", ["python", "-m"],
                 ["pipeline.drift", "--date", "{{ params.score_date }}"], memory="1536Mi")
    # exit 0 = critical drift, labels newer than the production data_end, cooldown passed;
    # exit 99 = skip (this task and the trigger turn pink, not red).
    # retries=1: exit 99 is a skip and is never retried, but a pod that fails to start (seen once: 300 s with no
    # scheduling event, not reproducible) or a transient MLflow/Postgres error deserves one more try.
    retrain_check = step("retrain_check", ["python", "-m"],
                         ["pipeline.drift", "--should-retrain", "--date", "{{ params.score_date }}",
                          "--cooldown-days", "{{ params.cooldown_days }}"],
                         retries=1, skip_on_exit_code=99)
    # The retrained model still stops at @staging: drift can start training, never promotion.
    retrain = TriggerDagRunOperator(task_id="trigger_retrain", trigger_dag_id="loan_propensity_train",
                                    conf={"as_of": "{{ params.score_date }}"})
    predict >> drift >> retrain_check >> retrain


with DAG(
    "loan_propensity_evaluate",
    start_date=datetime(2026, 10, 1),
    schedule="@weekly",
    catchup=False,
    max_active_runs=1,
    params={"start": "2025-12-25", "end": "2025-12-31"},
    tags=["mlops"],
):
    # Needs pred rows for the window (backfill: pipeline.predict --date <start> --end <end>) and closed labels.
    step("evaluate", ["python", "-m"],
         ["pipeline.evaluate", "--start", "{{ params.start }}", "--end", "{{ params.end }}"], memory="1536Mi")
