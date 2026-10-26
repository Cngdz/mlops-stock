"""Step 3 write_partitions: overwrite partition report_date = T of the six fs_* tables (and fs_state).

  python -m features.write --date 2026-01-30 --mode overwrite-partition [--staging tmp_fs_20260130]

Each table is written with an overwrite filtered on report_date = T (a range for backfills): a missing partition is
created, an existing one replaced, every other day keeps its files. The day is marked WRITING first, so a COMPLETE
from an earlier run never survives a rewrite, then WRITTEN. The staging dir is deleted once all tables are written.
Replaced files stay referenced by older snapshots until the weekly features.maintenance.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
from pathlib import Path

import pyarrow.parquet as pq
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import And, BooleanExpression, EqualTo, GreaterThanOrEqual, LessThanOrEqual

from features import status
from features.common import FS_TABLES, NAMESPACE, STATE_TABLE, catalog, days, parse_date, table_name
from features.compute import out_dir
from pipeline import catalog as lakehouse
from pipeline.common import write_partition


def day_filter(start: dt.date, end: dt.date) -> BooleanExpression:
    if start == end:
        return EqualTo("report_date", start.isoformat())
    return And(GreaterThanOrEqual("report_date", start.isoformat()), LessThanOrEqual("report_date", end.isoformat()))


def write(cat: Catalog, staging: Path, statuses: status.StatusStore) -> dict:
    run = json.loads((staging / "run.json").read_text(encoding="utf-8"))
    start, end = parse_date(run["start"]), parse_date(run["end"])
    covered = days(start, end)
    statuses.set(covered, status.WRITING, run_id=run["run_id"], row_counts=None, details=None, published_at=None)
    lakehouse.ensure_namespace(cat, NAMESPACE)
    for name in FS_TABLES + [STATE_TABLE]:
        data = pq.read_table(staging / f"{name}.parquet")
        write_partition(cat, table_name(name), data, "report_date", day_filter(start, end))
        print(f"{table_name(name)} {start}..{end}: {data.num_rows:,} rows", flush=True)
    statuses.set(covered, status.WRITTEN)
    shutil.rmtree(staging)
    return run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=parse_date, required=True)
    parser.add_argument("--end", type=parse_date)
    parser.add_argument("--mode", choices=["overwrite-partition"], default="overwrite-partition",
                        help="the only mode: replace the partitions of the run's days, never append")
    parser.add_argument("--staging", help="staging dir name, as given to features.compute --out")
    args = parser.parse_args()
    staging = out_dir(args.staging, args.date, args.end or args.date)
    if not (staging / "run.json").exists():
        raise SystemExit(f"no computed features in {staging}: run features.compute first")
    run = write(catalog(), staging, status.store())
    print(f"run {run['run_id']} written; staging {staging.name} deleted")


if __name__ == "__main__":
    main()
