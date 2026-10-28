"""Airflow only schedules and orders: every task is a pod in kind running the mlops-pipeline image.

Training stops at @staging. @production is set only by a human (training.promote --approve), so no
task here may ever pass --approve.

DAGs:
  feature_store_daily        Gold -> fs_* partition of day T (Iceberg, MinIO), then the COMPLETE marker in control.fs_status
  feature_store_maintenance  weekly Iceberg housekeeping of fs_*
  loan_propensity_train / _predict / _evaluate     (predict waits for the feature store day first)

The synthetic data has no "today": its last feature day is 2026-01-30 and labels end 2025-12-31, so the dates are
DAG params (editable in "Trigger DAG w/ config"). In production they would be {{ ds }}-based; feature_store_daily
already defaults to yesterday: trigger it with {"report_date": "2026-01-30"} for the synthetic data.
"""
from datetime import datetime, timedelta

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


# ---- Feature store -------------------------------------------------------------------------------------------
REPORT_DATE = "{{ params.report_date or data_interval_end | ds }}"
STAGING = "tmp_fs_{{ (params.report_date or data_interval_end | ds) | replace('-', '') }}"

with DAG(
    "feature_store_daily",
    start_date=datetime(2026, 10, 1),
    schedule="0 23 * * *",  # 23:00 UTC = 06:00 Asia/Ho_Chi_Minh, before the 07:00 predict DAG
    catchup=False,
    max_active_runs=1,
    params={"report_date": ""},  # empty = yesterday (data interval end)
    tags=["mlops", "features"],
):
    # Gold not there yet is the expected failure: retry for an hour before giving up.
    check = step("check_source", ["python", "-m"], ["features.check_source", "--date", REPORT_DATE], retries=4,
                 retry_delay=timedelta(minutes=15))
    # Reads the small Gold tables in full (accumulated values) and the large ones for 30 days: 0.7 GB measured on the
    # synthetic year, so 2Gi leaves room for a longer history.
    compute = step("compute_features", ["python", "-m"],
                   ["features.compute", "--date", REPORT_DATE, "--out", STAGING], memory="2Gi")
    write = step("write_partitions", ["python", "-m"],
                 ["features.write", "--date", REPORT_DATE, "--mode", "overwrite-partition", "--staging", STAGING])
    # retries=0: a failed gate is a verdict on the data, not a transient error. Day T stays unpublished.
    quality = step("quality_gate", ["python", "-m"], ["features.quality", "--date", REPORT_DATE], retries=0)
    publish = step("publish_marker", ["python", "-m"], ["features.publish", "--date", REPORT_DATE])
    check >> compute >> write >> quality >> publish

with DAG(
    "feature_store_maintenance",
    start_date=datetime(2026, 10, 1),
    schedule="0 20 * * 6",  # Saturday 20:00 UTC = Sunday 03:00 VN, away from the daily run
    catchup=False,
    max_active_runs=1,
    tags=["mlops", "features"],
):
    step("iceberg_maintenance", ["python", "-m"],
         ["features.maintenance", "--retention-months", "12", "--expire-snapshots", "--remove-orphans"],
         memory="1536Mi")


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
    # The sensor: scores only a day the feature store marked COMPLETE (control.fs_status). Each try polls for 30 min;
    # up to 12 tries give a 6 h wait, then the run fails (no partition, or a failed quality gate).
    wait = step("wait_features", ["python", "-m"],
                ["features.status", "--date", "{{ params.score_date }}", "--wait", "--timeout-minutes", "30"],
                retries=11, retry_delay=timedelta(minutes=1))
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
    wait >> predict >> drift >> retrain_check >> retrain


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
