"""Daily feature store: read ALL of Gold, compute the features, write only the requested day(s) as partitions.

  python -m scripts.fs_daily --date 2026-01-30                       # daily: replaces partition 2026-01-30 only
  python -m scripts.fs_daily --start 2025-02-01 --date 2026-01-30    # backfill: one partition per day in the range

Why the whole of Gold is read: segment (history_count), has_campaign_history / days_since_last_campaign and
over_limit_streak accumulate over the account's full history, so a 30-day look-back would give wrong values.
Only the WRITE is incremental: rerunning a day replaces that partition and nothing else.

Layout (data/features/fs, pipeline.common.FS_ROOT):
  <fs_table>/report_date=<day>/data.parquet   one file per table and day, replaced atomically
  _status/report_date=<day>.json              written last; pipeline.common.read_snapshot ignores days without it
Retention: partitions older than --retention-days before --date are deleted, with their markers.
Exit 0: written; exit 2: source or partition quality gate failed, nothing written.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from pipeline.common import FS_ROOT, fs_marker, fs_partition
from scripts.day4_feature_engineering import (EOD_TIMESTAMP, GROUPS, KEYS, build, catalog, load_sources, normalize,
                                              utc_timestamps, validate_sources, write_json)

FEATURES = [f for fields in GROUPS.values() for f in fields]
RETENTION_DAYS = 365


def check_partitions(con, start: date, end: date) -> dict[str, int]:
    """Hard checks (0 violating rows) on the days about to be written. Returns the violations that are not 0."""
    window = f"report_date BETWEEN DATE '{start}' AND DATE '{end}'"
    any_null = " OR ".join(f'"{c}" IS NULL' for c in KEYS + FEATURES)
    checks = {
        "null_key_or_feature": f"SELECT count(*) FROM scoring_features WHERE {window} AND ({any_null})",
        "duplicate_keys": f"SELECT count(*) FROM (SELECT master_account, report_date FROM scoring_features "
                          f"WHERE {window} GROUP BY ALL HAVING count(*) > 1)",
        "invalid_domains": f"SELECT count(*) FROM scoring_features WHERE {window} AND (margin_segment NOT IN "
                           "('nu','lu','au') OR account_age_days < 30 OR trade_count_7d > trade_count_30d "
                           "OR active_trading_days_30d NOT BETWEEN 0 AND 30)",
    }
    bad = {name: con.execute(sql).fetchone()[0] for name, sql in checks.items()}
    expected = (end - start).days + 1
    present = con.execute(f"SELECT count(DISTINCT report_date) FROM scoring_features WHERE {window}").fetchone()[0]
    bad["missing_days"] = expected - present
    return {name: n for name, n in bad.items() if n}


def write_partitions(con, start: date, end: date, root: Path | None = None) -> dict[str, dict[str, int]]:
    """One parquet file per (table, day) in [start, end], replaced atomically, then the day's completion marker."""
    written: dict[str, dict[str, int]] = {}
    days = [d[0] for d in con.execute(
        f"SELECT DISTINCT report_date FROM scoring_features WHERE report_date BETWEEN DATE '{start}' "
        f"AND DATE '{end}' ORDER BY 1").fetchall()]
    for day in days:
        rows = {}
        for table, fields in GROUPS.items():
            cols = ", ".join(f'"{c}"' for c in KEYS + fields)
            arrow = utc_timestamps(con.execute(
                f"SELECT {cols}, {EOD_TIMESTAMP} FROM scoring_features WHERE report_date = ? "
                "ORDER BY master_account", [day]).to_arrow_table())
            path = fs_partition(table, day, root)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".parquet.tmp")
            pq.write_table(arrow, temporary)
            os.replace(temporary, path)
            rows[table] = arrow.num_rows
        marker = fs_marker(day, root)
        marker.parent.mkdir(parents=True, exist_ok=True)
        write_json(marker, {"report_date": day, "status": "COMPLETE", "rows": rows,
                            "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        written[day.isoformat()] = rows
    return written


def drop_old_partitions(end: date, retention_days: int = RETENTION_DAYS, root: Path | None = None) -> list[str]:
    """Delete partitions (and markers) dated before end - retention_days. Returns the removed days."""
    root = root or FS_ROOT
    cutoff = end - timedelta(days=retention_days)
    removed = set()
    for table in GROUPS:
        for partition in (root / table).glob("report_date=*"):
            day = date.fromisoformat(partition.name.split("=")[1])
            if day < cutoff:
                shutil.rmtree(partition)
                removed.add(day.isoformat())
    for marker in (root / "_status").glob("report_date=*.json"):
        if date.fromisoformat(marker.stem.split("=")[1]) < cutoff:
            marker.unlink()
            removed.add(marker.stem.split("=")[1])
    return sorted(removed)


def run(args) -> int:
    start = args.start or args.date
    if start > args.date:
        raise SystemExit(f"--start {start} is after --date {args.date}")
    con = duckdb.connect()
    con.execute("SET TimeZone='Asia/Ho_Chi_Minh'")
    con.execute("SET threads=4")
    load_sources(con, catalog(), args.source_namespace)
    latest = con.execute("SELECT max(business_date) FROM margin_balance_daily").fetchone()[0]
    if args.date > latest:
        print(f"--date {args.date} is after the newest Gold day {latest}: nothing written.", flush=True)
        return 2
    # Validate the sources as they are today (up to `latest`); features are still cut at --date, so rerunning an
    # old day uses only data up to that day and gives the same values as when it was first computed.
    source_report = validate_sources(con, latest)
    if source_report["status"] != "PASS":
        print(json.dumps(source_report, indent=2, default=str), flush=True)
        print(f"Source validation FAIL (Gold up to {latest}): nothing written.", flush=True)
        return 2
    normalize(con)
    build(con, args.date)
    bad = check_partitions(con, start, args.date)
    if bad:
        print(f"Partition quality gate FAIL for {start}..{args.date}: {bad}. Nothing written.", flush=True)
        return 2
    written = write_partitions(con, start, args.date)
    removed = drop_old_partitions(args.date, args.retention_days)
    first, last = min(written), max(written)
    print(f"Wrote {len(written)} partition(s) {first}..{last}; {sum(written[last].values()):,} rows on {last}; "
          f"removed {len(removed)} older than {args.retention_days} days", flush=True)
    con.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="last day to write (T)")
    parser.add_argument("--start", type=date.fromisoformat, help="first day to write; default = --date (daily run)")
    parser.add_argument("--retention-days", type=int, default=RETENTION_DAYS)
    parser.add_argument("--source-namespace", help="Gold namespace; default: the last approved source")
    sys.exit(run(parser.parse_args()))
