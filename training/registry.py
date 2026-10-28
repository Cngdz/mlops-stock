"""Day 7 MLflow side: log each (use case, segment) run, register the selected model, tag the gate result.

Registered model name: <usecase>_<segment> (e.g. loan_propensity_au); Day 9 derives the
InferenceService name from it. New versions get alias @staging. @production is never set here:
promote.py does that after approval, and only for a gate-passing set of versions.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import mlflow
import mlflow.sklearn
import numpy as np
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from mlflow.models import infer_signature
from sklearn.metrics import roc_auc_score

from training.config import UseCase
from training.data import SegmentData
from training.evaluate import recall_at_alert_rate
from training.promotion import GateConfig, GateDecision, evaluate_gate

STAGING, PRODUCTION = "staging", "production"


def configure() -> MlflowClient:
    """Local defaults = the port-forwards from the Day 7 runbook; override with the usual env vars."""
    for stream in (sys.stdout, sys.stderr):  # MLflow prints emoji; Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("MLFLOW_TRACKING_URI", "http://127.0.0.1:5050")
    os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadmin")
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    return MlflowClient()


def model_name(usecase: str, segment: str) -> str:
    return f"{usecase}_{segment}"


def log_segment(uc: UseCase, data: SegmentData, result, lineage: dict) -> str:
    """One MLflow run per segment: both models' metrics, the selected model registered. Returns version."""
    selected = result.metrics[result.selected]
    mlflow.set_experiment(uc.name)
    with mlflow.start_run(run_name=f"{data.segment}-{lineage['train_run_id']}"):
        mlflow.set_tags({**{k: str(v) for k, v in lineage.items() if k != "libraries"},
                         "usecase": uc.name, "segment": data.segment, "selected_model": result.selected})
        mlflow.log_params({"model_type": result.selected, "seed": uc.seed, "label": uc.label,
                           "feature_hash": uc.feature_hash(), "n_features": len(uc.features),
                           "threshold": selected["threshold"], "threshold_rule": uc.threshold["rule"],
                           **{f"lgbm_{k}": v for k, v in uc.lgbm.items()},
                           **({"best_iteration": selected["best_iteration"]} if "best_iteration" in selected else {})})
        for name, r in result.metrics.items():
            for split in ("validation", "test"):
                for key in ("roc_auc", "pr_auc", "precision", "recall", "f1"):
                    mlflow.log_metric(f"{name}_{split}_{key}", r[split][key])
                    if name == result.selected:
                        mlflow.log_metric(f"{split}_{key}", r[split][key])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.json"
            path.write_text(json.dumps(result.metrics, indent=2), encoding="utf-8")
            mlflow.log_artifact(str(path))
        X_example = data.X["validation"].head(5)
        pipe = result.models[result.selected]
        info = mlflow.sklearn.log_model(
            sk_model=pipe, name="model", registered_model_name=model_name(uc.name, data.segment),
            signature=infer_signature(X_example, pipe.predict_proba(X_example)),
            input_example=X_example, pyfunc_predict_fn="predict_proba",
            # MLflow 3 defaults to skops, which rejects LightGBM types unless whitelisted. cloudpickle is
            # what the KServe/MLServer mlflow runtime loads reliably; artifacts come only from this pipeline.
            serialization_format="cloudpickle")
    version = str(info.registered_model_version)
    client = MlflowClient()
    name = model_name(uc.name, data.segment)
    for key, value in {"threshold": selected["threshold"], "model_type": result.selected,
                       "train_run_id": lineage["train_run_id"], "feature_run_id": lineage["feature_run_id"],
                       "data_end": lineage["data_end"],
                       "test_roc_auc": selected["test"]["roc_auc"], "test_recall": selected["test"]["recall"]}.items():
        client.set_model_version_tag(name, version, key, str(value))
    client.set_registered_model_alias(name, STAGING, version)
    return version


def production_version(client: MlflowClient, name: str):
    try:
        return client.get_model_version_by_alias(name, PRODUCTION)
    except MlflowException:
        return None  # no registered model yet, or no @production alias


def compare_with_champion(client: MlflowClient, uc: UseCase, data: SegmentData,
                          result) -> tuple[dict, dict | None, str]:
    """Gate inputs for one segment: (challenger, champion, note), each {"roc_auc", "recall"}.

    Both models score the SAME test rows. Recall is compared at the champion's operating point:
    the share of rows @production flags at its own threshold (its alert rate); the challenger is
    given the same number of alerts. Thresholds picked separately (max-F1 on validation) move a
    lot on rare-positive segments, so raw recall at each model's own threshold is not comparable.
    No @production: baseline, challenger recall at its own threshold.
    Champion unable to score these rows (feature schema change): its recorded test metrics."""
    y = data.y["test"]
    own = result.metrics[result.selected]["test"]
    name = model_name(uc.name, data.segment)
    champion = production_version(client, name)
    if champion is None:
        return {"roc_auc": own["roc_auc"], "recall": own["recall"]}, None, "no @production"
    try:
        champ_proba = mlflow.sklearn.load_model(f"models:/{name}@{PRODUCTION}").predict_proba(data.X["test"])[:, 1]
        threshold = float(champion.tags["threshold"])
    except (KeyError, ValueError) as err:
        recorded = {"roc_auc": float(champion.tags["test_roc_auc"]), "recall": float(champion.tags["test_recall"])}
        return ({"roc_auc": own["roc_auc"], "recall": own["recall"]}, recorded,
                f"v{champion.version} recorded metrics (could not rescore: {err})")
    alert_rate = float(np.mean(champ_proba >= threshold))
    new_proba = result.models[result.selected].predict_proba(data.X["test"])[:, 1]
    challenger = {"roc_auc": own["roc_auc"], "recall": recall_at_alert_rate(y, new_proba, alert_rate)}
    champ = {"roc_auc": float(roc_auc_score(y, champ_proba)), "recall": recall_at_alert_rate(y, champ_proba, alert_rate)}
    return challenger, champ, f"v{champion.version} on same test rows, alert rate {alert_rate:.1%}"


def record_gate(client: MlflowClient, uc: UseCase, versions: dict[str, str], decision: GateDecision) -> None:
    for segment, version in versions.items():
        name = model_name(uc.name, segment)
        client.set_model_version_tag(name, version, "promotion_gate", decision.status)
        client.set_model_version_tag(name, version, "gate_reason", decision.reasons[segment][:500])


def gate_usecase(client: MlflowClient, uc: UseCase, challengers: dict[str, dict], champions: dict[str, dict | None],
                 versions: dict[str, str], cfg: GateConfig) -> GateDecision:
    decision = evaluate_gate(challengers, champions, cfg)
    record_gate(client, uc, versions, decision)
    return decision
