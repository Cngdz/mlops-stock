"""Step 5 publish_marker: mark day T COMPLETE in control.fs_status.

  python -m features.publish --date 2026-01-30

Refuses unless the quality gate passed for T in this run (status QUALITY_PASSED): a day is only ever published
after write -> quality. Re-running a day updates its own row only. The predict DAGs wait for this row.
"""
from __future__ import annotations

import argparse
import datetime as dt

from features import status
from features.common import days, parse_date


def publish(start: dt.date, end: dt.date, statuses: status.StatusStore) -> list[dt.date]:
    covered = days(start, end)
    rows = statuses.get_range(start, end)
    if blocked := {d: rows[d]["status"] if d in rows else "missing" for d in covered
                   if d not in rows or rows[d]["status"] != status.QUALITY_PASSED}:
        shown = dict(list(blocked.items())[:5])
        raise SystemExit(f"not publishable, quality gate not passed: {shown}"
                         + (f" (+{len(blocked) - 5} more days)" if len(blocked) > 5 else ""))
    statuses.set(covered, status.COMPLETE, published_at=status.now())
    return covered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=parse_date, required=True)
    parser.add_argument("--end", type=parse_date)
    args = parser.parse_args()
    published = publish(args.date, args.end or args.date, status.store())
    print(f"control.fs_status: {published[0]}..{published[-1]} COMPLETE ({len(published)} days)")


if __name__ == "__main__":
    main()
