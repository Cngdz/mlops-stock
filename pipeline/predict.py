"""Batch predict: score the rows of a day with each segment's @production model, write Iceberg.

  python -m pipeline.predict --usecase loan_propensity --date 2026-01-30
  python -m pipeline.predict --usecase overdue_risk --date 2025-12-25 --end 2025-12-31     # backfill a range

Rows scored per use case (features.store.usecase_rows): loan_propensity every account of the fs_* partitions of T,
overdue_risk only overdue_eligible = 1 (segments lu, au), campaign_response the DELIVERED sends of T. Only days
COMPLETE in control.fs_status are read. Table monitoring.pred_<usecase>, partitioned by score_date; every row
carries model_name + model_version and feature_run_id (the feature run that wrote that day). Re-running a day
replaces that day. Batch does not go through KServe: it loads the same MLflow artifact and scores in one call.
"""
from __future__ import annotations

import argparse
import datetime as dt

import mlflow
import mlflow.sklearn
import pandas as pd
import pyarrow as pa
from pyiceberg.expressions import EqualTo

from features import store
from pipeline import catalog as lakehouse
from pipeline.common import date_range, parse_date, write_partition
from training import registry
from training.config import load_usecases

SCHEMA = pa.schema([
    ("master_account", pa.string()),
    ("score_date", pa.date32()),
    ("segment", pa.string()),
    ("score", pa.float64()),
    ("model_name", pa.string()),
    ("model_version", pa.string()),
    ("feature_run_id", pa.string()),
    ("scored_at", pa.timestamp("us")),
])
EVENT_SCHEMA = SCHEMA.insert(1, pa.field(store.EVENT_KEY, pa.string()))   # campaign_response: one row per send


def schema_for(uc) -> pa.Schema:
    return EVENT_SCHEMA if uc.dataset == store.CAMPAIGN_DATASET else SCHEMA


def score_segments(rows: pd.DataFrame, models: dict, features: list[str], segment_column: str | None,
                   keys: tuple[str, ...] = ()) -> tuple[pd.DataFrame, list[str]]:
    """models: segment -> (model_name, version, model with predict_proba). segment_column None = one model "all".
    Pure: no MLflow, no I/O. Returns the scored rows and the segments present that had no model (left unscored)."""
    groups = rows.groupby(segment_column, sort=True) if segment_column else [("all", rows)]
    parts, unscored = [], []
    for segment, part in groups:
        if segment not in models:
            unscored.append(str(segment))
            continue
        name, version, model = models[segment]
        parts.append(pd.DataFrame({
            "master_account": part["master_account"].astype(str).to_numpy(),
            **{k: part[k].astype(str).to_numpy() for k in keys},
            "score_date": part["report_date"].to_numpy(),
            "segment": str(segment),
            "score": model.predict_proba(part[features])[:, 1],
            "model_name": name,
            "model_version": str(version),
        }))
    columns = ["master_account", *keys, "score_date", "segment", "score", "model_name", "model_version"]
    scored = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)
    return scored, unscored


def production_models(client, usecase: str, segments: list[str]) -> dict:
    """Resolve @production to a fixed version first, then load THAT version: an alias moved mid-run cannot mix
    two versions inside one segment."""
    models = {}
    for segment in segments:
        name = registry.model_name(usecase, segment)
        mv = registry.production_version(client, name)
        if mv is None:
            print(f"{name}: no @production, segment {segment} not scored")
            continue
        models[segment] = (name, mv.version, mlflow.sklearn.load_model(f"models:/{name}/{mv.version}"))
    return models


def to_arrow(scored: pd.DataFrame, feature_run_id: str, scored_at: dt.datetime, schema: pa.Schema = SCHEMA) -> pa.Table:
    frame = scored.assign(feature_run_id=feature_run_id, scored_at=scored_at)
    frame["score_date"] = pd.to_datetime(frame["score_date"]).dt.date
    return pa.Table.from_pandas(frame[schema.names], schema=schema, preserve_index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--usecase", required=True)
    parser.add_argument("--date", type=parse_date, required=True)
    parser.add_argument("--end", type=parse_date, help="last day of a backfill range (inclusive)")
    args = parser.parse_args()

    uc = load_usecases()[args.usecase]
    client = registry.configure()
    models = production_models(client, uc.name, uc.segments or ["all"])
    if not models:
        raise SystemExit(f"{uc.name}: no segment has a @production model")
    catalog = lakehouse.load()
    lakehouse.ensure_namespace(catalog)
    table, schema = f"{lakehouse.NAMESPACE}.pred_{uc.name}", schema_for(uc)
    keys = (store.EVENT_KEY,) if schema is EVENT_SCHEMA else ()
    for day in date_range(args.date, args.end):
        rows, run_id = store.usecase_rows(catalog, uc, day)
        scored, unscored = score_segments(rows, models, uc.features, uc.segment_column if uc.segments else None, keys)
        write_partition(catalog, table, to_arrow(scored, run_id, dt.datetime.now(dt.UTC).replace(tzinfo=None), schema),
                        "score_date", EqualTo("score_date", day.isoformat()))
        versions = scored.groupby("segment")["model_version"].first().to_dict()
        print(f"{table} {day}: {len(scored)} rows, versions {versions}"
              + (f", unscored segments {unscored}" if unscored else ""), flush=True)


if __name__ == "__main__":
    main()
