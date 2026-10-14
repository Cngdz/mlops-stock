"""Feast definitions: 1 entity, 6 feature views (one per fs_* table), 3 feature services.

Sources point at the approved Day 4 run (data/features/current.json), or at FEAST_RUN_DIR
when set (tests, backfills). Each fs_* row carries event_timestamp = 23:59:59 Asia/Ho_Chi_Minh
on report_date, so a request at time T gets the latest COMPLETE daily snapshot at or before T.
Re-run `feast apply` after every new approved run.
"""
from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pyarrow.parquet as pq
from feast import Entity, FeatureService, FeatureView, Field, FileSource, ValueType
from feast.types import Float64, Int64, String

ROOT = Path(__file__).resolve().parents[1]
FEATURE_GROUPS = ["fs_demographic", "fs_trading_behavior", "fs_margin_balance",
                  "fs_asset_balance", "fs_portfolio", "fs_campaign"]
NON_FEATURE_COLUMNS = {"master_account", "report_date", "event_timestamp"}
# Recorded but not a model input: holdings are not reconciled with asset_value (decisions 9.2).
EXCLUDED_FROM_MODELS = {"portfolio_value"}
DTYPES = {"int64": Int64, "double": Float64, "string": String, "large_string": String}


def run_dir() -> Path:
    if os.environ.get("FEAST_RUN_DIR"):
        return Path(os.environ["FEAST_RUN_DIR"])
    pointer = json.loads((ROOT / "data/features/current.json").read_text(encoding="utf-8"))
    return ROOT / "data/features/day4_runs" / pointer["run_id"]  # portable; ignores the absolute Windows path


RUN_DIR = run_dir()

account = Entity(name="account", join_keys=["master_account"], value_type=ValueType.STRING,
                 description="Securities account (10-digit string, keeps leading zeros)")


def _view(name: str) -> FeatureView:
    path = RUN_DIR / f"{name}.parquet"
    schema = pq.read_schema(path)
    fields = []
    for column in schema:
        if column.name in NON_FEATURE_COLUMNS:
            continue
        dtype = DTYPES.get(str(column.type))
        if dtype is None:
            raise TypeError(f"{name}.{column.name}: unsupported type {column.type}; cast it in Day 4")
        fields.append(Field(name=column.name, dtype=dtype))
    return FeatureView(
        name=name, entities=[account], schema=fields,
        # Daily dense panel: one day of lookback. A request after an account stops having
        # snapshots (closed/dormant) finds nothing instead of a stale value.
        ttl=timedelta(days=1),
        source=FileSource(name=f"{name}_source", path=str(path), timestamp_field="event_timestamp"),
        tags={"day4_run": RUN_DIR.name},
    )


views = {name: _view(name) for name in FEATURE_GROUPS}
fs_demographic, fs_trading_behavior, fs_margin_balance, fs_asset_balance, fs_portfolio, fs_campaign = views.values()


def _model_features(view: FeatureView):
    return view[[f.name for f in view.features if f.name not in EXCLUDED_FROM_MODELS]]


ACCOUNT_VIEWS = [fs_demographic, fs_trading_behavior, fs_margin_balance, fs_asset_balance, fs_portfolio]

loan_propensity = FeatureService(
    name="loan_propensity", features=[_model_features(v) for v in ACCOUNT_VIEWS + [fs_campaign]],
    description="loan_label_next; entity_df = loan_overdue_labels (end of day D)")
overdue_risk = FeatureService(
    name="overdue_risk", features=[_model_features(v) for v in ACCOUNT_VIEWS + [fs_campaign]],
    description="overdue_label_next_30d; entity_df = loan_overdue_labels WHERE overdue_eligible = 1")
# fs_campaign counts sends made on D itself, which would include the send being scored.
# Campaign history comes from campaign_labels (computed per send, excluding it).
campaign_response = FeatureService(
    name="campaign_response", features=[_model_features(v) for v in ACCOUNT_VIEWS],
    description="campaign_response_label_14d; entity_df = campaign_labels at exact sent_at (gets D-1 snapshot)")
