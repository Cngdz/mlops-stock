"""Day 13 drift: compare the model features of a day with the training reference (Evidently, column-level).

  python -m pipeline.drift --date 2026-01-30                          # vs drift.reference_date: the official check
  python -m pipeline.drift --date 2026-01-30 --reference 2026-01-29   # ad-hoc comparison (no MLflow tags)
  python -m pipeline.drift --should-retrain --date 2026-01-30         # exit 0 = trigger retrain, 99 = skip

Drift Ratio = drifted features / model features -> severity (monitoring.yaml). Result: monitoring.drift_<usecase>,
HTML report in s3://warehouse/reports/drift/. The official check also tags each @production version with
monitoring.driftSeverity. Drift alone does not prove the model got worse (pipeline.evaluate does, with labels);
it is the early warning available before the labels exist.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

import boto3
import pandas as pd
import pyarrow as pa
from pyiceberg.expressions import And, EqualTo

from pipeline import catalog as lakehouse
from pipeline.common import as_json, feature_run, load_settings, parse_date, read_snapshot, write_partition
from training import registry
from training.config import load_usecases

SKIP_EXIT = 99  # Airflow KubernetesPodOperator(skip_on_exit_code=99): "no retrain" is a skip, not a failure
SEVERITIES = ("none", "medium", "high", "critical")
SCHEMA = pa.schema([
    ("current_date", pa.date32()),
    ("reference_date", pa.date32()),
    ("n_features", pa.int64()),
    ("n_drifted", pa.int64()),
    ("drift_ratio", pa.float64()),
    ("severity", pa.string()),
    ("drifted_columns", pa.string()),
    ("column_scores", pa.string()),
    ("report_uri", pa.string()),
    ("official", pa.bool_()),
    ("checked_at", pa.timestamp("us")),
])


def severity_for(ratio: float, bounds: dict) -> str:
    """bounds = upper limits (inclusive) of none/medium/high; anything above high is critical. Pure."""
    for name in ("none", "medium", "high"):
        if ratio <= bounds[name]:
            return name
    return "critical"


def column_results(report: dict) -> list[dict]:
    """Per-column verdicts from an Evidently report dict. Distance methods (Wasserstein, Jensen-Shannon...) drift
    when score >= threshold; p-value tests drift when p < threshold. Pure."""
    out = []
    for metric in report["metrics"]:
        cfg = metric.get("config", {})
        if not cfg.get("type", "").endswith("ValueDrift"):
            continue
        score, threshold, method = float(metric["value"]), float(cfg["threshold"]), cfg["method"]
        drifted = score < threshold if "p_value" in method.lower() else score >= threshold
        out.append({"column": cfg["column"], "method": method, "score": score, "threshold": threshold,
                    "drifted": drifted})
    return out


def should_retrain(severity: str, last_trained: dt.datetime | None, now: dt.datetime, cooldown_days: int,
                   ) -> tuple[bool, str]:
    """Only critical drift retrains, and not again within the cooldown: retraining on unchanged data cannot fix a
    lasting drift, it only piles up versions. Pure."""
    if severity != "critical":
        return False, f"severity {severity}: no retrain"
    if last_trained is not None and now - last_trained < dt.timedelta(days=cooldown_days):
        return False, f"critical, but last training {last_trained:%Y-%m-%d %H:%M} is within {cooldown_days} days"
    return True, "critical drift and cooldown passed: retrain"


def upload_html(snapshot, key: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.html"
        snapshot.save_html(str(path))
        boto3.client("s3", endpoint_url=os.environ.get("MLFLOW_S3_ENDPOINT_URL", "http://127.0.0.1:9000"),
                     aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
                     aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"),
                     region_name="us-east-1").upload_file(str(path), "warehouse", key)
    return f"s3://warehouse/{key}"


def run_check(day: dt.date, reference: dt.date, official: bool) -> str:
    from evidently import Report
    from evidently.presets import DataDriftPreset

    settings = load_settings()
    usecase = settings["usecase"]
    uc = load_usecases()[usecase]
    run_dir, _ = feature_run()
    ref, cur = read_snapshot(run_dir, reference)[uc.features], read_snapshot(run_dir, day)[uc.features]
    snapshot = Report([DataDriftPreset(columns=uc.features)]).run(reference_data=ref, current_data=cur)
    columns = column_results(snapshot.dict())
    drifted = [c["column"] for c in columns if c["drifted"]]
    ratio = len(drifted) / len(uc.features)
    severity = severity_for(ratio, settings["drift"]["severity"])
    uri = upload_html(snapshot, f"reports/drift/{usecase}/{day}_vs_{reference}.html")

    row = pd.DataFrame([{
        "current_date": day, "reference_date": reference, "n_features": len(uc.features), "n_drifted": len(drifted),
        "drift_ratio": ratio, "severity": severity, "drifted_columns": as_json(drifted),
        "column_scores": as_json({c["column"]: round(c["score"], 4) for c in columns}), "report_uri": uri,
        "official": official, "checked_at": dt.datetime.now(dt.UTC).replace(tzinfo=None)}])
    catalog = lakehouse.load()
    lakehouse.ensure_namespace(catalog)
    write_partition(catalog, f"{lakehouse.NAMESPACE}.drift_{usecase}",
                    pa.Table.from_pandas(row[SCHEMA.names], schema=SCHEMA, preserve_index=False), "current_date",
                    And(EqualTo("current_date", day.isoformat()), EqualTo("reference_date", reference.isoformat())))
    print(f"drift {day} vs {reference}: {len(drifted)}/{len(uc.features)} features ({ratio:.0%}) -> {severity}")
    print(f"  drifted: {drifted}")
    print(f"  report: {uri}")

    if official:  # ad-hoc comparisons must not overwrite the severity shown on the production versions
        client = registry.configure()
        for segment in uc.segments or ["all"]:
            mv = registry.production_version(client, registry.model_name(usecase, segment))
            if mv is not None:
                client.set_model_version_tag(mv.name, mv.version, "monitoring.driftSeverity", severity)
                client.set_model_version_tag(mv.name, mv.version, "monitoring.driftCheckedFor", day.isoformat())
    return severity


def last_training(client, usecase: str, segments: list[str]) -> dt.datetime | None:
    stamps = [int(v.creation_timestamp) for s in segments
              for v in client.search_model_versions(f"name='{registry.model_name(usecase, s)}'")]
    return dt.datetime.fromtimestamp(max(stamps) / 1000, dt.UTC).replace(tzinfo=None) if stamps else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=parse_date, required=True)
    parser.add_argument("--reference", type=parse_date, help="override drift.reference_date (ad-hoc, no tags)")
    parser.add_argument("--should-retrain", action="store_true", help=f"exit 0 = retrain, {SKIP_EXIT} = skip")
    parser.add_argument("--cooldown-days", type=int, help="override drift.retrain_cooldown_days")
    args = parser.parse_args()

    settings = load_settings()
    official_ref = parse_date(settings["drift"]["reference_date"])
    if not args.should_retrain:
        reference = args.reference or official_ref
        run_check(args.date, reference, official=reference == official_ref)
        return

    usecase = settings["usecase"]
    uc = load_usecases()[usecase]
    rows = lakehouse.load().load_table(f"{lakehouse.NAMESPACE}.drift_{usecase}").scan(
        row_filter=And(EqualTo("current_date", args.date.isoformat()),
                       EqualTo("reference_date", official_ref.isoformat()))).to_pandas()
    if rows.empty:
        raise SystemExit(f"no official drift check for {args.date}: run pipeline.drift --date {args.date} first")
    cooldown = settings["drift"]["retrain_cooldown_days"] if args.cooldown_days is None else args.cooldown_days
    retrain, reason = should_retrain(rows["severity"].iloc[-1],
                                     last_training(registry.configure(), usecase, uc.segments or ["all"]),
                                     dt.datetime.now(dt.UTC).replace(tzinfo=None), cooldown)
    print(reason)
    sys.exit(0 if retrain else SKIP_EXIT)


if __name__ == "__main__":
    main()
