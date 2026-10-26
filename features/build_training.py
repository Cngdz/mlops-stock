"""Training data: fs_* partitions of [start, end] + labels computed from Gold -> a versioned run for training.train.

  python -m features.build_training                                   # split range from features/settings.yaml
  python -m features.build_training --start 2025-02-01 --end 2025-12-31 --run-id loan_propensity_train_20261025

Features are read back from the published fs_* partitions (every day must be COMPLETE), never recomputed, so a
training row and the row scored on the same day carry identical values. Labels look forward and are computed here
only, from Gold: loan_label_next = valid margin disbursement in D+1..D+30, overdue_label_next_30d = a new OVERDUE in
D+1..D+30 for overdue_eligible rows, campaign_response_label_14d = valid disbursement in D+1..D+14 after a DELIVERED
send. Rows whose label window passes the last Gold day are dropped.

The quality gate is all-or-nothing. PASS writes data/features/day4_runs/<run_id>/ (training_dataset,
campaign_training_dataset, loan_overdue_labels, class_weights.json, quality_report.json) and moves
data/features/current.json to it. FAIL writes data/features/rejected_training_report.json only and exits 2.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
import time

import duckdb
import pyarrow.parquet as pq
from pyiceberg.catalog import Catalog

from features import gold, status, store
from features.common import (EOD_TIMESTAMP, FEATURE_COLUMNS, FEATURE_CONTRACT, FS_TABLES, KEYS, OVERDUE_ELIGIBLE_SQL,
                             POINTER, ROOT, RUNS_ROOT, catalog, days, load_settings, parse_date, run_id, table_name,
                             write_json)
from features.compute import connect, utc_timestamps
from features.write import day_filter

INTERNAL = ["response_14d", "no_campaign_14d"]   # gate helpers, never exported
SEGMENTS = ["nu", "lu", "au"]
SPLITS = ["train", "validation", "test"]


def load_fs(con: duckdb.DuckDBPyConnection, cat: Catalog, start: dt.date, end: dt.date) -> None:
    """The six fs_* partitions of [start, end] joined into DuckDB table fs (no event_timestamp)."""
    for name in FS_TABLES:
        con.register(f"src_{name}", cat.load_table(table_name(name)).scan(row_filter=day_filter(start, end)).to_arrow())
    joined = " JOIN ".join([f"src_{FS_TABLES[0]}"] + [f"src_{n} USING({', '.join(KEYS)})" for n in FS_TABLES[1:]])
    con.execute(f"CREATE OR REPLACE TABLE fs AS SELECT * EXCLUDE(event_timestamp) FROM {joined}")
    for name in FS_TABLES:
        con.unregister(f"src_{name}")


def build(con: duckdb.DuckDBPyConnection, label_end: dt.date, splits: dict) -> None:
    """fs + Gold cash flows, balances, campaigns loaded in con -> candidate, campaign_candidate. No I/O.

    The first event / OVERDUE day strictly after D comes from an ASOF join, so the labels are a lookup per row,
    not a scan of 30 future days."""
    gold.normalize(con)
    case = " ".join(f"WHEN f.report_date BETWEEN DATE '{a}' AND DATE '{b}' THEN '{name}'"
                    for name, (a, b) in splits.items())
    con.execute("CREATE OR REPLACE TABLE overdue_days AS SELECT master_account, business_date FROM balances "
                "WHERE margin_status = 'OVERDUE'")
    con.execute(f"""CREATE OR REPLACE TABLE snapshots AS
        WITH next_event AS (
            SELECT f.master_account, f.report_date, e.event_day AS next_event_day
            FROM fs f ASOF LEFT JOIN valid_events e
              ON f.master_account = e.master_account AND f.report_date < e.event_day),
        next_overdue AS (
            SELECT f.master_account, f.report_date, o.business_date AS next_overdue_day
            FROM fs f ASOF LEFT JOIN overdue_days o
              ON f.master_account = o.master_account AND f.report_date < o.business_date)
        SELECT f.*,
            CAST(coalesce(n.next_event_day <= f.report_date + INTERVAL 30 DAY, false) AS TINYINT) AS loan_label_next,
            {OVERDUE_ELIGIBLE_SQL} AS overdue_eligible,
            CASE WHEN {OVERDUE_ELIGIBLE_SQL} = 1 THEN
                CAST(coalesce(o.next_overdue_day <= f.report_date + INTERVAL 30 DAY, false) AS TINYINT) END
                AS overdue_label_next_30d,
            CASE {case} END AS split,
            CAST(coalesce(n.next_event_day <= f.report_date + INTERVAL 14 DAY, false) AS TINYINT) AS response_14d,
            -- no campaign in D-14..D: the last one (or none, 365) is more than 14 days back
            CAST(f.days_since_last_campaign > 14 AS TINYINT) AS no_campaign_14d
        FROM fs f JOIN next_event n USING(master_account, report_date)
                  JOIN next_overdue o USING(master_account, report_date)
        WHERE f.report_date <= DATE '{label_end}' - INTERVAL 30 DAY""")
    con.execute("CREATE OR REPLACE TABLE candidate AS SELECT * FROM snapshots WHERE split IS NOT NULL")
    store.campaign_rows(con, "candidate")
    con.execute("""CREATE OR REPLACE TABLE campaign_candidate AS
        SELECT r.*, s.response_14d AS campaign_response_label_14d, s.split
        FROM campaign_rows r JOIN candidate s USING(master_account, report_date)""")


def scalar(con, sql, params=None):
    return con.execute(sql, params).fetchone()[0]


def records(con, sql):
    cur = con.execute(sql)
    return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]


def assess(con: duckdb.DuckDBPyConnection, label_end: dt.date) -> dict:
    """Quality gate of the training rows (thresholds = decisions 11.3, 11.4, 14.5 of the Day 4 gate)."""
    checks = []

    def check(name, observed, expected=0):
        checks.append({"check": name, "observed": observed, "expected": expected, "passed": bool(observed == expected)})

    required = KEYS + FEATURE_COLUMNS + ["loan_label_next", "split"]
    check("candidate.null_required_rows", scalar(con, "SELECT count(*) FROM candidate WHERE "
                                                 + " OR ".join(f'"{k}" IS NULL' for k in required)))
    check("candidate.duplicate_keys", scalar(con, "SELECT count(*) FROM (SELECT master_account,report_date FROM candidate GROUP BY ALL HAVING count(*)<>1)"))
    check("candidate.nonempty", scalar(con, "SELECT count(*) FROM candidate") > 0, True)
    check("candidate.invalid_domains", scalar(con, "SELECT count(*) FROM candidate WHERE margin_segment NOT IN ('nu','lu','au') OR split NOT IN ('train','validation','test') OR loan_label_next NOT IN (0,1) OR account_age_days<30 OR trade_count_7d>trade_count_30d OR total_trading_amount_7d>total_trading_amount_30d OR active_trading_days_30d NOT BETWEEN 0 AND 30"))
    check("candidate.incomplete_label_window", scalar(con, "SELECT count(*) FROM candidate WHERE report_date+INTERVAL 30 DAY>?", [label_end]))
    check("candidate.balance_formulas", scalar(con, """SELECT count(*) FROM candidate WHERE
        NAV<>asset_value+cash_balance-margin_debt OR
        abs(margin_utilization_ratio-CASE WHEN margin_limit=0 THEN 0.0 ELSE margin_debt::DOUBLE/margin_limit END)>1e-10 OR
        abs(cash_to_asset_ratio-CASE WHEN asset_value=0 THEN 0.0 ELSE cash_balance::DOUBLE/asset_value END)>1e-10"""))
    # Independent audit: recompute the labels of 150 rows with direct EXISTS queries instead of the ASOF lookup.
    con.execute("CREATE OR REPLACE TABLE audit_sample AS SELECT * FROM candidate ORDER BY hash(master_account,report_date) LIMIT 150")
    check("label_independent_audit", scalar(con, """SELECT count(*) FROM audit_sample s WHERE
        loan_label_next<>CAST(EXISTS(SELECT 1 FROM valid_events e WHERE e.master_account=s.master_account AND e.event_day>s.report_date AND e.event_day<=s.report_date+INTERVAL 30 DAY) AS TINYINT)
        OR s.overdue_label_next_30d IS DISTINCT FROM CAST(CASE WHEN s.overdue_eligible=1 THEN
            EXISTS(SELECT 1 FROM overdue_days o WHERE o.master_account=s.master_account AND o.business_date>s.report_date
                   AND o.business_date<=s.report_date+INTERVAL 30 DAY) END AS TINYINT)"""))
    stats = records(con, "SELECT split,margin_segment,count(*) AS rows,sum(loan_label_next) AS positives,avg(loan_label_next) AS positive_rate FROM candidate GROUP BY ALL ORDER BY 1,2")
    for split in SPLITS:
        for segment in SEGMENTS:
            row = next((r for r in stats if r["split"] == split and r["margin_segment"] == segment), None)
            check(f"{split}.{segment}.both_classes", bool(row and 0 < row["positives"] < row["rows"]), True)
    rates = records(con, "SELECT margin_segment,count(*) AS rows,avg(loan_label_next) AS positive_rate FROM candidate GROUP BY ALL")
    overall = scalar(con, "SELECT avg(loan_label_next) FROM candidate")
    check("overall_positive_rate_10_to_35pct", overall is not None and .10 <= overall <= .35, True)
    last_shares = {}
    for seg, low, high in [("nu", .05, .25), ("lu", .10, .40), ("au", .15, .50)]:
        rate = next((r["positive_rate"] for r in rates if r["margin_segment"] == seg), None)
        check(f"{seg}.positive_rate_{low}_to_{high}", rate is not None and low <= rate <= high, True)
        share = scalar(con, f"SELECT avg(CAST(margin_segment='{seg}' AS INTEGER)) FROM candidate WHERE report_date=(SELECT max(report_date) FROM candidate)")
        last_shares[seg] = share
        check(f"{seg}.last_snapshot_share_at_least_10pct", share is not None and share >= .1, True)

    check("overdue.invalid_domains", scalar(con, """SELECT count(*) FROM candidate WHERE overdue_eligible NOT IN (0,1)
        OR (overdue_eligible=1 AND (overdue_label_next_30d IS NULL OR overdue_label_next_30d NOT IN (0,1)))
        OR (overdue_eligible=0 AND overdue_label_next_30d IS NOT NULL)
        OR over_limit_streak<0 OR over_limit_days_30d NOT BETWEEN 0 AND 30"""))
    check("overdue.nu_never_eligible", scalar(con, "SELECT count(*) FROM candidate WHERE overdue_eligible=1 AND margin_segment='nu'"))
    overdue_stats = records(con, "SELECT split,margin_segment,count(*) AS rows,sum(overdue_label_next_30d) AS positives,avg(overdue_label_next_30d) AS positive_rate FROM candidate WHERE overdue_eligible=1 GROUP BY ALL ORDER BY 1,2")
    for split in SPLITS:
        check(f"overdue.{split}.eligible_rows_at_least_50000", sum(r["rows"] for r in overdue_stats if r["split"] == split) >= 50_000, True)
    overdue_rate = scalar(con, "SELECT avg(overdue_label_next_30d) FROM candidate WHERE overdue_eligible=1")
    check("overdue.positive_rate_5_to_30pct", overdue_rate is not None and .05 <= overdue_rate <= .30, True)
    for seg in ["lu", "au"]:
        rows = [r for r in overdue_stats if r["margin_segment"] == seg]
        total, pos = sum(r["rows"] for r in rows), sum(r["positives"] for r in rows)
        check(f"overdue.{seg}.positive_rate_1_to_40pct", bool(total) and .01 <= pos / total <= .40, True)
        for split in SPLITS:
            row = next((r for r in rows if r["split"] == split), None)
            check(f"overdue.{split}.{seg}.both_classes", bool(row and 0 < row["positives"] < row["rows"]), True)

    campaign = {"rows": scalar(con, "SELECT count(*) FROM campaign_candidate")}
    check("campaign.duplicate_keys", scalar(con, "SELECT count(*) FROM (SELECT campaign_event_id FROM campaign_candidate GROUP BY ALL HAVING count(*)>1)"))
    check("campaign.invalid_domains", scalar(con, """SELECT count(*) FROM campaign_candidate WHERE campaign_response_label_14d NOT IN (0,1)
        OR campaign_response_label_14d IS NULL OR split NOT IN ('train','validation','test')
        OR channel NOT IN ('APP','SMS','EMAIL') OR offer_type NOT IN ('RATE_DISCOUNT','FEE_WAIVER','LIMIT_BOOST')
        OR interest_rate_offer NOT BETWEEN 0.065 AND 0.105 OR account_age_days<30 OR campaign_count_30d<0"""))
    check("campaign.incomplete_label_window", scalar(con, "SELECT count(*) FROM campaign_candidate WHERE report_date+INTERVAL 14 DAY>?", [label_end]))
    check("campaign_label_independent_audit", scalar(con, """SELECT count(*) FROM (SELECT * FROM campaign_candidate ORDER BY hash(campaign_event_id) LIMIT 150) s
        WHERE s.campaign_response_label_14d<>CAST(EXISTS(SELECT 1 FROM valid_events e WHERE e.master_account=s.master_account
              AND e.event_day>s.report_date AND e.event_day<=s.report_date+INTERVAL 14 DAY) AS TINYINT)"""))
    by_split = records(con, "SELECT split,count(*) AS rows,avg(campaign_response_label_14d) AS positive_rate FROM campaign_candidate GROUP BY ALL ORDER BY 1")
    for split in SPLITS:
        check(f"campaign.{split}.rows_at_least_5000", any(r["split"] == split and r["rows"] >= 5000 for r in by_split), True)
    campaign_rate = scalar(con, "SELECT avg(campaign_response_label_14d) FROM campaign_candidate")
    check("campaign.positive_rate_8_to_40pct", campaign_rate is not None and .08 <= campaign_rate <= .40, True)
    # Lift is standardised by segment: campaigns skew towards nu/lu, whose base rate is lower.
    treated = records(con, "SELECT margin_segment,count(*) AS n,avg(campaign_response_label_14d) AS rate FROM campaign_candidate GROUP BY ALL")
    baseline = {r["margin_segment"]: r["rate"] for r in records(con, "SELECT margin_segment,avg(response_14d::DOUBLE) AS rate FROM candidate WHERE no_campaign_14d=1 GROUP BY ALL")}
    expected = sum(r["n"] * baseline.get(r["margin_segment"], 0.0) for r in treated)
    lift = sum(r["n"] * r["rate"] for r in treated) / expected if expected else None
    check("campaign.segment_standardised_lift_1_2_to_2_5", lift is not None and 1.2 <= lift <= 2.5, True)
    offers = records(con, "SELECT offer_type,count(*) AS rows,avg(campaign_response_label_14d) AS rate FROM campaign_candidate GROUP BY ALL ORDER BY 1")
    spread = max(r["rate"] for r in offers) - min(r["rate"] for r in offers) if offers else 0.0
    check("campaign.offer_response_spread_at_least_1_5pp", spread >= .015, True)
    campaign.update({"by_split": by_split, "positive_rate": campaign_rate, "lift": lift, "by_offer": offers, "offer_spread": spread})
    return {"status": "PASS" if all(c["passed"] for c in checks) else "FAIL", "checks": checks,
            "rows": scalar(con, "SELECT count(*) FROM candidate"), "positive_rate": overall,
            "by_segment": rates, "by_split_segment": stats, "last_snapshot_shares": last_shares,
            "overdue_by_split_segment": overdue_stats, "overdue_positive_rate": overdue_rate, "campaign": campaign,
            "rows_outside_splits": scalar(con, "SELECT count(*) FROM snapshots WHERE split IS NULL")}


def balanced(counts: dict) -> dict | None:
    return {str(k): sum(counts.values()) / (2 * v) for k, v in counts.items()} if len(counts) == 2 else None


def class_weights(con: duckdb.DuckDBPyConnection) -> dict:
    """Balanced class weights N / (2 * N_class), fit on the train split only, per use case and segment."""
    result = {"method": "balanced: N / (2 * N_class)", "fit_split": "train", "approved_for_training": True,
              "segments": {}, "overdue_risk": {"fit_split": "train", "segments": {}},
              "campaign_response": {"fit_split": "train"}}
    for seg in SEGMENTS:
        counts = dict(con.execute("SELECT loan_label_next,count(*) FROM candidate WHERE split='train' AND margin_segment=? GROUP BY 1", [seg]).fetchall())
        result["segments"][seg] = {"counts": counts, "weights": balanced(counts)}
    for seg in ["lu", "au"]:
        counts = dict(con.execute("SELECT overdue_label_next_30d,count(*) FROM candidate WHERE split='train' AND overdue_eligible=1 AND margin_segment=? GROUP BY 1", [seg]).fetchall())
        result["overdue_risk"]["segments"][seg] = {"counts": counts, "weights": balanced(counts)}
    counts = dict(con.execute("SELECT campaign_response_label_14d,count(*) FROM campaign_candidate WHERE split='train' GROUP BY 1").fetchall())
    result["campaign_response"].update({"counts": counts, "weights": balanced(counts)})
    return result


OUTPUTS = {
    "training_dataset": f"SELECT * EXCLUDE({', '.join(INTERNAL)}) FROM candidate ORDER BY master_account, report_date",
    "campaign_training_dataset": "SELECT * FROM campaign_candidate ORDER BY master_account, report_date, campaign_event_id",
    "loan_overdue_labels": (f"SELECT master_account, report_date, {EOD_TIMESTAMP}, loan_label_next, overdue_eligible, "
                            "overdue_label_next_30d, split FROM candidate ORDER BY master_account, report_date"),
}


def run(cat: Catalog, start: dt.date, end: dt.date, statuses: status.StatusStore, run_name: str | None = None) -> int:
    started = time.monotonic()
    marks = statuses.get_range(start, end)
    if missing := [d for d in days(start, end) if marks.get(d, {}).get("status") != status.COMPLETE]:
        raise SystemExit(f"{len(missing)} days of {start}..{end} are not COMPLETE in control.fs_status "
                         f"(first {missing[0]}): backfill them first")
    label_end = gold.max_date(cat, "margin_balance_daily", "business_date")
    con = connect()
    load_fs(con, cat, start, end)
    for table, window_start in [("margin_cash_flow", start), ("margin_balance_daily", start),
                                ("customer_campaign", None)]:  # campaign history columns count every earlier send
        rows = gold.load(con, cat, table, window_start, label_end)
        print(f"gold {table}: {rows:,} rows", flush=True)
    build(con, label_end, load_settings()["training"]["splits"])
    report = assess(con, label_end)
    name = run_name or run_id()
    report.update({"run_id": name, "feature_contract": FEATURE_CONTRACT, "fs_range": [start, end],
                   "label_end": label_end, "fs_runs": sorted({m["run_id"] for m in marks.values() if m["run_id"]})})
    if report["status"] != "PASS":
        write_json(ROOT / "data/features/rejected_training_report.json", report)
        con.close()
        failed = [c["check"] for c in report["checks"] if not c["passed"]]
        print(f"training data quality gate FAIL ({len(failed)}): {failed}; nothing exported", flush=True)
        return 2
    out = RUNS_ROOT / name
    out.mkdir(parents=True, exist_ok=True)  # a retried task reuses its --run-id: files are replaced
    report["outputs"] = {}
    for table, sql in OUTPUTS.items():
        path = out / f"{table}.parquet"
        pq.write_table(utc_timestamps(con.execute(sql).to_arrow_table()), path)
        report["outputs"][table] = {"rows": pq.read_metadata(path).num_rows,
                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        print(f"{table}: {report['outputs'][table]['rows']:,} rows", flush=True)
    write_json(out / "class_weights.json", class_weights(con))
    con.close()
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    write_json(out / "quality_report.json", report)
    write_json(POINTER, {"run_id": name, "path": str(out), "feature_contract": FEATURE_CONTRACT,
                         "fs_range": [start, end], "label_end": label_end})
    print(f"quality gate PASS; run {name} -> {out}; data/features/current.json updated", flush=True)
    return 0


def main() -> None:
    splits = load_settings()["training"]["splits"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=parse_date, default=parse_date(splits["train"][0]))
    parser.add_argument("--end", type=parse_date, default=parse_date(splits["test"][1]))
    parser.add_argument("--run-id", help="name of the run dir (the train DAG passes one so its train task finds it)")
    args = parser.parse_args()
    sys.exit(run(catalog(), args.start, args.end, status.store(), args.run_id))


if __name__ == "__main__":
    main()
