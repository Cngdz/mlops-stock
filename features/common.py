"""Shared by every feature step: the fs_* contract, settings, catalogs, staging dirs."""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path

import yaml
from pyiceberg.catalog import Catalog

from pipeline import catalog as lakehouse

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = Path(__file__).with_name("settings.yaml")
SQL_DIR = Path(__file__).with_name("sql")
STAGING_ROOT = ROOT / "data/features/staging"

FEATURE_CONTRACT = "day4-v5"
NAMESPACE = lakehouse.FEATURES_NAMESPACE
KEYS = ["master_account", "report_date"]
KEY_TYPES = {"master_account": "string", "report_date": "date", "event_timestamp": "timestamptz"}
# Contract = column -> Iceberg type, per table (docs/feature_contract.md describes each column).
GROUPS: dict[str, dict[str, str]] = {
    "fs_demographic": {"account_age_days": "long", "margin_segment": "string"},
    "fs_trading_behavior": {"trade_count_7d": "long", "trade_count_30d": "long", "total_trading_amount_7d": "long",
                            "total_trading_amount_30d": "long", "active_trading_days_30d": "long"},
    "fs_margin_balance": {"margin_debt": "long", "margin_limit": "long", "margin_utilization_ratio": "double",
                          "debt_change_7d": "long", "over_limit_streak": "long", "over_limit_days_30d": "long"},
    "fs_asset_balance": {"cash_balance": "long", "asset_value": "long", "collateral_value": "long",
                         "cash_to_asset_ratio": "double", "NAV": "long"},
    "fs_portfolio": {"portfolio_value": "long", "holding_symbol_count": "long", "portfolio_concentration": "double",
                     "unrealized_loss_ratio": "double", "risky_asset_ratio": "double"},
    "fs_campaign": {"campaign_count_30d": "long", "days_since_last_campaign": "long", "has_campaign_history": "long"},
}
FS_TABLES = list(GROUPS)
FEATURE_COLUMNS = [c for columns in GROUPS.values() for c in columns]
# Feast timestamp convention, kept on fs_*: a daily snapshot for D is valid at 23:59:59 Asia/Ho_Chi_Minh on D.
EOD_TIMESTAMP = ("timezone('Asia/Ho_Chi_Minh', CAST(report_date AS TIMESTAMP) + INTERVAL 1 DAY - INTERVAL 1 SECOND)"
                 " AS event_timestamp")


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def catalog() -> Catalog:
    """fs_* and Gold share the lakehouse catalog (Postgres iceberg_catalog, data in s3://warehouse)."""
    return lakehouse.load()


def table_name(name: str) -> str:
    return f"{NAMESPACE}.{name}"


def gold_name(name: str, settings: dict | None = None) -> str:
    namespace = os.environ.get("GOLD_NAMESPACE") or (settings or load_settings())["gold_namespace"]
    return f"{namespace}.{name}"


def parse_date(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def days(start: dt.date, end: dt.date) -> list[dt.date]:
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def staging_dir(start: dt.date, end: dt.date) -> Path:
    name = f"fs_{start:%Y%m%d}" + ("" if end == start else f"_{end:%Y%m%d}")
    return STAGING_ROOT / name


def run_id() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%f")


def run_sql(con, name: str, **params) -> None:
    """Run features/sql/<name> statement by statement; each statement gets only the $params it mentions."""
    text = "\n".join(line.split("--", 1)[0] for line in (SQL_DIR / name).read_text(encoding="utf-8").splitlines())
    for statement in text.split(";"):
        if statement.strip():
            used = {k: v for k, v in params.items() if f"${k}" in statement}
            con.execute(statement, used or None)


def write_json(path: Path, obj) -> None:
    """Replace one JSON file atomically: a failed write keeps the previous file (pointers stay valid)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
