"""Step 4 quality_gate: contract and quality checks on partition report_date = T only.

  python -m features.quality --date 2026-01-30

Reads the six fs_* partitions of T (a range for backfills), never the rest of the table:
  - contract: column names and Iceberg types of each table = docs/feature_contract.md (features/common.py GROUPS)
  - keys (master_account, report_date): not null, unique, the same account set in all six tables
  - rows of T / rows of the previous day within quality.row_count_ratio
  - null rate of contract columns <= quality.max_null_rate, and value domains (segment, windows, ratios, formulas)
A failing day is marked QUALITY_FAILED with the failed checks and the job exits 1: it is never published.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import duckdb
from pyiceberg.catalog import Catalog

from features import status
from features.common import FS_TABLES, GROUPS, KEY_TYPES, KEYS, catalog, days, load_settings, parse_date, table_name
from features.write import day_filter

DOMAINS = {
    "margin_segment": "margin_segment NOT IN ('nu','lu','au')",
    "account_age": "account_age_days < 30",
    "trading_windows": ("trade_count_7d > trade_count_30d OR total_trading_amount_7d > total_trading_amount_30d "
                        "OR active_trading_days_30d NOT BETWEEN 0 AND 30 OR trade_count_7d < 0"),
    "over_limit": "over_limit_streak < 0 OR over_limit_days_30d NOT BETWEEN 0 AND 30",
    "campaign": ("has_campaign_history NOT IN (0,1) OR days_since_last_campaign NOT BETWEEN 0 AND 365 "
                 "OR campaign_count_30d < 0 OR (has_campaign_history = 0 AND days_since_last_campaign <> 365)"),
    "ratios": ("margin_utilization_ratio < 0 OR cash_to_asset_ratio < 0 OR portfolio_concentration NOT BETWEEN 0 AND 1 "
               "OR unrealized_loss_ratio NOT BETWEEN 0 AND 1 OR risky_asset_ratio NOT BETWEEN 0 AND 1"),
    "balance_formulas": ("NAV <> asset_value + cash_balance - margin_debt "
                         "OR abs(margin_utilization_ratio - CASE WHEN margin_limit=0 THEN 0.0 ELSE margin_debt::DOUBLE/margin_limit END) > 1e-10 "
                         "OR abs(cash_to_asset_ratio - CASE WHEN asset_value=0 THEN 0.0 ELSE cash_balance::DOUBLE/asset_value END) > 1e-10"),
}


def contract_problems(observed: dict[str, dict[str, str]]) -> dict[str, dict]:
    """observed: fs table -> column -> Iceberg type. Missing, extra or retyped columns per table. Pure."""
    problems = {}
    for name, columns in GROUPS.items():
        expected = {**KEY_TYPES, **columns}
        actual = observed.get(name, {})
        found = {"missing": sorted(set(expected) - set(actual)), "extra": sorted(set(actual) - set(expected)),
                 "types": {c: {"expected": t, "observed": actual[c]} for c, t in expected.items()
                           if c in actual and actual[c] != t}}
        if any(found.values()):
            problems[name] = found
    return problems


def per_day(con: duckdb.DuckDBPyConnection, sql: str) -> dict[dt.date, float]:
    return {d: v for d, v in con.execute(sql).fetchall()}


def evaluate(con: duckdb.DuckDBPyConnection, covered: list[dt.date], previous_rows: int | None,
             settings: dict, contract: dict) -> dict[dt.date, dict]:
    """fs_* rows of the covered days registered in con (one table per fs name) -> verdict per day. No I/O."""
    low, high = settings["row_count_ratio"]
    found: dict[dt.date, dict[str, object]] = {d: {} for d in covered}
    rows = {name: per_day(con, f"SELECT report_date, count(*) FROM {name} GROUP BY ALL") for name in FS_TABLES}

    def record(check: str, values: dict[dt.date, float], passed) -> None:
        for d in covered:
            observed = values.get(d, 0)
            if not passed(observed):
                found[d][check] = observed

    for name, columns in GROUPS.items():
        record(f"{name}.rows", rows[name], lambda n: n > 0)
        record(f"{name}.null_keys", per_day(con, f"SELECT report_date, count(*) FROM {name} WHERE master_account IS NULL "
                                                 f"OR report_date IS NULL GROUP BY ALL"), lambda n: n == 0)
        record(f"{name}.duplicate_keys", per_day(con, f"SELECT report_date, count(*) FROM (SELECT {', '.join(KEYS)} FROM "
                                                      f"{name} GROUP BY ALL HAVING count(*) > 1) GROUP BY ALL"), lambda n: n == 0)
        nulls = " + ".join(f'count(*) FILTER (WHERE "{c}" IS NULL)' for c in columns)
        record(f"{name}.null_rate", per_day(con, f"SELECT report_date, ({nulls})::DOUBLE / (count(*) * {len(columns)}) "
                                                 f"FROM {name} GROUP BY ALL"),
               lambda r: r <= settings["max_null_rate"])
        if name != FS_TABLES[0]:
            record(f"{name}.same_accounts_as_{FS_TABLES[0]}", per_day(con, f"""
                SELECT report_date, count(*) FROM (
                    (SELECT {', '.join(KEYS)} FROM {name} EXCEPT SELECT {', '.join(KEYS)} FROM {FS_TABLES[0]}) UNION ALL
                    (SELECT {', '.join(KEYS)} FROM {FS_TABLES[0]} EXCEPT SELECT {', '.join(KEYS)} FROM {name}))
                GROUP BY ALL"""), lambda n: n == 0)
    joined = " JOIN ".join(FS_TABLES[:1] + [f"{n} USING({', '.join(KEYS)})" for n in FS_TABLES[1:]])
    for check, condition in DOMAINS.items():
        record(f"domain.{check}", per_day(con, f"SELECT report_date, count(*) FROM {joined} WHERE {condition} GROUP BY ALL"),
               lambda n: n == 0)

    counts = rows[FS_TABLES[0]]
    for d in covered:
        before = counts.get(d - dt.timedelta(days=1), previous_rows if d == covered[0] else None)
        if before:  # the first day ever has nothing to compare with
            ratio = counts.get(d, 0) / before
            if not low <= ratio <= high:
                found[d]["row_count_ratio"] = round(ratio, 4)
        if contract:
            found[d]["contract"] = contract
    return {d: {"status": status.QUALITY_FAILED if found[d] else status.QUALITY_PASSED,
                "rows": {name: rows[name].get(d, 0) for name in FS_TABLES}, "failed": found[d]} for d in covered}


def partition_rows(cat: Catalog, name: str, day: dt.date) -> int | None:
    """Rows of one partition from the Iceberg metadata (no data scan); None if the partition does not exist."""
    for p in cat.load_table(table_name(name)).inspect.partitions().to_pylist():
        if p["partition"]["report_date"] == day:
            return p["record_count"]
    return None


def check(cat: Catalog, start: dt.date, end: dt.date, statuses: status.StatusStore) -> dict[dt.date, dict]:
    con = duckdb.connect()
    observed = {}
    for name in FS_TABLES:
        table = cat.load_table(table_name(name))
        observed[name] = {f.name: str(f.field_type) for f in table.schema().fields}
        con.register(name, table.scan(row_filter=day_filter(start, end)).to_arrow())
    result = evaluate(con, days(start, end), partition_rows(cat, FS_TABLES[0], start - dt.timedelta(days=1)),
                      load_settings()["quality"], contract_problems(observed))
    con.close()
    for d, r in result.items():  # row counts and failures differ per day
        statuses.set([d], r["status"], row_counts=r["rows"], details=r["failed"] or None)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", type=parse_date, required=True)
    parser.add_argument("--end", type=parse_date)
    args = parser.parse_args()
    result = check(catalog(), args.date, args.end or args.date, status.store())
    failed = {d: r["failed"] for d, r in result.items() if r["status"] == status.QUALITY_FAILED}
    for d, r in result.items():
        if d in failed or len(result) <= 3:
            print(f"{d}: {r['status']}  rows={r['rows'][FS_TABLES[0]]:,}" + (f"  failed={r['failed']}" if r["failed"] else ""))
    print(f"quality gate: {len(result) - len(failed)}/{len(result)} days passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
