"""Gold side of the feature store: source contract, freshness, and loading a date window into DuckDB.

Gold is read-only for this system (docs 1.4). Tables live in the lakehouse catalog, namespace `gold`
(scripts/migrate_gold.py copies them from the old local SQLite catalog once).
"""
from __future__ import annotations

import datetime as dt

import duckdb
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import AlwaysTrue, And, BooleanExpression, GreaterThanOrEqual, LessThan, LessThanOrEqual

from features.common import gold_name

# Expected column kinds. "timestamp" also accepts a string column (parsed in SQL); "number" any numeric type.
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
        "cash_flow_id": "text", "master_account": "text", "event_date": "date", "status": "text",
        "fk_product": "text", "fk_cash_flow_type": "text", "fk_deliver_type": "text", "amount": "number",
    },
    "stock_price_daily": {"business_date": "date", "symbol": "text", "price": "number"},
    "security_master": {"symbol": "text", "sector": "text", "liquidity_group": "text", "margin_eligible": "boolean",
                        "risk_level": "text"},
    "portfolio_holding_daily": {"master_account": "text", "business_date": "date", "symbol": "text",
                                "quantity": "number", "market_value": "number", "portfolio_weight": "number"},
    "customer_campaign": {"campaign_event_id": "text", "master_account": "text", "campaign_id": "text",
                          "sent_at": "timestamp", "channel": "text", "offer_type": "text",
                          "interest_rate_offer": "number", "status": "text"},
}
ICEBERG_KINDS = {
    "text": {"string"}, "date": {"date"}, "boolean": {"boolean"},
    "timestamp": {"timestamptz", "timestamp", "string"},
    "number": {"int", "long", "float", "double"},
}
# Daily snapshot tables must reach T. Event tables (trades, cash flows, campaigns) can legitimately have no row on
# T, so their freshness cannot be told apart from a quiet day: only their schema is checked.
SNAPSHOT_TABLES = {"margin_balance_daily": "business_date", "portfolio_holding_daily": "business_date",
                   "stock_price_daily": "business_date"}
# Columns read per table, and the column a date window applies to (None = whole table, it is small).
READ = {
    "customer_account": (None, ["master_account", "account_open_date", "account_status", "account_close_date",
                                "dormant_start_date", "risk_profile"]),
    "margin_balance_daily": ("business_date", ["master_account", "business_date", "cash_balance", "asset_value",
                                               "margin_debt", "margin_limit", "margin_status"]),
    "stock_transaction": ("transaction_time", ["master_account", "transaction_time", "trade_value"]),
    "margin_cash_flow": ("event_date", ["master_account", "event_date", "status", "fk_product", "fk_cash_flow_type",
                                        "fk_deliver_type"]),
    "portfolio_holding_daily": ("business_date", ["master_account", "business_date", "symbol", "market_value",
                                                  "unrealized_pnl", "portfolio_weight"]),
    "security_master": (None, ["symbol", "risk_level"]),
    "customer_campaign": ("sent_at", ["campaign_event_id", "campaign_id", "master_account", "sent_at", "channel",
                                      "offer_type", "interest_rate_offer", "status"]),
}
VALID_EVENT = """status='POSTED' AND
    ((fk_product='MARGIN_MBS' AND fk_cash_flow_type='INTERM_DELIVER' AND fk_deliver_type='BUY_SHARE') OR
     (fk_product='MBLINK' AND fk_cash_flow_type='TLO_DELIVER_CASH' AND fk_deliver_type='BUY'))"""


def schema_problems(observed: dict[str, dict[str, str]]) -> dict:
    """observed: table -> column -> Iceberg type (missing table = absent key). Pure."""
    missing_tables = sorted(set(SOURCE_SCHEMA) - set(observed))
    missing_columns, invalid_types = {}, {}
    for table, expected in SOURCE_SCHEMA.items():
        if table not in observed:
            continue
        columns = observed[table]
        if missing := sorted(set(expected) - set(columns)):
            missing_columns[table] = missing
        if bad := {c: {"observed": columns[c], "expected": kind} for c, kind in expected.items()
                   if c in columns and columns[c] not in ICEBERG_KINDS[kind]}:
            invalid_types[table] = bad
    return {"missing_tables": missing_tables, "missing_columns": missing_columns, "invalid_column_types": invalid_types}


def observed_schema(cat: Catalog) -> dict[str, dict[str, str]]:
    out = {}
    for table in SOURCE_SCHEMA:
        if cat.table_exists(gold_name(table)):
            out[table] = {f.name: str(f.field_type) for f in cat.load_table(gold_name(table)).schema().fields}
    return out


def max_date(cat: Catalog, table: str, column: str) -> dt.date | None:
    """Largest value of a date column from the file statistics in the Iceberg metadata: no data scan."""
    files = cat.load_table(gold_name(table)).inspect.files()
    if files.num_rows == 0:
        return None
    bounds = [m[column]["upper_bound"] for m in files.column("readable_metrics").to_pylist() if m.get(column)]
    return max((b for b in bounds if b is not None), default=None)


def window_filter(column: str | None, start: dt.date | None, end: dt.date) -> BooleanExpression:
    """Rows with column in [start, end] (start None = all history). Timestamps are widened by a day on each side:
    the local (Asia/Ho_Chi_Minh) calendar day is cut exactly in SQL."""
    if column is None:
        return AlwaysTrue()
    if column in ("transaction_time", "sent_at"):
        upper = LessThan(column, f"{end + dt.timedelta(days=2)}T00:00:00+00:00")
        return upper if start is None else And(
            GreaterThanOrEqual(column, f"{start - dt.timedelta(days=1)}T00:00:00+00:00"), upper)
    upper = LessThanOrEqual(column, end.isoformat())
    return upper if start is None else And(GreaterThanOrEqual(column, start.isoformat()), upper)


def load(con: duckdb.DuckDBPyConnection, cat: Catalog, table: str, start: dt.date | None, end: dt.date) -> int:
    """Gold rows of one table in [start, end] -> DuckDB table of the same name. Returns the row count."""
    column, wanted = READ[table]
    iceberg = cat.load_table(gold_name(table))
    present = {f.name for f in iceberg.schema().fields}
    arrow = iceberg.scan(row_filter=window_filter(column, start, end),
                         selected_fields=tuple(c for c in wanted if c in present)).to_arrow()
    con.register("gold_arrow", arrow)
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM gold_arrow")
    con.unregister("gold_arrow")
    return arrow.num_rows


def normalize(con: duckdb.DuckDBPyConnection) -> None:
    """Views over the loaded Gold tables with canonical fields only; label semantics are never inferred.
    build_training loads only cash flows, balances and campaigns: views over absent tables are skipped."""
    loaded = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    columns = {r[0] for r in con.execute("DESCRIBE margin_cash_flow").fetchall()}
    if missing := {"fk_cash_flow_type", "fk_deliver_type"} - columns:
        raise ValueError(f"Missing cash-flow columns: {sorted(missing)}")
    # Optional in the small test fixtures; check_source requires all eight tables in production.
    con.execute("""CREATE TABLE IF NOT EXISTS security_master(symbol VARCHAR, risk_level VARCHAR)""")
    con.execute("""CREATE TABLE IF NOT EXISTS portfolio_holding_daily(master_account VARCHAR, business_date DATE,
        symbol VARCHAR, market_value BIGINT, unrealized_pnl BIGINT, portfolio_weight DOUBLE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS customer_campaign(campaign_event_id VARCHAR, campaign_id VARCHAR,
        master_account VARCHAR, sent_at TIMESTAMPTZ, channel VARCHAR, offer_type VARCHAR, interest_rate_offer DOUBLE,
        status VARCHAR)""")
    con.execute(f"""CREATE OR REPLACE VIEW valid_events AS
        SELECT master_account, CAST(event_date AS DATE) AS event_day FROM margin_cash_flow WHERE {VALID_EVENT}""")
    if "stock_transaction" in loaded:
        con.execute("""CREATE OR REPLACE VIEW trades AS SELECT master_account, trade_value,
            CAST(timezone('Asia/Ho_Chi_Minh', CAST(transaction_time AS TIMESTAMPTZ)) AS DATE) AS trade_date
            FROM stock_transaction""")
    balance_columns = {r[0] for r in con.execute("DESCRIBE margin_balance_daily").fetchall()}
    status = ("margin_status" if "margin_status" in balance_columns
              else "CASE WHEN margin_limit>0 AND margin_debt>margin_limit THEN 'OVERDUE' ELSE 'ACTIVE' END")
    con.execute(f"""CREATE OR REPLACE VIEW balances AS
        SELECT master_account, CAST(business_date AS DATE) AS business_date, cash_balance, asset_value,
               margin_debt, margin_limit, {status} AS margin_status
        FROM margin_balance_daily""")
    con.execute("""CREATE OR REPLACE VIEW portfolio_daily AS
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
