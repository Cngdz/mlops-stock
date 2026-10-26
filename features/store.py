"""Read side of the feature store: the rows a use case scores on day T (batch predict, drift).

Only COMPLETE days are served (control.fs_status). Account-day use cases read the six fs_* partitions of T and join
them on (master_account, report_date); campaign_response scores the DELIVERED sends of T instead (its own loader,
campaign.sql, shared with training so both build a send's row the same way).
"""
from __future__ import annotations

import datetime as dt

import duckdb
import pandas as pd
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import EqualTo

from features import gold, status
from features.common import FS_TABLES, KEYS, OVERDUE_ELIGIBLE_SQL, run_sql, table_name

CAMPAIGN_DATASET = "campaign_training_dataset"
EVENT_KEY = "campaign_event_id"


def assemble(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Join the fs_* frames of one or more days on (master_account, report_date). Pure."""
    out = frames[0].drop(columns=["event_timestamp"], errors="ignore")
    for frame in frames[1:]:
        out = out.merge(frame.drop(columns=["event_timestamp"], errors="ignore"), on=KEYS, how="inner",
                        validate="one_to_one")
    return out


def read_day(cat: Catalog, day: dt.date, statuses: status.StatusStore | None = None) -> tuple[pd.DataFrame, str]:
    """All feature groups of one COMPLETE day, and the feature run id that wrote it."""
    marker = status.require_complete(day, statuses)
    frames = [cat.load_table(table_name(name)).scan(row_filter=EqualTo("report_date", day.isoformat())).to_pandas()
              for name in FS_TABLES]
    snapshot = assemble(frames)
    if snapshot.empty:
        raise SystemExit(f"feature store day {day} is COMPLETE but has no rows")
    return snapshot, marker["run_id"]


def with_overdue_eligible(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Adds overdue_eligible with the same SQL expression build_training uses for the training rows."""
    con = duckdb.connect()
    con.register("snapshot", snapshot)
    out = con.execute(f"SELECT *, {OVERDUE_ELIGIBLE_SQL} AS overdue_eligible FROM snapshot").df()
    con.close()
    return out


def campaign_rows(con: duckdb.DuckDBPyConnection, accounts: pd.DataFrame | str) -> None:
    """customer_campaign loaded in con + account rows (a frame or a table name) -> DuckDB table campaign_rows."""
    if isinstance(accounts, str):
        con.execute(f"CREATE OR REPLACE VIEW campaign_accounts AS SELECT * FROM {accounts}")
    else:
        con.register("campaign_accounts", accounts)
    run_sql(con, "campaign.sql")


def campaign_sends(cat: Catalog, day: dt.date, snapshot: pd.DataFrame) -> pd.DataFrame:
    """The DELIVERED sends of day T with their features. Campaign history is read up to T (the history columns
    count earlier sends); sends of other days are not scored."""
    con = duckdb.connect()
    con.execute("SET TimeZone='Asia/Ho_Chi_Minh'")
    gold.load(con, cat, "customer_campaign", None, day)
    campaign_rows(con, snapshot)
    rows = con.execute("SELECT * FROM campaign_rows WHERE report_date = ? ORDER BY campaign_event_id", [day]).df()
    con.close()
    return rows


def usecase_rows(cat: Catalog, uc, day: dt.date) -> tuple[pd.DataFrame, str]:
    """(rows to score, feature run id) for one use case (training.config.UseCase) on day T."""
    snapshot, run_id = read_day(cat, day)
    if uc.dataset == CAMPAIGN_DATASET:
        return campaign_sends(cat, day, snapshot), run_id
    rows = with_overdue_eligible(snapshot)
    if uc.row_filter:
        rows = rows.query(uc.row_filter).reset_index(drop=True)
    return rows, run_id
