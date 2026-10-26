"""Step 2 compute_features: features of day T (or a range) from Gold T-30..T and the carried state of T-1.

  python -m features.compute --date 2026-01-30 --out tmp_fs_20260130
  python -m features.compute --date 2025-02-01 --end 2025-02-28 --bootstrap     # first run: no state of T-1 yet

Writes <staging>/fs_*.parquet, fs_state.parquet and run.json (run id, range, row counts) for features.write.
The run never depends on the length of the history: Gold is read for 30 days, the unbounded values (margin
history count, over-limit streak, last campaign date) continue from features.fs_state of T-1. Without that
partition the run stops unless --bootstrap, which rebuilds the state once from the small Gold event tables.
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import EqualTo

from features import gold
from features.common import (EOD_TIMESTAMP, GROUPS, KEYS, STAGING_ROOT, STATE_TABLE, catalog, load_settings,
                             parse_date, run_id, run_sql, staging_dir, table_name, write_json)

STATE_COLUMNS = ["master_account", "history_count", "over_limit_streak", "last_campaign_date"]


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone='Asia/Ho_Chi_Minh'")  # business days are local calendar days
    con.execute("SET threads=4")
    return con


def build(con: duckdb.DuckDBPyConnection, start: dt.date, end: dt.date, lookback_days: int = 30,
          bootstrap: bool = False) -> None:
    """Gold tables loaded in con (at least start-lookback..end) + seed_state (unless bootstrap)
    -> scoring_features and state_out. No I/O: the same call serves the daily run, backfills and tests."""
    gold.normalize(con)
    if bootstrap:
        run_sql(con, "bootstrap_state.sql", seed_day=start - dt.timedelta(days=1))
    run_sql(con, "features.sql", start=start, end=end, lookback_start=start - dt.timedelta(days=lookback_days))


def outputs(con: duckdb.DuckDBPyConnection) -> dict[str, pa.Table]:
    """fs_* tables (keys + event timestamp + contract columns) and the state, as Arrow (UTC microsecond timestamps)."""
    out = {}
    keys = ", ".join(KEYS)
    for name, columns in GROUPS.items():
        selected = ", ".join(f'"{c}"' for c in columns)
        out[name] = utc_timestamps(con.execute(
            f"SELECT {keys}, {EOD_TIMESTAMP}, {selected} FROM scoring_features ORDER BY {keys}").to_arrow_table())
    out[STATE_TABLE] = con.execute("SELECT * FROM state_out ORDER BY master_account, report_date").to_arrow_table()
    return out


def utc_timestamps(table: pa.Table) -> pa.Table:
    """Store every timezone-aware timestamp as microsecond UTC (Iceberg timestamptz)."""
    for index, field in enumerate(table.schema):
        if pa.types.is_timestamp(field.type) and field.type.tz is not None:
            table = table.set_column(index, field.name, table.column(index).cast(pa.timestamp("us", tz="UTC")))
    return table


def load_seed(con: duckdb.DuckDBPyConnection, cat: Catalog, seed_day: dt.date) -> int:
    """State partition of seed_day -> DuckDB seed_state. Returns its row count (0 = no such partition)."""
    try:
        arrow = cat.load_table(table_name(STATE_TABLE)).scan(
            row_filter=EqualTo("report_date", seed_day.isoformat()), selected_fields=tuple(STATE_COLUMNS)).to_arrow()
    except NoSuchTableError:
        arrow = pa.table({c: [] for c in STATE_COLUMNS})
    if arrow.num_rows:
        seed_from(con, arrow)
    return arrow.num_rows


def seed_from(con: duckdb.DuckDBPyConnection, state: pa.Table) -> None:
    con.register("seed_arrow", state)
    con.execute(f"CREATE OR REPLACE TABLE seed_state AS SELECT {', '.join(STATE_COLUMNS)} FROM seed_arrow")
    con.unregister("seed_arrow")


def compute(cat: Catalog, start: dt.date, end: dt.date, out: Path, bootstrap: bool = False) -> dict:
    """Gold window -> staging parquet. Returns the run summary also written to out/run.json."""
    settings = load_settings()
    lookback = start - dt.timedelta(days=settings["lookback_days"])
    con = connect()
    seed_day = start - dt.timedelta(days=1)
    if not bootstrap and load_seed(con, cat, seed_day) == 0:
        raise SystemExit(f"no {table_name(STATE_TABLE)} partition for {seed_day}: run that day first, "
                         f"or start a new history with --bootstrap")
    for table, (column, _) in gold.READ.items():
        # The state tables need all history only when bootstrapping, and they are the small ones.
        full_history = bootstrap and table in ("margin_balance_daily", "margin_cash_flow", "customer_campaign")
        rows = gold.load(con, cat, table, None if full_history else lookback, end)
        print(f"gold {table}: {rows:,} rows" + ("" if column is None else
              f" ({'all history' if full_history else lookback} .. {end})"), flush=True)
    build(con, start, end, settings["lookback_days"], bootstrap)
    tables = outputs(con)
    con.close()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, arrow in tables.items():
        pq.write_table(arrow, out / f"{name}.parquet")
    summary = {"run_id": run_id(), "start": start, "end": end, "bootstrap": bootstrap,
               "rows": {name: t.num_rows for name, t in tables.items()}}
    write_json(out / "run.json", summary)
    return summary


def out_dir(text: str | None, start: dt.date, end: dt.date) -> Path:
    """--out NAME -> data/features/staging/NAME (a bare name, as the DAG passes it); default fs_<start>[_<end>]."""
    if not text:
        return staging_dir(start, end)
    path = Path(text)
    return path if path.is_absolute() or len(path.parts) > 1 else STAGING_ROOT / text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=parse_date, required=True)
    parser.add_argument("--end", type=parse_date, help="last day of a range (inclusive); default: --date")
    parser.add_argument("--out", help="staging dir name under data/features/staging (default fs_<date>)")
    parser.add_argument("--bootstrap", action="store_true", help="rebuild the carried state from all Gold history")
    args = parser.parse_args()
    end = args.end or args.date
    out = out_dir(args.out, args.date, end)
    summary = compute(catalog(), args.date, end, out, args.bootstrap)
    print(f"run {summary['run_id']} {args.date}..{end}: " + ", ".join(f"{k} {v:,}" for k, v in summary["rows"].items()))
    print(f"staging: {out}")


if __name__ == "__main__":
    main()
