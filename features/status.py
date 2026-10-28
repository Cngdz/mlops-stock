"""control.fs_status: one row per report_date, the readiness marker of the feature store.

A day moves WRITING -> WRITTEN -> QUALITY_PASSED | QUALITY_FAILED -> COMPLETE. Only COMPLETE means "the six fs_*
partitions of this day passed the quality gate"; the predict DAGs wait for it (SqlSensor) and pipeline jobs refuse
any other state. Re-running a day starts again at WRITING, so a stale COMPLETE never outlives the data it vouched
for. Plain Postgres (schema control in the database iceberg_catalog), not Iceberg: a sensor polls it every few
minutes and needs a cheap point lookup.

  python -m features.status --date 2026-01-30        # show the row
  python -m features.status --start 2026-01-01 --end 2026-01-30
  python -m features.status --date 2026-01-30 --wait --timeout-minutes 30   # the sensor: exit 0 once COMPLETE, 1 on timeout
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time

import sqlalchemy as sa

WRITING, WRITTEN, QUALITY_PASSED, QUALITY_FAILED, COMPLETE = (
    "WRITING", "WRITTEN", "QUALITY_PASSED", "QUALITY_FAILED", "COMPLETE")
DEFAULT_URI = "postgresql+psycopg2://postgres:mlflowpassword@127.0.0.1:5432/iceberg_catalog"


class StatusStore:
    def __init__(self, engine: sa.Engine, schema: str | None = "control"):
        self.engine = engine
        if schema and engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        elif engine.dialect.name != "postgresql":
            schema = None  # SQLite (tests) has no schemas
        self.table = sa.Table(
            "fs_status", sa.MetaData(),
            sa.Column("report_date", sa.Date, primary_key=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("run_id", sa.String(64)),
            sa.Column("row_counts", sa.Text),   # JSON: fs table -> rows of the day
            sa.Column("details", sa.Text),      # JSON: failed quality checks
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.Column("published_at", sa.DateTime),
            schema=schema,
        )
        self.table.metadata.create_all(engine)

    def set(self, days: list[dt.date], status: str, **fields) -> None:
        """Upsert the status of each day. Fields not given keep their value (run_id survives the later steps)."""
        values = {"status": status, "updated_at": now(),
                  **{k: json.dumps(v, default=str) if k in ("row_counts", "details") else v for k, v in fields.items()}}
        with self.engine.begin() as conn:
            existing = {r.report_date for r in conn.execute(
                sa.select(self.table.c.report_date).where(self.table.c.report_date.in_(days)))}
            if existing:
                conn.execute(self.table.update().where(self.table.c.report_date.in_(existing)).values(**values))
            if fresh := [d for d in days if d not in existing]:
                conn.execute(self.table.insert(), [{"report_date": d, **values} for d in fresh])

    def get_range(self, start: dt.date, end: dt.date) -> dict[dt.date, dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(sa.select(self.table).where(self.table.c.report_date.between(start, end)))
            return {r.report_date: decode(r._asdict()) for r in rows}

    def get(self, day: dt.date) -> dict | None:
        return self.get_range(day, day).get(day)

    def latest_complete(self) -> dt.date | None:
        with self.engine.connect() as conn:
            return conn.execute(sa.select(sa.func.max(self.table.c.report_date))
                                .where(self.table.c.status == COMPLETE)).scalar()

    def delete_before(self, cutoff: dt.date) -> int:
        with self.engine.begin() as conn:
            return conn.execute(self.table.delete().where(self.table.c.report_date < cutoff)).rowcount


def decode(row: dict) -> dict:
    for key in ("row_counts", "details"):
        row[key] = json.loads(row[key]) if row[key] else None
    return row


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def store() -> StatusStore:
    """Same Postgres as the Iceberg catalog unless CONTROL_DB_URI says otherwise."""
    return StatusStore(sa.create_engine(os.environ.get("CONTROL_DB_URI")
                                        or os.environ.get("ICEBERG_CATALOG_URI", DEFAULT_URI)))


def require_complete(day: dt.date, statuses: StatusStore | None = None) -> dict:
    """The fs_status row of a COMPLETE day; stops the job for any other state."""
    row = (statuses or store()).get(day)
    if row is None or row["status"] != COMPLETE:
        raise SystemExit(f"feature store day {day} is not COMPLETE (status: {row['status'] if row else 'missing'}): "
                         f"run DAG feature_store_daily for it first")
    return row


def wait_complete(day: dt.date, timeout_minutes: float, poll_seconds: float = 30.0,
                  statuses: StatusStore | None = None, sleep=time.sleep, clock=time.monotonic) -> bool:
    """Poll control.fs_status until `day` is COMPLETE. False when the timeout passes first (the sensor failed)."""
    statuses = statuses or store()
    deadline = clock() + timeout_minutes * 60
    while True:
        row = statuses.get(day)
        if row is not None and row["status"] == COMPLETE:
            return True
        if clock() >= deadline:
            return False
        sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=dt.date.fromisoformat)
    parser.add_argument("--start", type=dt.date.fromisoformat)
    parser.add_argument("--end", type=dt.date.fromisoformat)
    parser.add_argument("--wait", action="store_true", help="block until --date is COMPLETE (the predict sensor)")
    parser.add_argument("--timeout-minutes", type=float, default=30.0)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.wait:
        if not args.date:
            parser.error("--wait needs --date")
        ready = wait_complete(args.date, args.timeout_minutes, args.poll_seconds)
        print(f"feature store day {args.date}: " + ("COMPLETE" if ready else f"not COMPLETE after {args.timeout_minutes:g} min"))
        raise SystemExit(0 if ready else 1)
    start, end = (args.date, args.date) if args.date else (args.start, args.end)
    if not (start and end):
        parser.error("--date, or --start and --end")
    rows = store().get_range(start, end)
    for day in sorted(rows):
        r = rows[day]
        print(f"{day}  {r['status']:15s} run={r['run_id']}  rows={r['row_counts']}  updated={r['updated_at']:%Y-%m-%d %H:%M}"
              + (f"  failed={list(r['details'])}" if r["details"] else ""))
    print(f"{len(rows)} of {(end - start).days + 1} days have a row")


if __name__ == "__main__":
    main()
