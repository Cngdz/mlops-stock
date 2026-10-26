"""Shared helpers for the batch jobs: per-use-case settings, date ranges, Iceberg partition writes."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pyarrow as pa
import yaml
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import BooleanExpression

SETTINGS_PATH = Path(__file__).with_name("monitoring.yaml")


def load_settings(usecase: str, path: Path = SETTINGS_PATH) -> dict:
    """The monitoring entry of one use case (drift + evaluate thresholds)."""
    usecases = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["usecases"]
    if usecase not in usecases:
        raise SystemExit(f"{usecase}: no entry in {Path(path).name} (known: {sorted(usecases)})")
    return usecases[usecase]


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
