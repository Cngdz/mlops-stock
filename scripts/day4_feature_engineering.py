"""Iceberg -> scoring features + training candidates -> quality gate -> versioned feature tables.

fs_* tables come from scoring_features (every eligible day up to raw_end, no labels);
training_dataset comes from candidate (features JOIN labels, complete label window, split).

Exit 0: approved; exit 2: rejected, only a validation report is written.
No feature tables or training files are written when validation fails.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]
KEYS = ["master_account", "report_date"]
# Feast timestamp convention: a daily snapshot for D is valid at 23:59:59 Asia/Ho_Chi_Minh on D.
EOD_TIMESTAMP = "timezone('Asia/Ho_Chi_Minh', CAST(report_date AS TIMESTAMP) + INTERVAL 1 DAY - INTERVAL 1 SECOND) AS event_timestamp"
FEATURE_CONTRACT = "day4-v5"
GROUPS = {
    "fs_demographic": ["account_age_days", "margin_segment"],
    "fs_trading_behavior": ["trade_count_7d", "trade_count_30d", "total_trading_amount_7d", "total_trading_amount_30d", "active_trading_days_30d"],
    "fs_margin_balance": ["margin_debt", "margin_limit", "margin_utilization_ratio", "debt_change_7d", "over_limit_streak", "over_limit_days_30d"],
    "fs_asset_balance": ["cash_balance", "asset_value", "collateral_value", "cash_to_asset_ratio", "NAV"],
    "fs_portfolio": ["portfolio_value", "holding_symbol_count", "portfolio_concentration", "unrealized_loss_ratio", "risky_asset_ratio"],
    "fs_campaign": ["campaign_count_30d", "days_since_last_campaign", "has_campaign_history"],
}
SOURCE_KEYS = {"customer_account": ["master_account"], "stock_transaction": ["transaction_id"],
               "margin_balance_daily": ["master_account", "business_date"], "margin_cash_flow": ["cash_flow_id"]}
EXTENDED_SOURCE_KEYS = {"stock_price_daily": ["business_date", "symbol"], "security_master": ["symbol"],
                        "portfolio_holding_daily": ["master_account", "business_date", "symbol"],
                        "customer_campaign": ["campaign_event_id"]}
ALL_SOURCE_KEYS = {**SOURCE_KEYS, **EXTENDED_SOURCE_KEYS}
CORE_SOURCE_KEYS = SOURCE_KEYS
SOURCE_SCHEMA = {
    "customer_account": {
        "master_account": "text", "account_open_date": "date", "account_status": "text",
        "account_close_date": "date", "dormant_start_date": "date", "risk_profile": "text",
    },
    "stock_transaction": {
        "transaction_id": "text", "master_account": "text", "transaction_time": "timestamp",
        "quantity": "number", "price": "number", "trade_value": "number", "side": "text",
    },
    "margin_balance_daily": {
        "master_account": "text", "business_date": "date", "cash_balance": "number",
        "asset_value": "number", "margin_debt": "number", "margin_limit": "number",
    },
    "margin_cash_flow": {
        "cash_flow_id": "text", "master_account": "text", "event_date": "date",
        "status": "text", "fk_product": "text", "fk_cash_flow_type": "text",
        "fk_deliver_type": "text", "amount": "number",
    },
    "stock_price_daily": {"business_date": "date", "symbol": "text", "price": "number"},
    "security_master": {"symbol": "text", "sector": "text", "liquidity_group": "text", "margin_eligible": "boolean", "risk_level": "text"},
    "portfolio_holding_daily": {"master_account": "text", "business_date": "date", "symbol": "text", "quantity": "number", "market_value": "number", "portfolio_weight": "number"},
    "customer_campaign": {"campaign_event_id": "text", "master_account": "text", "campaign_id": "text", "sent_at": "timestamp", "channel": "text", "offer_type": "text", "interest_rate_offer": "number", "status": "text"},
}


def schema_type_matches(actual, expected):
    if expected == "number":
        return actual.split("(")[0] in {
            "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
            "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
            "FLOAT", "DOUBLE", "DECIMAL",
        }
    if expected == "timestamp":
        return actual == "VARCHAR" or actual.startswith("TIMESTAMP")
    if expected == "boolean":
        return actual == "BOOLEAN"
    return actual == {"text": "VARCHAR", "date": "DATE"}[expected]


def catalog():
    return load_catalog("local", **{
        "type": "sql", "uri": f"sqlite:///{(ROOT / 'data/catalog_full/pyiceberg.db').as_posix()}",
        "warehouse": str(ROOT / "data/warehouse_full"),
    })


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]


def records(con, sql):
    cur = con.execute(sql)
    return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]


def validate_sources(con, raw_end):
    """Reject unsupported schemas and invalid source data before feature builds."""
    available = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    missing_tables = sorted(set(CORE_SOURCE_KEYS) - available)
    optional_missing_tables = sorted(set(SOURCE_SCHEMA) - set(CORE_SOURCE_KEYS) - available)
    missing_columns, invalid_types = {}, {}
    for table, required in SOURCE_SCHEMA.items():
        if table not in available:
            continue
        columns = dict((r[0], r[1]) for r in con.execute(f"DESCRIBE {table}").fetchall())
        missing_columns[table] = sorted(set(required) - columns.keys())
        invalid_types[table] = {
            name: {"observed": columns[name], "expected": kind}
            for name, kind in required.items()
            if name in columns and not schema_type_matches(columns[name], kind)
        }
    result = {
        "status": "FAIL", "missing_tables": missing_tables,
        "optional_missing_tables": optional_missing_tables,
        "missing_columns": {k: v for k, v in missing_columns.items() if v},
        "invalid_column_types": {k: v for k, v in invalid_types.items() if v},
        "missing_cash_flow_columns": missing_columns.get("margin_cash_flow", []),
        "invalid_transaction_timestamps": None,
        "accounts_with_incomplete_balance_history": None,
    }
    if missing_tables or result["missing_columns"] or result["invalid_column_types"]:
        return result
    invalid_times = scalar(con, "SELECT count(*) FROM stock_transaction WHERE TRY_CAST(transaction_time AS TIMESTAMPTZ) IS NULL")
    incomplete = con.execute("""SELECT count(*) FROM (
        SELECT a.master_account FROM customer_account a LEFT JOIN margin_balance_daily b USING(master_account)
        GROUP BY a.master_account,a.account_open_date HAVING a.account_open_date IS NULL
        OR min(b.business_date) IS DISTINCT FROM a.account_open_date
        OR max(b.business_date) IS DISTINCT FROM ? OR count(DISTINCT b.business_date)<>date_diff('day',a.account_open_date,?)+1)""",
        [raw_end, raw_end]).fetchone()[0]
    result.update({
        "status": "FAIL" if invalid_times or incomplete else "PASS",
        "invalid_transaction_timestamps": invalid_times,
        "accounts_with_incomplete_balance_history": incomplete,
    })
    return result


def normalize(con):
    """Use canonical source fields only; never infer missing label semantics."""
    columns = {r[0] for r in con.execute("DESCRIBE margin_cash_flow").fetchall()}
    missing = {"fk_cash_flow_type", "fk_deliver_type"} - columns
    if missing:
        raise ValueError(f"Missing cash-flow columns: {sorted(missing)}")
    con.execute("CREATE TABLE events AS SELECT *, CAST(event_date AS DATE) AS event_day FROM margin_cash_flow")
    con.execute("""CREATE TABLE valid_events AS SELECT * FROM events WHERE status='POSTED' AND
        ((fk_product='MARGIN_MBS' AND fk_cash_flow_type='INTERM_DELIVER' AND fk_deliver_type='BUY_SHARE') OR
         (fk_product='MBLINK' AND fk_cash_flow_type='TLO_DELIVER_CASH' AND fk_deliver_type='BUY'))""")
    con.execute("""CREATE TABLE trades AS SELECT *,
        CAST(timezone('Asia/Ho_Chi_Minh', CAST(transaction_time AS TIMESTAMPTZ)) AS DATE) AS trade_date
        FROM stock_transaction""")
    # Extension sources are optional for legacy four-source fixtures. A full
    # generated batch contains them and receives the additional feature views.
    con.execute("""CREATE TABLE IF NOT EXISTS security_master(
        symbol VARCHAR, sector VARCHAR, exchange VARCHAR, liquidity_group VARCHAR,
        margin_eligible BOOLEAN, risk_level VARCHAR, effective_from DATE, effective_to DATE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS portfolio_holding_daily(
        master_account VARCHAR, business_date DATE, symbol VARCHAR, quantity BIGINT,
        average_cost DOUBLE, market_value BIGINT, unrealized_pnl BIGINT, portfolio_weight DOUBLE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS customer_campaign(
        campaign_event_id VARCHAR, campaign_id VARCHAR, master_account VARCHAR, sent_at TIMESTAMPTZ,
        channel VARCHAR, offer_type VARCHAR, interest_rate_offer DOUBLE, status VARCHAR)""")
    con.execute("""CREATE TABLE portfolio_daily AS
        SELECT h.master_account, CAST(h.business_date AS DATE) AS business_date,
               coalesce(sum(h.market_value), 0)::BIGINT AS portfolio_value,
               count(DISTINCT h.symbol)::BIGINT AS holding_symbol_count,
               coalesce(max(h.portfolio_weight), 0.0) AS portfolio_concentration,
               CASE WHEN sum(h.market_value)=0 THEN 0.0
                    ELSE sum(CASE WHEN h.unrealized_pnl<0 THEN h.market_value ELSE 0 END)::DOUBLE/sum(h.market_value) END AS unrealized_loss_ratio,
               CASE WHEN sum(h.market_value)=0 THEN 0.0
                    ELSE sum(CASE WHEN s.risk_level='HIGH' THEN h.market_value ELSE 0 END)::DOUBLE/sum(h.market_value) END AS risky_asset_ratio
        FROM portfolio_holding_daily h LEFT JOIN security_master s USING(symbol)
        GROUP BY h.master_account, h.business_date""")
    con.execute("""CREATE TABLE campaign_daily AS
        SELECT master_account, CAST(sent_at AS DATE) AS campaign_day, count(*)::BIGINT AS campaigns,
               max(CAST(sent_at AS DATE)) AS last_campaign_date
        FROM customer_campaign WHERE status <> 'FAILED' GROUP BY ALL""")
    balance_columns = {r[0] for r in con.execute("DESCRIBE margin_balance_daily").fetchall()}
    status_expr = "margin_status" if "margin_status" in balance_columns else "CASE WHEN margin_limit>0 AND margin_debt>margin_limit THEN 'OVERDUE' ELSE 'ACTIVE' END"
    con.execute(f"CREATE TABLE balance_label_source AS SELECT *, {status_expr} AS normalized_margin_status FROM margin_balance_daily")


def build(con, raw_end):
    for statement in (ROOT / "scripts/day4_features.sql").read_text(encoding="utf-8").split(';'):
        if statement.strip():
            con.execute(statement, {"raw_end": raw_end} if '$raw_end' in statement else None)


def keys_or_cols(con, table):
    return {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}


def assess(con, raw_end):
    checks = []

    def check(name, observed, expected=0):
        checks.append({"check": name, "observed": observed, "expected": expected, "passed": bool(observed == expected)})

    check("invalid_transaction_timestamp", scalar(con, "SELECT count(*) FROM trades WHERE TRY_CAST(transaction_time AS TIMESTAMPTZ) IS NULL"))
    available = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    for table, keys in ALL_SOURCE_KEYS.items():
        if table not in available:
            continue
        check(f"{table}.duplicate_keys", scalar(con, f"SELECT count(*) FROM (SELECT {','.join(keys)} FROM {table} GROUP BY ALL HAVING count(*)>1)"))
        check(f"{table}.null_keys", scalar(con, f"SELECT count(*) FROM {table} WHERE " + " OR ".join(f"{k} IS NULL" for k in keys)))
        if table != "customer_account" and "master_account" in keys_or_cols(con, table):
            check(f"{table}.orphan_accounts", scalar(con, f"SELECT count(*) FROM {table} s ANTI JOIN customer_account a USING(master_account)"))
    check("source_account_enums", scalar(con, "SELECT count(*) FROM customer_account WHERE risk_profile NOT IN ('LOW','MEDIUM','HIGH') OR risk_profile IS NULL OR account_status NOT IN ('ACTIVE','DORMANT','CLOSED') OR account_status IS NULL"))
    check("source_account_lifecycle_dates", scalar(con, "SELECT count(*) FROM customer_account WHERE account_open_date IS NULL OR (account_status='CLOSED' AND account_close_date IS NULL) OR (account_status='DORMANT' AND dormant_start_date IS NULL) OR account_close_date < account_open_date OR dormant_start_date < account_open_date"))
    check("invalid_trade_values", scalar(con, "SELECT count(*) FROM trades WHERE quantity IS NULL OR price IS NULL OR trade_value IS NULL OR quantity<=0 OR price<=0 OR trade_value<0 OR abs(trade_value-quantity*price)>1 OR side NOT IN ('BUY','SELL') OR side IS NULL OR trade_date IS NULL"))
    check("invalid_cash_flow", scalar(con, """SELECT count(*) FROM events WHERE amount IS NULL OR amount<0 OR event_day IS NULL
        OR status NOT IN ('POSTED','CANCELLED') OR status IS NULL
        OR fk_product IS NULL OR fk_product NOT IN ('MARGIN_MBS','MBLINK','OTHER')
        OR fk_cash_flow_type IS NULL OR fk_cash_flow_type NOT IN ('INTERM_DELIVER','TLO_DELIVER_CASH','REPAYMENT','FEE','OTHER')
        OR fk_deliver_type IS NULL OR fk_deliver_type NOT IN ('BUY_SHARE','BUY','OTHER')"""))
    for table, day in [("trades", "trade_date"), ("events", "event_day")]:
        check(f"{table}.outside_account_lifecycle", scalar(con, f"SELECT count(*) FROM {table} s JOIN customer_account a USING(master_account) WHERE {day}<account_open_date OR {day}>=account_close_date OR {day}>=dormant_start_date"))
        check(f"{table}.after_raw_end", con.execute(f"SELECT count(*) FROM {table} WHERE {day}>?", [raw_end]).fetchone()[0])
    check("invalid_balance_values", scalar(con, "SELECT count(*) FROM margin_balance_daily WHERE cash_balance IS NULL OR asset_value IS NULL OR margin_debt IS NULL OR margin_limit IS NULL OR least(cash_balance,asset_value,margin_debt,margin_limit)<0"))
    check("source_debt_reconciliation", scalar(con, """WITH deltas AS (
        SELECT master_account,event_day,sum(CASE
            WHEN status='POSTED' AND ((fk_product='MARGIN_MBS' AND fk_cash_flow_type='INTERM_DELIVER' AND fk_deliver_type='BUY_SHARE') OR
            (fk_product='MBLINK' AND fk_cash_flow_type='TLO_DELIVER_CASH' AND fk_deliver_type='BUY')) THEN amount
            WHEN status='POSTED' AND fk_cash_flow_type='REPAYMENT' THEN -amount ELSE 0 END) AS delta
        FROM events GROUP BY ALL), previous AS (
        SELECT *,coalesce(lag(margin_debt) OVER(PARTITION BY master_account ORDER BY business_date),0) AS prior_debt
        FROM margin_balance_daily)
        SELECT count(*) FROM previous b JOIN customer_account a USING(master_account)
        LEFT JOIN deltas d ON b.master_account=d.master_account AND b.business_date=d.event_day
        WHERE b.margin_debt<>CASE WHEN b.business_date>=a.account_close_date THEN 0
            ELSE greatest(0,b.prior_debt+coalesce(d.delta,0)) END"""))
    check("balance_history_incomplete", con.execute("""SELECT count(*) FROM (
        SELECT a.master_account FROM customer_account a LEFT JOIN margin_balance_daily b USING(master_account)
        GROUP BY a.master_account,a.account_open_date HAVING min(b.business_date)<>a.account_open_date
        OR max(b.business_date)<>? OR count(DISTINCT b.business_date)<>date_diff('day',a.account_open_date,?)+1)""", [raw_end, raw_end]).fetchone()[0])
    columns = KEYS + [f for values in GROUPS.values() for f in values] + ["loan_label_next", "split"]
    check("candidate.null_required_rows", scalar(con, "SELECT count(*) FROM candidate WHERE " + " OR ".join(f'"{k}" IS NULL' for k in columns)))
    check("candidate.duplicate_keys", scalar(con, "SELECT count(*) FROM (SELECT master_account,report_date FROM candidate GROUP BY ALL HAVING count(*)<>1)"))
    check("candidate.nonempty", scalar(con, "SELECT count(*) FROM candidate") > 0, True)
    check("candidate.invalid_domains", scalar(con, "SELECT count(*) FROM candidate WHERE margin_segment NOT IN ('nu','lu','au') OR split NOT IN ('train','validation','test') OR loan_label_next NOT IN (0,1) OR account_age_days<30 OR trade_count_7d>trade_count_30d OR total_trading_amount_7d>total_trading_amount_30d OR active_trading_days_30d NOT BETWEEN 0 AND 30"))
    check("candidate.incomplete_label_window", con.execute("SELECT count(*) FROM candidate WHERE report_date+INTERVAL 30 DAY>?", [raw_end]).fetchone()[0])
    check("candidate.embargo_rows", scalar(con, "SELECT count(*) FROM candidate WHERE report_date BETWEEN '2025-07-01' AND '2025-07-30' OR report_date BETWEEN '2025-10-01' AND '2025-10-30'"))
    check("candidate.balance_formulas", scalar(con, """SELECT count(*) FROM candidate WHERE
        NAV<>asset_value+cash_balance-margin_debt OR
        abs(margin_utilization_ratio-CASE WHEN margin_limit=0 THEN 0.0 ELSE margin_debt::DOUBLE/margin_limit END)>1e-10 OR
        abs(cash_to_asset_ratio-CASE WHEN asset_value=0 THEN 0.0 ELSE cash_balance::DOUBLE/asset_value END)>1e-10"""))
    # ---- Scoring features (fs_* source): separate from labels, includes the latest day ----
    feature_cols = [f for values in GROUPS.values() for f in values]
    check("scoring.nonempty", scalar(con, "SELECT count(*) FROM scoring_features") > 0, True)
    check("scoring.duplicate_keys", scalar(con, "SELECT count(*) FROM (SELECT master_account,report_date FROM scoring_features GROUP BY ALL HAVING count(*)<>1)"))
    check("scoring.null_required_rows", scalar(con, "SELECT count(*) FROM scoring_features WHERE " + " OR ".join(f'"{k}" IS NULL' for k in KEYS + feature_cols)))
    check("scoring.has_no_label_columns", len({"loan_label_next", "overdue_label_next_30d", "overdue_eligible", "split", "baseline_events_14d"} & keys_or_cols(con, "scoring_features")))
    check("scoring.reaches_raw_end", con.execute("SELECT max(report_date)=? FROM scoring_features", [raw_end]).fetchone()[0], True)
    check("scoring.covers_every_candidate_key", scalar(con, "SELECT count(*) FROM candidate c ANTI JOIN scoring_features f USING(master_account,report_date)"))
    check("scoring.training_parity", scalar(con, "SELECT count(*) FROM candidate c JOIN scoring_features f USING(master_account,report_date) WHERE "
          + " OR ".join(f'c."{k}" IS DISTINCT FROM f."{k}"' for k in feature_cols)))
    con.execute("CREATE TABLE audit_sample AS SELECT * FROM candidate ORDER BY hash(master_account,report_date) LIMIT 150")
    check("independent_rolling_and_label_audit", scalar(con, """SELECT count(*) FROM audit_sample s WHERE
        trade_count_7d<>(SELECT count(*) FROM trades t WHERE t.master_account=s.master_account AND t.trade_date BETWEEN s.report_date-INTERVAL 6 DAY AND s.report_date) OR
        total_trading_amount_30d<>(SELECT coalesce(sum(trade_value),0) FROM trades t WHERE t.master_account=s.master_account AND t.trade_date BETWEEN s.report_date-INTERVAL 29 DAY AND s.report_date) OR
        loan_label_next<>CAST(EXISTS(SELECT 1 FROM valid_events e WHERE e.master_account=s.master_account AND e.event_day>s.report_date AND e.event_day<=s.report_date+INTERVAL 30 DAY) AS TINYINT)"""))
    stats = records(con, "SELECT split,margin_segment,count(*) AS rows,sum(loan_label_next) AS positives,avg(loan_label_next) AS positive_rate FROM candidate GROUP BY ALL ORDER BY 1,2")
    for split in ["train", "validation", "test"]:
        for segment in ["nu", "lu", "au"]:
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

    # ---- Overdue use case gates (decisions 11.3 and 14.5) ----
    check("overdue.invalid_domains", scalar(con, """SELECT count(*) FROM candidate WHERE overdue_eligible NOT IN (0,1)
        OR (overdue_eligible=1 AND (overdue_label_next_30d IS NULL OR overdue_label_next_30d NOT IN (0,1)))
        OR (overdue_eligible=0 AND overdue_label_next_30d IS NOT NULL)
        OR over_limit_streak<0 OR over_limit_days_30d NOT BETWEEN 0 AND 30"""))
    check("overdue.nu_never_eligible", scalar(con, "SELECT count(*) FROM candidate WHERE overdue_eligible=1 AND margin_segment='nu'"))
    check("overdue_label_independent_audit", scalar(con, """SELECT count(*) FROM audit_sample s WHERE
        s.overdue_eligible IS DISTINCT FROM CAST((s.margin_debt>0 OR s.history_count>0) AND
            coalesce((SELECT b.normalized_margin_status FROM balance_label_source b WHERE b.master_account=s.master_account AND b.business_date=s.report_date),'')<>'OVERDUE' AS TINYINT)
        OR s.overdue_label_next_30d IS DISTINCT FROM CAST(CASE WHEN s.overdue_eligible=1 THEN
            EXISTS(SELECT 1 FROM balance_label_source b WHERE b.master_account=s.master_account AND b.business_date>s.report_date
                   AND b.business_date<=s.report_date+INTERVAL 30 DAY AND b.normalized_margin_status='OVERDUE') END AS TINYINT)"""))
    overdue_stats = records(con, "SELECT split,margin_segment,count(*) AS rows,sum(overdue_label_next_30d) AS positives,avg(overdue_label_next_30d) AS positive_rate FROM candidate WHERE overdue_eligible=1 GROUP BY ALL ORDER BY 1,2")
    for split in ["train", "validation", "test"]:
        check(f"overdue.{split}.eligible_rows_at_least_50000", sum(r["rows"] for r in overdue_stats if r["split"] == split) >= 50_000, True)
    overdue_rate = scalar(con, "SELECT avg(overdue_label_next_30d) FROM candidate WHERE overdue_eligible=1")
    check("overdue.positive_rate_5_to_30pct", overdue_rate is not None and .05 <= overdue_rate <= .30, True)
    for seg in ["lu", "au"]:
        rows = [r for r in overdue_stats if r["margin_segment"] == seg]
        total, pos = sum(r["rows"] for r in rows), sum(r["positives"] for r in rows)
        check(f"overdue.{seg}.positive_rate_1_to_40pct", bool(total) and .01 <= pos / total <= .40, True)
        for split in ["train", "validation", "test"]:
            row = next((r for r in rows if r["split"] == split), None)
            check(f"overdue.{split}.{seg}.both_classes", bool(row and 0 < row["positives"] < row["rows"]), True)

    # ---- Campaign-response gates (decisions 11.4 and 14.5) ----
    campaign_summary = {"source_rows": scalar(con, "SELECT count(*) FROM customer_campaign")}
    if campaign_summary["source_rows"]:
        check("campaign.sent_to_inactive_or_young_accounts", scalar(con, """SELECT count(*) FROM customer_campaign c JOIN customer_account a USING(master_account)
            WHERE c.status='DELIVERED' AND (CAST(timezone('Asia/Ho_Chi_Minh', CAST(c.sent_at AS TIMESTAMPTZ)) AS DATE)>=a.account_close_date
               OR CAST(timezone('Asia/Ho_Chi_Minh', CAST(c.sent_at AS TIMESTAMPTZ)) AS DATE)>=a.dormant_start_date
               OR CAST(timezone('Asia/Ho_Chi_Minh', CAST(c.sent_at AS TIMESTAMPTZ)) AS DATE)<a.account_open_date+INTERVAL 30 DAY)"""))
        check("campaign.duplicate_keys", scalar(con, "SELECT count(*) FROM (SELECT campaign_event_id FROM campaign_candidate GROUP BY ALL HAVING count(*)>1)"))
        check("campaign.invalid_domains", scalar(con, """SELECT count(*) FROM campaign_candidate WHERE campaign_response_label_14d NOT IN (0,1)
            OR campaign_response_label_14d IS NULL OR split NOT IN ('train','validation','test')
            OR channel NOT IN ('APP','SMS','EMAIL') OR offer_type NOT IN ('RATE_DISCOUNT','FEE_WAIVER','LIMIT_BOOST')
            OR interest_rate_offer NOT BETWEEN 0.065 AND 0.105 OR account_age_days<30 OR campaign_count_30d<0"""))
        check("campaign.incomplete_label_window", con.execute("SELECT count(*) FROM campaign_candidate WHERE report_date+INTERVAL 14 DAY>?", [raw_end]).fetchone()[0])
        check("campaign_label_independent_audit", scalar(con, """SELECT count(*) FROM (SELECT * FROM campaign_candidate ORDER BY hash(campaign_event_id) LIMIT 150) s
            WHERE s.campaign_response_label_14d<>CAST(EXISTS(SELECT 1 FROM valid_events e WHERE e.master_account=s.master_account
                  AND e.event_day>s.report_date AND e.event_day<=s.report_date+INTERVAL 14 DAY) AS TINYINT)"""))
        by_split = records(con, "SELECT split,count(*) AS rows,avg(campaign_response_label_14d) AS positive_rate FROM campaign_candidate GROUP BY ALL ORDER BY 1")
        for split in ["train", "validation", "test"]:
            check(f"campaign.{split}.rows_at_least_5000", any(r["split"] == split and r["rows"] >= 5000 for r in by_split), True)
        campaign_rate = scalar(con, "SELECT avg(campaign_response_label_14d) FROM campaign_candidate")
        check("campaign.positive_rate_8_to_40pct", campaign_rate is not None and .08 <= campaign_rate <= .40, True)
        # Lift is standardised by segment: campaigns skew towards nu/lu, whose base rate is lower.
        treated = records(con, "SELECT margin_segment,count(*) AS n,avg(campaign_response_label_14d) AS rate FROM campaign_candidate GROUP BY ALL")
        baseline = {r["margin_segment"]: r["rate"] for r in records(con, "SELECT margin_segment,avg(CAST(baseline_events_14d>0 AS DOUBLE)) AS rate FROM candidate WHERE campaign_count_14d_internal=0 GROUP BY ALL")}
        expected = sum(r["n"] * baseline.get(r["margin_segment"], 0.0) for r in treated)
        lift = sum(r["n"] * r["rate"] for r in treated) / expected if expected else None
        check("campaign.segment_standardised_lift_1_2_to_2_5", lift is not None and 1.2 <= lift <= 2.5, True)
        offers = records(con, "SELECT offer_type,count(*) AS rows,avg(campaign_response_label_14d) AS rate FROM campaign_candidate GROUP BY ALL ORDER BY 1")
        spread = max(r["rate"] for r in offers) - min(r["rate"] for r in offers) if offers else 0.0
        check("campaign.offer_response_spread_at_least_1_5pp", spread >= .015, True)
        campaign_summary.update({"by_split": by_split, "positive_rate": campaign_rate, "lift": lift, "by_offer": offers, "offer_spread": spread})
    return {"status": "PASS" if all(c["passed"] for c in checks) else "FAIL", "checks": checks,
            "overdue_by_split_segment": overdue_stats, "overdue_positive_rate": overdue_rate, "campaign": campaign_summary,
            "rows": scalar(con, "SELECT count(*) FROM candidate"), "positive_rate": overall,
            "scoring_rows": scalar(con, "SELECT count(*) FROM scoring_features"),
            "feast_label_rows": {"loan_overdue_labels": scalar(con, "SELECT count(*) FROM loan_overdue_labels"),
                                 "campaign_labels": scalar(con, "SELECT count(*) FROM campaign_labels"),
                                 "campaign_dropped_without_prior_snapshot": scalar(con, "SELECT count(*) FROM campaign_candidate") - scalar(con, "SELECT count(*) FROM campaign_labels")},
            "scoring_report_date_range": [str(x) for x in con.execute("SELECT min(report_date),max(report_date) FROM scoring_features").fetchone()],
            "by_segment": rates, "by_split_segment": stats,
            "last_snapshot_shares": last_shares,
            "embargo_rows_excluded": scalar(con, "SELECT count(*) FROM snapshots WHERE split IS NULL"),
            "null_required_rows": scalar(con, "SELECT count(*) FROM candidate WHERE " + " OR ".join(f'"{k}" IS NULL' for k in columns))}


def weights(con, approved):
    result = {"method": "balanced: N / (2 * N_class)", "fit_split": "train", "approved_for_training": approved, "segments": {}}
    for seg in ["nu", "lu", "au"]:
        counts = dict(con.execute("SELECT loan_label_next,count(*) FROM candidate WHERE split='train' AND margin_segment=? GROUP BY 1", [seg]).fetchall())
        result["segments"][seg] = {"counts": counts, "weights": {str(k): sum(counts.values()) / (2 * v) for k,v in counts.items()} if len(counts)==2 else None}
    return result


def _balanced(counts):
    return {str(k): sum(counts.values()) / (2 * v) for k, v in counts.items()} if len(counts) == 2 else None


def extra_weights(con):
    """Class weights for the secondary use cases, fit on the train split only."""
    result = {"overdue_risk": {"fit_split": "train", "segments": {}}, "campaign_response": {"fit_split": "train"}}
    for seg in ["lu", "au"]:
        counts = dict(con.execute("SELECT overdue_label_next_30d,count(*) FROM candidate WHERE split='train' AND overdue_eligible=1 AND margin_segment=? GROUP BY 1", [seg]).fetchall())
        result["overdue_risk"]["segments"][seg] = {"counts": counts, "weights": _balanced(counts)}
    counts = dict(con.execute("SELECT campaign_response_label_14d,count(*) FROM campaign_candidate WHERE split='train' GROUP BY 1").fetchall())
    result["campaign_response"].update({"counts": counts, "weights": _balanced(counts)})
    return result


def output_queries():
    """Published tables: name -> (SELECT over the built DuckDB tables, sort keys used for readback)."""
    internal = "history_count, recent_events, baseline_events_14d, campaign_count_14d_internal"
    outputs = {name: (f'SELECT {", ".join(chr(34)+k+chr(34) for k in KEYS)}, {EOD_TIMESTAMP}, {", ".join(chr(34)+f+chr(34) for f in fields)} '
                      f'FROM scoring_features ORDER BY master_account, report_date', KEYS) for name, fields in GROUPS.items()}
    outputs.update({
        # Reference dataset: features + labels in one table (parity target for Feast retrieval).
        "training_dataset": (f"SELECT * EXCLUDE({internal}) FROM candidate ORDER BY master_account, report_date", KEYS),
        "campaign_training_dataset": ("SELECT * FROM campaign_candidate ORDER BY master_account, report_date, campaign_event_id", ["campaign_event_id"]),
        # Feast entity_df tables: keys + timestamp + labels, no features.
        "loan_overdue_labels": (f"SELECT master_account, report_date, {EOD_TIMESTAMP}, * EXCLUDE(master_account, report_date) "
                                f"FROM loan_overdue_labels ORDER BY master_account, report_date", KEYS),
        "campaign_labels": ("SELECT * EXCLUDE(sent_at), sent_at AS event_timestamp FROM campaign_labels ORDER BY campaign_event_id", ["campaign_event_id"]),
    })
    return outputs


def utc_timestamps(table):
    """Store every timezone-aware timestamp as microsecond UTC (Iceberg timestamptz, Feast)."""
    for index, field in enumerate(table.schema):
        if pa.types.is_timestamp(field.type) and field.type.tz is not None:
            table = table.set_column(index, field.name, table.column(index).cast(pa.timestamp("us", tz="UTC")))
    return table


def write_json(path, obj):
    """Replace one JSON file atomically; keep the previous file on write failure."""
    payload = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(args):
    started = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    out = ROOT / "data/features/day4_runs" / run_id
    con = duckdb.connect()
    con.execute("SET TimeZone='Asia/Ho_Chi_Minh'")
    con.execute("SET threads=4")
    cat = catalog()
    source_pointer = ROOT / 'data/source_current.json'
    source_namespace = args.source_namespace or (json.loads(source_pointer.read_text())['namespace'] if source_pointer.exists() else 'raw')
    source_versions = {}
    for name in ALL_SOURCE_KEYS:
        if not cat.table_exists(f"{source_namespace}.{name}"):
            continue  # validate_sources reports missing tables without a SQL bind error.
        table = cat.load_table(f"{source_namespace}.{name}")
        snapshot = table.current_snapshot()
        source_versions[name] = {"metadata": table.metadata_location, "snapshot_id": snapshot.snapshot_id if snapshot else None}
        con.register("source_arrow", table.scan(snapshot_id=snapshot.snapshot_id if snapshot else None).to_arrow())
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM source_arrow")
        con.unregister("source_arrow")
        print(f"Read {source_namespace}.{name}: {scalar(con, f'SELECT count(*) FROM {name}'):,}", flush=True)
    source_report = validate_sources(con, args.raw_end)
    source_report.update({"source_namespace": source_namespace, "source_snapshots": source_versions, "raw_end": args.raw_end})
    report_dir = ROOT / "data/features"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_dir / "source_validation.json", source_report)
    if source_report["status"] != "PASS":
        con.close()
        print(json.dumps(source_report, indent=2, default=str), flush=True)
        print("Source validation FAIL: no feature files or Iceberg tables created.", flush=True)
        return 2
    normalize(con)
    build(con, args.raw_end)
    report = assess(con, args.raw_end)
    if report["status"] != "PASS":
        report.update({"source_namespace": source_namespace, "source_snapshots": source_versions, "raw_end": args.raw_end})
        write_json(report_dir / "rejected_quality_report.json", report)
        con.close()
        print("Quality gate FAIL: report only, no dataset or class weights exported.", flush=True)
        return 2
    out.mkdir(parents=True)
    report.update({"run_id": run_id, "source_namespace": source_namespace, "source_snapshots": source_versions, "raw_end": args.raw_end,
                   "feature_contract": FEATURE_CONTRACT, "outputs": {}, "namespace": f"features_{run_id.lower()}"})
    namespace = report["namespace"]
    cat.create_namespace(namespace)
    outputs = output_queries()
    for name, (sql, sort_cols) in outputs.items():
        arrow = utc_timestamps(con.execute(sql).to_arrow_table())
        path = out / f"{name}.parquet"
        pq.write_table(arrow, path)
        table = cat.create_table(f"{namespace}.{name}", schema=arrow.schema, properties={"quality.status": report["status"], "day4.run_id": run_id})
        snapshot_id = None
        if arrow.num_rows:
            table.append(arrow)
            snapshot_id = table.current_snapshot().snapshot_id
        readback = table.scan().to_arrow()
        # Scan the data files, not just metadata row counts. Ignore scan order.
        sort_keys = [(k, 'ascending') for k in sort_cols]
        # Iceberg widens int8 labels to int32; safe cast checks values losslessly.
        if not readback.cast(arrow.schema, safe=True).sort_by(sort_keys).equals(pq.read_table(path).sort_by(sort_keys), check_metadata=False):
            raise RuntimeError(f"Iceberg/Parquet content verification failed for {name}")
        report["outputs"][name] = {"parquet": str(path), "rows": readback.num_rows, "iceberg": f"{namespace}.{name}",
                                   "snapshot_id": snapshot_id, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        print(f"Verified {name}: {readback.num_rows:,} rows", flush=True)
    write_json(out / "usecase_registry.json", {
        "feature_contract": FEATURE_CONTRACT,
        "shared_feature_groups": list(GROUPS),
        "use_cases": {
            "loan_propensity": {"label": "loan_label_next", "training_dataset": "training_dataset", "entity_key": KEYS},
            "overdue_risk": {"label": "overdue_label_next_30d", "training_dataset": "training_dataset", "entity_key": KEYS},
            "campaign_response": {"label": "campaign_response_label_14d", "training_dataset": "campaign_training_dataset", "entity_key": ["campaign_event_id"]},
        },
        # Feast path (decisions: Feast offline is the feature access path for training and batch scoring).
        "feast": {
            "repo": "feature_repo",
            "loan_propensity": {"feature_service": "loan_propensity", "entity_df": "loan_overdue_labels", "label": "loan_label_next"},
            "overdue_risk": {"feature_service": "overdue_risk", "entity_df": "loan_overdue_labels", "label": "overdue_label_next_30d", "row_filter": "overdue_eligible = 1"},
            "campaign_response": {"feature_service": "campaign_response", "entity_df": "campaign_labels", "label": "campaign_response_label_14d",
                                  "request_features": ["channel", "offer_type", "interest_rate_offer", "campaign_count_30d", "days_since_last_campaign", "has_campaign_history"]},
        },
    })
    weight_result = weights(con, approved=True)
    weight_result.update(extra_weights(con))
    write_json(out / "class_weights.json", weight_result)
    report["elapsed_seconds"] = round(time.monotonic()-started, 2)
    write_json(out / "quality_report.json", report)
    write_report(report, weight_result, out)
    write_json(ROOT / "data/features/current.json", {"run_id": run_id, "path": str(out), "namespace": namespace,
                                                   "source_namespace": source_namespace})
    write_json(source_pointer, {'namespace': source_namespace, 'approved_by_day4_run': run_id})
    print(f"Quality gate: {report['status']}; artifacts: {out}", flush=True)
    con.close()
    return 0


def write_report(report, weight_result, out):
    """Render a reproducible report from the verified run's actual statistics."""
    passed = sum(item["passed"] for item in report["checks"])
    lines = [
        "# Báo cáo Ngày 4 — Feature engineering và nhãn", "",
        "## Kết luận", "",
        f"**PASS {passed}/{len(report['checks'])} quality checks** trên nguồn {report['source_namespace']}.",
        f"Run: {report['run_id']}; {report['rows']:,} snapshot; {report['elapsed_seconds']} giây cho pipeline ngày 4.",
        f"Positive rate toàn bộ: {report['positive_rate']:.4%}. Null ở cột bắt buộc: {report['null_required_rows']}.", "",
        "Đầu ra đã được duyệt qua data/features/current.json. Nguồn mặc định cho lần chạy tiếp theo nằm trong data/source_current.json.", "",
        "## Các lỗi nguồn đã sửa", "",
        "- Sinh timestamp bằng datetime/timedelta; lưu UTC microsecond trong Iceberg, tính ngày nghiệp vụ theo Asia/Ho_Chi_Minh.",
        "- Cash-flow dùng schema chuẩn fk_product/fk_cash_flow_type/fk_deliver_type; phân biệt POSTED/CANCELLED, repayment, fee và non-target event.",
        "- Suy ra ACTIVE/DORMANT/CLOSED theo từng ngày. Giữ balance đến raw_end; số dư về 0 từ ngày đóng.",
        "- Hạn mức theo risk_profile; amount giải ngân bị chặn bởi available_limit; OVERDUE chỉ sau ba ngày giao dịch vượt hạn mức.",
        "- Tính NAV và collateral_value; tỷ lệ có mẫu số 0 trả về 0.0.",
        "- Ngày mở tài khoản nằm trong tháng 1; archetype chỉ dùng nội bộ để sinh hành vi.",
        "- RNG tách theo tài khoản/stream, được kiểm thử không thay đổi dữ liệu tài khoản cũ khi thêm tài khoản mới.", "",
        "## Thay đổi đã được người dùng duyệt", "",
        "Xác suất trả nợ tăng từ 5% lên 10%/ngày khi ACTIVE và có dư nợ; đã cập nhật decision §8.5 cùng các cấu hình tương ứng.",
        "Giữ nguyên định nghĩa label và toàn bộ ngưỡng quality gate. Calibration chỉ điều chỉnh xác suất sinh event, không thay nhãn sau khi sinh.",
        "Metadata/snapshot ID của chính nguồn được kiểm tra nằm trong quality_report.json. Tham số generator và calibration cần đối chiếu với generation_run.json của lần sinh nguồn tương ứng; báo cáo này không suy đoán từ tên thư mục.", "",
        "## Feature và nhãn", "",
        "Snapshot account-day có khóa (master_account, report_date). Bảng fs_* không chứa label; training_dataset dùng cho loan/overdue, còn campaign_training_dataset có grain campaign-event.",
        "Feature chỉ dùng dữ liệu đến cuối ngày D; cửa sổ 7 ngày là D−6..D, 30 ngày là D−29..D.",
        "debt_change_7d lấy đúng số dư D−7, không dịch bảy dòng trên một tập đã lọc.",
        "loan_label_next dùng event POSTED đúng tổ hợp Margin MBS hoặc MBLink trong D+1..D+30. overdue_label_next_30d là lần bắt đầu OVERDUE mới trong D+1..D+30, chỉ cho tài khoản có dư nợ hoặc lịch sử margin và không đang OVERDUE tại D; campaign_response_label_14d dùng valid event trong 14 ngày sau lần gửi DELIVERED.",
        "Segment: au khi còn dư nợ hoặc có event hợp lệ trong 30 ngày gần nhất; lu khi từng dùng nhưng hiện không dư nợ và không có event gần đây; còn lại nu.",
        "Không xuất days_since_last_margin_event, biến ẩn hoặc cờ generator vào feature.", "",
        "| Nhóm | Feature |", "|---|---|",
    ]
    for name, fields in GROUPS.items():
        lines.append(f"| {name} | {', '.join(fields)} |")
    lines += [
        "", "## Split và kết quả", "",
        "Train: 2025-02-01..2025-06-30; validation: 2025-07-31..2025-09-30; test: 2025-10-31..2025-12-31.",
        f"Đã loại {report['embargo_rows_excluded']:,} snapshot embargo. Chỉ lấy tài khoản ACTIVE, tuổi ≥30 ngày và đủ 30 ngày dữ liệu tương lai.", "",
        "| Split | Segment | Số dòng | Positive | Positive rate |", "|---|---|---:|---:|---:|",
    ]
    for row in report["by_split_segment"]:
        lines.append(f"| {row['split']} | {row['margin_segment']} | {row['rows']:,} | {row['positives']:,} | {row['positive_rate']:.4%} |")
    lines += ["", "Tỷ trọng tại snapshot cuối (gate: mỗi segment ≥10%):", ""]
    for segment, share in report["last_snapshot_shares"].items():
        lines.append(f"- {segment}: {share:.4%}.")
    lines += [
        "", "## Class imbalance", "",
        "Balanced class weight = N/(2×N_class), tính riêng từng segment trên train. Không resample validation/test; không kết hợp thêm scale_pos_weight.",
        "", "| Segment | Weight 0 | Weight 1 |", "|---|---:|---:|",
    ]
    for segment, values in weight_result["segments"].items():
        w=values["weights"]
        lines.append(f"| {segment} | {w['0']:.6f} | {w['1']:.6f} |")
    lines += [
        "", "## Kiểm chứng", "",
        "- Source gate: schema, timestamp, lịch sử balance đầy đủ.",
        "- Quality gate: khóa, null, foreign key, miền giá trị, vòng đời tài khoản, biên thời gian, cả hai lớp trong từng split/segment.",
        "- Đối soát dư nợ toàn bộ panel bằng giải ngân/trả nợ POSTED và trạng thái đóng tài khoản.",
        "- Đối chiếu độc lập rolling/label cho 150 snapshot bằng truy vấn trực tiếp.",
        "- Đọc lại mọi bảng Iceberg, sắp theo khóa và so sánh toàn bộ nội dung với Parquet; có SHA-256 và snapshot IDs trong quality_report.json.",
        "- Unit tests tại tests/test_day4.py và tests/test_generator.py: boundary, point-in-time, lifecycle, RNG độc lập, công thức số dư, timezone và class weights.", "",
        "## Đầu ra", "", f"Thư mục: {out}", "",
    ]
    for name, detail in report["outputs"].items():
        lines.append(f"- {name}.parquet: {detail['rows']:,} dòng; Iceberg {detail['iceberg']}.")
    lines += [
        "- quality_report.json: checks, provenance, hashes.",
        "- class_weights.json: weights đã duyệt.",
        "- data/features/current.json: trỏ đến phiên bản training đã duyệt.",
        "- data/source_current.json: trỏ đến nguồn Iceberg đã duyệt.", "",
        "## Giới hạn và phạm vi nghiệm thu", "",
        "PASS áp dụng cho quality gate ngày 4. Tỷ trọng segment đã đạt ngưỡng tối thiểu; chưa khớp các mục tiêu tham khảo nu=35–55%, lu=20–40%, au=15–35% trong decision §10.",
        "Chưa nghiệm thu mục tiêu thống kê bổ sung như số giao dịch/tháng. Chưa train model (ngày 6), chưa đánh giá hiệu quả kinh doanh trên dữ liệu thật.",
        "Nguồn không có ingestion timestamp nên kiểm thử point-in-time hiện bao phủ event time, chưa bao phủ late-arriving data trong production.",
        "Các đường dẫn trong báo cáo thuộc môi trường tạo run. Khi chuyển máy, cần ingest lại dữ liệu và tạo run mới; không suy ra trạng thái hiện tại chỉ từ một báo cáo lịch sử.", "",
        "## Chạy lại", "", "```powershell",
        ".\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v",
        ".\\.venv\\Scripts\\python.exe scripts/day4_feature_engineering.py",
        "```", "", "Exit 2 chỉ ghi báo cáo lỗi; không xuất dataset khi gate FAIL.",
        "Muốn cập nhật Markdown từ run đã duyệt mà không tạo thêm dataset: thêm --report-only.", "",
    ]
    (ROOT / "docs/day4_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-end", type=date.fromisoformat, default=date(2026, 1, 30))
    parser.add_argument("--source-namespace", help="Explicit source namespace; otherwise use the last approved source, or raw.")
    parser.add_argument("--report-only", action="store_true", help="Refresh Markdown from the current approved run without rebuilding data.")
    args = parser.parse_args()
    if args.report_only:
        pointer = json.loads((ROOT / "data/features/current.json").read_text())
        output = Path(pointer["path"])
        write_report(json.loads((output / "quality_report.json").read_text()),
                     json.loads((output / "class_weights.json").read_text()), output)
    else:
        sys.exit(run(args))
