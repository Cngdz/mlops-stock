"""Backfill a date range: compute -> write -> quality -> publish, one calendar month per round.

  python -m features.backfill --start 2025-02-01 --end 2026-01-30     # first fill of an empty store
  python -m features.backfill --start 2025-12-01 --end 2025-12-31     # redo one month

The same steps as DAG feature_store_daily, over a month at a time: every round reads the small Gold tables in full and
the large ones for that month plus 30 days of lookback, so memory stays at about two months of portfolio rows
whatever the range, and the rounds do not depend on each other. Stops at the first month whose quality gate fails; earlier months stay COMPLETE.
"""
from __future__ import annotations

import argparse
import datetime as dt

from features import quality, status
from features.common import catalog, parse_date, staging_dir
from features.compute import compute
from features.publish import publish
from features.write import write


def months(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """[start, end] cut at month ends. Pure."""
    out, first = [], start
    while first <= end:
        next_month = (first.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        last = min(end, next_month - dt.timedelta(days=1))
        out.append((first, last))
        first = last + dt.timedelta(days=1)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=parse_date, required=True)
    parser.add_argument("--end", type=parse_date, required=True)
    args = parser.parse_args()
    cat, statuses = catalog(), status.store()
    for first, last in months(args.start, args.end):
        print(f"==> {first}..{last}", flush=True)
        out = staging_dir(first, last)
        compute(cat, first, last, out)
        write(cat, out, statuses)
        result = quality.check(cat, first, last, statuses)
        if failed := {d: r["failed"] for d, r in result.items() if r["status"] != status.QUALITY_PASSED}:
            raise SystemExit(f"quality gate failed for {len(failed)} days, first {min(failed)}: {failed[min(failed)]}")
        publish(first, last, statuses)
        print(f"    COMPLETE {first}..{last}", flush=True)


if __name__ == "__main__":
    main()
