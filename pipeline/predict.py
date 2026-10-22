"""Day 13 batch predict: score every account of a day with each segment's @production model, write Iceberg.

  python -m pipeline.predict --date 2026-01-30                      # one day
  python -m pipeline.predict --date 2025-12-25 --end 2025-12-31     # backfill a range (one partition per day)

Table monitoring.pred_<usecase>, partitioned by score_date. Every row carries model_name + model_version (which model
produced it) and feature_run_id (which feature run it read). Re-running a day replaces that day. Batch does not go
through KServe: it loads the same MLflow artifact and scores the whole table in one call.
"""
from __future__ import annotations

import argparse
import datetime as dt

import mlflow
import mlflow.sklearn
import pandas as pd
import pyarrow as pa
from pyiceberg.expressions import EqualTo

from pipeline import catalog as lakehouse
from pipeline.common import date_range, feature_run, load_settings, parse_date, read_snapshot, write_partition
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


def score_segments(snapshot: pd.DataFrame, models: dict, features: list[str], segment_column: str,
                   ) -> tuple[pd.DataFrame, list[str]]:
    """models: segment -> (model_name, version, model with predict_proba). Pure: no MLflow, no I/O.
    Returns the scored rows and the segments present in the snapshot that had no model (left unscored)."""
    parts, unscored = [], []
    for segment, rows in snapshot.groupby(segment_column, sort=True):
        if segment not in models:
            unscored.append(str(segment))
            continue
        name, version, model = models[segment]
        parts.append(pd.DataFrame({
            "master_account": rows["master_account"].astype(str).to_numpy(),
            "score_date": rows["report_date"].to_numpy(),
            "segment": str(segment),
            "score": model.predict_proba(rows[features])[:, 1],
            "model_name": name,
            "model_version": str(version),
        }))
    scored = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=SCHEMA.names)
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


def to_arrow(scored: pd.DataFrame, feature_run_id: str, scored_at: dt.datetime) -> pa.Table:
    frame = scored.assign(feature_run_id=feature_run_id, scored_at=scored_at)
    frame["score_date"] = pd.to_datetime(frame["score_date"]).dt.date
    return pa.Table.from_pandas(frame[SCHEMA.names], schema=SCHEMA, preserve_index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=parse_date, required=True)
    parser.add_argument("--end", type=parse_date, help="last day of a backfill range (inclusive)")
    args = parser.parse_args()

    usecase = load_settings()["usecase"]
    uc = load_usecases()[usecase]
    client = registry.configure()
    run_dir, run_id = feature_run()
    models = production_models(client, usecase, uc.segments or ["all"])
    if not models:
        raise SystemExit(f"{usecase}: no segment has a @production model")
    catalog = lakehouse.load()
    lakehouse.ensure_namespace(catalog)
    table = f"{lakehouse.NAMESPACE}.pred_{usecase}"
    for day in date_range(args.date, args.end):
        scored, unscored = score_segments(read_snapshot(run_dir, day), models, uc.features, uc.segment_column)
        write_partition(catalog, table, to_arrow(scored, run_id, dt.datetime.now(dt.UTC).replace(tzinfo=None)),
                        "score_date", EqualTo("score_date", day.isoformat()))
        versions = scored.groupby("segment")["model_version"].first().to_dict()
        print(f"{table} {day}: {len(scored)} rows, versions {versions}"
              + (f", unscored segments {unscored}" if unscored else ""), flush=True)


if __name__ == "__main__":
    main()
