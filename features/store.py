"""Read side of the feature store: the six fs_* partitions of one day, served only when the day is COMPLETE
(control.fs_status). Batch predict and drift read through pipeline.common.read_snapshot, which calls this."""
from __future__ import annotations

import datetime as dt

import pandas as pd
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import EqualTo

from features import status
from features.common import FS_TABLES, KEYS, table_name


def assemble(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Join the fs_* frames of one day on (master_account, report_date). Pure."""
    out = frames[0].drop(columns=["event_timestamp"], errors="ignore")
    for frame in frames[1:]:
        out = out.merge(frame.drop(columns=["event_timestamp"], errors="ignore"), on=KEYS, how="inner",
                        validate="one_to_one")
    return out


def read_day(cat: Catalog, day: dt.date, statuses: status.StatusStore | None = None) -> tuple[pd.DataFrame, str]:
    """All feature groups of one COMPLETE day, and the feature run id that wrote it."""
    marker = status.require_complete(day, statuses)
    frames = [cat.load_table(table_name(name)).scan(row_filter=EqualTo("report_date", day.isoformat())).to_pandas()
              for name in FS_TABLES]
    snapshot = assemble(frames)
    if snapshot.empty:
        raise SystemExit(f"feature store day {day} is COMPLETE but has no rows")
    return snapshot, marker["run_id"]