"""Step 1 check_source: Gold has day T, with the schema the feature SQL expects.

  python -m features.check_source --date 2026-01-30

Fails (exit 1, Airflow retries) when a Gold table is missing, a column is missing or retyped, or a daily snapshot
table (margin balance, portfolio, prices) does not reach T yet. Nothing is computed from an incomplete source, so
no empty or partial partition can be written. Dates come from the Iceberg file statistics: no data scan.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from pyiceberg.catalog import Catalog

from features import gold
from features.common import catalog, parse_date


def check(cat: Catalog, day: dt.date) -> dict:
    report = gold.schema_problems(gold.observed_schema(cat))
    report["max_dates"] = {}
    for table, column in gold.SNAPSHOT_TABLES.items():
        if table not in report["missing_tables"]:
            report["max_dates"][table] = gold.max_date(cat, table, column)
    report["behind"] = {t: d for t, d in report["max_dates"].items() if d is None or d < day}
    report["status"] = "FAIL" if any(report[k] for k in ("missing_tables", "missing_columns",
                                                          "invalid_column_types", "behind")) else "PASS"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=parse_date, required=True)
    args = parser.parse_args()
    report = check(catalog(), args.date)
    print(json.dumps(report, indent=2, default=str))
    print(f"source check for {args.date}: {report['status']}")
    sys.exit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
