"""Airflow (namespace airflow) only schedules and orders: every task is a pod in namespace pipeline running the
mlops-pipeline image from the cluster registry, created with the in-cluster service account (RBAC:
pipeline/k8s/40-airflow-rbac.yaml).

DAGs:
  feature_store_daily        Gold -> fs_* partition of day T, then the COMPLETE marker in control.fs_status
  feature_store_maintenance  weekly Iceberg housekeeping of fs_*
  <usecase>_train            training data -> train -> champion gate, one DAG per use case in USECASES
  <usecase>_predict          wait for the fs day -> predict -> drift -> retrain_check -> trigger <usecase>_train
  <usecase>_evaluate         live AUC vs training AUC once labels have matured

Training stops at @staging. @production is set only by a human (training.promote --approve), so no task here may
ever pass --approve.

The synthetic data has no "today": its last feature day is 2026-01-30 and labels end 2025-12-31, so scoring and
evaluation dates are DAG params (editable in "Trigger DAG w/ config"). feature_store_daily defaults to yesterday
(the data interval end) as in production; trigger it with {"report_date": "2026-01-30"} for the synthetic data.
"""
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.common.sql.sensors.sql import SqlSensor
from kubernetes.client import models as k8s

# Set in the Airflow Helm values (infra/helm-values/airflow-values.yaml); the defaults match them.
IMAGE = os.environ.get("MLOPS_PIPELINE_IMAGE", "harbor.local/mlops/mlops-pipeline:v1")
PULL_SECRET = os.environ.get("MLOPS_IMAGE_PULL_SECRET", "harbor-pull")
ENV = {  # in-cluster service DNS: no port-forward inside the cluster
    "MLFLOW_TRACKING_URI": "http://mlflow.mlops.svc.cluster.local",
    "MLFLOW_S3_ENDPOINT_URL": "http://minio.mlops.svc.cluster.local:9000",
    # Iceberg catalog and control.fs_status (Postgres db iceberg_catalog); demo credentials, a real setup reads
    # them from a Secret
    "ICEBERG_CATALOG_URI":
        "postgresql+psycopg2://postgres:mlflowpassword@postgres-postgresql.mlops.svc.cluster.local:5432/iceberg_catalog",
}
DATA = k8s.V1Volume(
    name="data",
    persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name="pipeline-data"),
)
DATA_MOUNT = k8s.V1VolumeMount(name="data", mount_path="/app/data")
# Scoring defaults per use case. campaign_response scores DELIVERED sends, and the synthetic campaigns stop on
# 2026-01-16 (14 days before the last Gold day, so every send has a matured label).
USECASES = {
    "loan_propensity": {"score_date": "2026-01-30"},
    "overdue_risk": {"score_date": "2026-01-30"},
    "campaign_response": {"score_date": "2026-01-16"},
}
EVALUATE_WINDOW = {"start": "2025-12-25", "end": "2025-12-31"}


def step(task_id: str, module: str, args: list[str], memory: str = "1Gi", retries: int = 1, **kwargs):
    return KubernetesPodOperator(
        task_id=task_id,
        name=task_id.replace("_", "-"),
        namespace="pipeline",
        image=IMAGE,
        image_pull_policy="Always",  # the tag is re-pushed for each code version
        image_pull_secrets=[k8s.V1LocalObjectReference(name=PULL_SECRET)],
        cmds=["python", "-m"],
        arguments=[module, *args],
        env_vars=ENV,
        volumes=[DATA],
        volume_mounts=[DATA_MOUNT],
        container_resources=k8s.V1ResourceRequirements(requests={"memory": "256Mi"}, limits={"memory": memory}),
        in_cluster=True,
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
    schedule="0 23 * * *",  # 23:00 UTC = 06:00 Asia/Ho_Chi_Minh, before the 07:00 predict DAGs
    catchup=False,
    max_active_runs=1,  # day T+1 continues the state of day T
    params={"report_date": ""},  # empty = yesterday (data interval end)
    tags=["mlops", "features"],
):
    # Gold not there yet is the expected failure: retry for an hour before giving up.
    check = step("check_source", "features.check_source", ["--date", REPORT_DATE], retries=4,
                 retry_delay=timedelta(minutes=15))
    compute = step("compute_features", "features.compute", ["--date", REPORT_DATE, "--out", STAGING],
                   memory="1536Mi")
    write = step("write_partitions", "features.write",
                 ["--date", REPORT_DATE, "--mode", "overwrite-partition", "--staging", STAGING])
    # retries=0: a failed gate is a verdict on the data, not a transient error. Day T stays unpublished.
    quality = step("quality_gate", "features.quality", ["--date", REPORT_DATE], retries=0)
    publish = step("publish_marker", "features.publish", ["--date", REPORT_DATE])
    check >> compute >> write >> quality >> publish

with DAG(
    "feature_store_maintenance",
    start_date=datetime(2026, 10, 1),
    schedule="0 20 * * 6",  # Saturday 20:00 UTC = Sunday 03:00 VN, away from the daily runs
    catchup=False,
    max_active_runs=1,
    tags=["mlops", "features"],
):
    step("iceberg_maintenance", "features.maintenance",
         ["--retention-months", "12", "--expire-snapshots", "--remove-orphans", "--keep-training-runs", "12"],
         memory="1536Mi")

# ---- One train / predict / evaluate DAG set per use case -----------------------------------------------------
for usecase, defaults in USECASES.items():
    with DAG(
        f"{usecase}_train",
        start_date=datetime(2026, 10, 1),
        schedule="@weekly",
        catchup=False,
        max_active_runs=1,
        tags=["mlops", usecase],
    ):
        # The run dir is named after the DAG run, so train reads exactly what build_training wrote even if
        # another use case's DAG moves data/features/current.json meanwhile.
        run_id = f"{usecase}_{{{{ ts_nodash }}}}"
        build = step("build_training", "features.build_training", ["--run-id", run_id], memory="3Gi", retries=0)
        train = step("train", "training.train",
                     ["--usecase", usecase, "--run-dir", f"data/features/day4_runs/{run_id}"], memory="2Gi")
        # promote WITHOUT --approve: prints the gate result and exits 1 if REFUSED.
        # retries=0: a refusal is a verdict, not a transient failure.
        gate = step("report_gate", "training.promote", ["--usecase", usecase], retries=0)
        build >> train >> gate

    with DAG(
        f"{usecase}_predict",
        start_date=datetime(2026, 10, 1),
        schedule="@daily",
        catchup=False,
        max_active_runs=1,
        params={"score_date": defaults["score_date"], "cooldown_days": 7},
        tags=["mlops", usecase],
    ):
        # Scores only a day the feature store published: poke control.fs_status every 5 min for up to 6 h,
        # releasing the worker slot between pokes.
        wait = SqlSensor(
            task_id="wait_features",
            conn_id="feature_store_db",
            sql="SELECT count(*) FROM control.fs_status WHERE report_date = %(day)s AND status = 'COMPLETE'",
            parameters={"day": "{{ params.score_date }}"},
            mode="reschedule",
            poke_interval=300,
            timeout=6 * 3600,
        )
        predict = step("predict", "pipeline.predict",
                       ["--usecase", usecase, "--date", "{{ params.score_date }}"], memory="1536Mi")
        # exit 99 = no row to compare that day (no campaign sent): skipped, as are the tasks after it.
        drift = step("drift", "pipeline.drift", ["--usecase", usecase, "--date", "{{ params.score_date }}"],
                     memory="1536Mi", skip_on_exit_code=99)
        # exit 0 = critical drift past the cooldown, exit 99 = skip (this task and the trigger turn pink, not red).
        # retries=1: exit 99 is a skip and is never retried, but a pod that fails to start or a transient
        # MLflow/Postgres error deserves one more try.
        retrain_check = step("retrain_check", "pipeline.drift",
                             ["--usecase", usecase, "--should-retrain", "--date", "{{ params.score_date }}",
                              "--cooldown-days", "{{ params.cooldown_days }}"],
                             retries=1, skip_on_exit_code=99)
        # The retrained model still stops at @staging: drift can start training, never promotion.
        retrain = TriggerDagRunOperator(task_id="trigger_retrain", trigger_dag_id=f"{usecase}_train")
        wait >> predict >> drift >> retrain_check >> retrain

    with DAG(
        f"{usecase}_evaluate",
        start_date=datetime(2026, 10, 1),
        schedule="@weekly",
        catchup=False,
        max_active_runs=1,
        params=dict(EVALUATE_WINDOW),
        tags=["mlops", usecase],
    ):
        # Needs pred rows for the window (backfill: pipeline.predict --date <start> --end <end>) and matured labels.
        step("evaluate", "pipeline.evaluate",
             ["--usecase", usecase, "--start", "{{ params.start }}", "--end", "{{ params.end }}"], memory="1536Mi")
