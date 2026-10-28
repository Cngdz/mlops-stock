"""Shared helpers for the batch jobs: settings, feature snapshots from the approved Day 4 run, Iceberg writes."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import BooleanExpression

from training.data import resolve_run_dir

SETTINGS_PATH = Path(__file__).with_name("monitoring.yaml")
KEYS = ["master_account", "report_date"]
FS_TABLES = ["fs_trading_behavior", "fs_margin_balance", "fs_portfolio", "fs_campaign", "fs_demographic",
             "fs_asset_balance"]


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def feature_run() -> tuple[Path, str]:
    """(run dir, run id) of the approved feature run that data/features/current.json points to."""
    run_dir = resolve_run_dir()
    return run_dir, run_dir.name


def assemble(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Join the fs_* frames of one or more days on (master_account, report_date). Pure."""
    out = frames[0].drop(columns=["event_timestamp"], errors="ignore")
    for frame in frames[1:]:
        out = out.merge(frame.drop(columns=["event_timestamp"], errors="ignore"), on=KEYS, how="inner",
                        validate="one_to_one")
    return out


def read_snapshot(run_dir: Path, date: dt.date) -> pd.DataFrame:
    """All feature groups of one day. A day the feature store has written (a row in control.fs_status) is served from
    the Iceberg fs_* partitions and only once COMPLETE; a day it never wrote falls back to the approved run's parquet,
    filtered to that day (1 of 364)."""
    from features import status, store  # local import: the batch jobs that never touch the store do not need it
    from features.common import catalog

    statuses = status.store()
    if statuses.get(date) is not None:
        return store.read_day(catalog(), date, statuses)[0]
    frames = [pq.read_table(run_dir / f"{name}.parquet", filters=[("report_date", "=", date)]).to_pandas()
              for name in FS_TABLES]
    snapshot = assemble(frames)
    if snapshot.empty:
        raise ValueError(f"no feature rows for {date} in {run_dir.name}")
    return snapshot


def parse_date(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def date_range(start: dt.date, end: dt.date | None) -> list[dt.date]:
    end = end or start
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def write_partition(catalog: Catalog, identifier: str, data: pa.Table, partition_column: str,
                    replace: BooleanExpression) -> None:
    """Create the table on first use (identity-partitioned on partition_column), then replace the rows matching
    `replace`: re-running the same day overwrites that day instead of appending duplicates."""
    try:
        table = catalog.load_table(identifier)
    except NoSuchTableError:
        table = catalog.create_table(identifier, schema=data.schema)
        with table.update_spec() as spec:
            spec.add_identity(partition_column)
        table = catalog.load_table(identifier)
    table.overwrite(data, overwrite_filter=replace)


def as_json(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)
