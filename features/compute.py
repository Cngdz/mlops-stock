"""Step 2 compute_features: features of day T (or a range) from Gold.

  python -m features.compute --date 2026-01-30 --out tmp_fs_20260130
  python -m features.compute --date 2026-01-01 --end 2026-01-31      # a range, e.g. one backfill month

Writes <staging>/fs_*.parquet and run.json (run id, range, row counts) for features.write.
Every run is independent of the previous one. Three kinds of values need an account's WHOLE history: the margin
history count (segment), the over-limit streak and the last campaign date. They come from the three small Gold
tables (balances, cash flows, campaigns), read from the first day to T, and are rebuilt by bootstrap_state.sql.
The large tables (trades, portfolio holdings) are read for 30 days only: every window is 7 or 30 days.
So the cost of a run grows with the small tables, not with the portfolio rows, and rerunning any day, in any
order, gives the same rows.
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

from features import gold
from features.common import (EOD_TIMESTAMP, GROUPS, KEYS, STAGING_ROOT, catalog, load_settings, parse_date, run_id,
                             run_sql, staging_dir, write_json)

# Tables whose whole history is needed (accumulated values); the others are read for the lookback window only.
FULL_HISTORY_TABLES = ("margin_balance_daily", "margin_cash_flow", "customer_campaign")


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET TimeZone='Asia/Ho_Chi_Minh'")  # business days are local calendar days
    con.execute("SET threads=4")
    return con


def build(con: duckdb.DuckDBPyConnection, start: dt.date, end: dt.date, lookback_days: int = 30) -> None:
    """Gold tables loaded in con (the small ones in full, the large ones for start-lookback..end) -> scoring_features.
    No I/O: the same call serves the daily run, backfills and tests."""
    gold.normalize(con)
    run_sql(con, "bootstrap_state.sql", seed_day=start - dt.timedelta(days=1))
    run_sql(con, "features.sql", start=start, end=end, lookback_start=start - dt.timedelta(days=lookback_days))


def outputs(con: duckdb.DuckDBPyConnection) -> dict[str, pa.Table]:
    """fs_* tables (keys + event timestamp + contract columns) as Arrow (UTC microsecond timestamps)."""
    out = {}
    keys = ", ".join(KEYS)
    for name, columns in GROUPS.items():
        selected = ", ".join(f'"{c}"' for c in columns)
        out[name] = utc_timestamps(con.execute(
            f"SELECT {keys}, {EOD_TIMESTAMP}, {selected} FROM scoring_features ORDER BY {keys}").to_arrow_table())
    return out


def utc_timestamps(table: pa.Table) -> pa.Table:
    """Store every timezone-aware timestamp as microsecond UTC (Iceberg timestamptz)."""
    for index, field in enumerate(table.schema):
        if pa.types.is_timestamp(field.type) and field.type.tz is not None:
            table = table.set_column(index, field.name, table.column(index).cast(pa.timestamp("us", tz="UTC")))
    return table


def compute(cat: Catalog, start: dt.date, end: dt.date, out: Path) -> dict:
    """Gold -> staging parquet. Returns the run summary also written to out/run.json."""
    settings = load_settings()
    lookback = start - dt.timedelta(days=settings["lookback_days"])
    con = connect()
    for table, (column, _) in gold.READ.items():
        full_history = table in FULL_HISTORY_TABLES
        rows = gold.load(con, cat, table, None if full_history else lookback, end)
        print(f"gold {table}: {rows:,} rows" + ("" if column is None else
              f" ({'all history' if full_history else lookback} .. {end})"), flush=True)
    build(con, start, end, settings["lookback_days"])
    tables = outputs(con)
    con.close()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name, arrow in tables.items():
        pq.write_table(arrow, out / f"{name}.parquet")
    summary = {"run_id": run_id(), "start": start, "end": end,
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
    args = parser.parse_args()
    end = args.end or args.date
    out = out_dir(args.out, args.date, end)
    summary = compute(catalog(), args.date, end, out)
    print(f"run {summary['run_id']} {args.date}..{end}: " + ", ".join(f"{k} {v:,}" for k, v in summary["rows"].items()))
    print(f"staging: {out}")


if __name__ == "__main__":
    main()