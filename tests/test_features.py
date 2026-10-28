"""Daily feature store (features/): one day alone = the full rebuild = the legacy script, partition writes, gate, marker.

The legacy full-rebuild script (scripts/day4_feature_engineering.py) is the oracle: the daily job must produce the
same rows for a day as the old job did, although it reads only the small Gold tables in full and 30 days of the rest.
"""
import datetime as dt
import json

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa
from pyiceberg.catalog.sql import SqlCatalog

from features import publish, quality, status, store, write
from features.backfill import months
from features.common import FEATURE_COLUMNS, FS_TABLES, GROUPS, load_settings, table_name
from features.compute import build, connect, outputs
from features.maintenance import cutoff_for, path_key
from scripts.day4_feature_engineering import build as legacy_build, normalize as legacy_normalize
from tests.test_day4 import fixture

GOLD = ["customer_account", "margin_balance_daily", "stock_transaction", "margin_cash_flow"]
START, END = dt.date(2025, 2, 1), dt.date(2025, 3, 10)
COLUMNS = ["master_account", "report_date"] + FEATURE_COLUMNS


def scenario(c):
    """Fixture + an over-limit spell crossing day boundaries, campaigns, OVERDUE days."""
    c.execute("UPDATE margin_balance_daily SET margin_debt=10,margin_limit=5 WHERE master_account='A' "
              "AND business_date BETWEEN '2025-01-28' AND '2025-02-05'")
    c.execute("ALTER TABLE margin_balance_daily ADD COLUMN margin_status VARCHAR DEFAULT 'NO_MARGIN'")
    c.execute("UPDATE margin_balance_daily SET margin_status='OVERDUE' WHERE master_account='B' "
              "AND business_date IN ('2025-03-03','2025-05-10')")
    c.execute("""CREATE TABLE customer_campaign(campaign_event_id VARCHAR,campaign_id VARCHAR,master_account VARCHAR,
        sent_at TIMESTAMPTZ,channel VARCHAR,offer_type VARCHAR,interest_rate_offer DOUBLE,status VARCHAR)""")
    for i, (account, sent, state) in enumerate([("A", "2025-01-20 10:00:00+07", "DELIVERED"),
                                                ("A", "2025-02-05 10:00:00+07", "DELIVERED"),
                                                ("B", "2025-02-01 10:00:00+07", "DELIVERED"),
                                                ("C", "2025-03-01 23:30:00+07", "DELIVERED"),
                                                ("D", "2025-02-01 10:00:00+07", "FAILED"),
                                                ("B", "2025-08-03 08:00:00+07", "DELIVERED")]):
        c.execute("INSERT INTO customer_campaign VALUES (?,'M',?,?::TIMESTAMPTZ,'APP','RATE_DISCOUNT',0.07,?)",
                  [f"E{i}", account, sent, state])
    return c


def gold_connection():
    """A features.compute connection holding the scenario's Gold tables."""
    con, source = connect(), scenario(fixture())
    for table in GOLD + ["customer_campaign"]:
        con.register("x", source.execute(f"SELECT * FROM {table}").to_arrow_table())
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM x")
        con.unregister("x")
    return con


def rows(con, table="scoring_features"):
    select = ", ".join(f'"{c}"' for c in COLUMNS)
    return sorted(con.execute(f"SELECT {select} FROM {table}").fetchall())


@pytest.fixture(scope="module")
def full():
    con = gold_connection()
    build(con, START, END)
    return con


def test_full_range_equals_the_legacy_rebuild(full):
    legacy = scenario(fixture())
    legacy_normalize(legacy)
    legacy_build(legacy, dt.date(2026, 1, 30))
    legacy.execute(f"CREATE TABLE legacy_rows AS SELECT * FROM scoring_features WHERE report_date BETWEEN '{START}' AND '{END}'")
    assert rows(full) == rows(legacy, "legacy_rows")


def test_every_day_alone_equals_the_full_range(full):
    """No run depends on another: any day, computed alone and in any order, gives the rows of the full range."""
    expected = rows(full)
    for offset in (0, 6, 13, 20, 27, 31, 37):
        day = START + dt.timedelta(days=offset)
        con = gold_connection()
        build(con, day, day)
        assert rows(con) == [r for r in expected if r[1] == day], day


def test_a_later_start_gives_the_same_rows(full):
    con = gold_connection()
    build(con, dt.date(2025, 2, 20), END)
    assert rows(con) == [r for r in rows(full) if r[1] >= dt.date(2025, 2, 20)]


def test_large_tables_are_read_for_30_days_only(full):
    """Trades older than the lookback are gone, the small tables (balances, cash flows, campaigns) stay whole."""
    con = gold_connection()
    day = dt.date(2025, 3, 10)
    con.execute("DELETE FROM stock_transaction WHERE CAST(transaction_time AS TIMESTAMPTZ) < TIMESTAMPTZ '2025-02-08 00:00:00+07'")
    build(con, day, day)
    assert rows(con) == [r for r in rows(full) if r[1] == day]

def test_outputs_follow_the_contract(full):
    tables = outputs(full)
    for name, columns in GROUPS.items():
        assert tables[name].schema.names == ["master_account", "report_date", "event_timestamp", *columns]
        assert str(tables[name].schema.field("event_timestamp").type) == "timestamp[us, tz=UTC]"


# ---- Iceberg partitions, control.fs_status, quality gate ----

@pytest.fixture
def lake(tmp_path):
    cat = SqlCatalog("t", uri=f"sqlite:///{tmp_path / 'catalog.db'}", warehouse=f"file://{tmp_path / 'wh'}")
    statuses = status.StatusStore(sa.create_engine(f"sqlite:///{tmp_path / 'control.db'}"))
    return cat, statuses, tmp_path


def stage(tmp_path, con, start, end, name):
    out = tmp_path / name
    out.mkdir()
    for table, arrow in outputs(con).items():
        pq.write_table(arrow, out / f"{table}.parquet")
    (out / "run.json").write_text(json.dumps({"run_id": name, "start": str(start), "end": str(end)}))
    return out


def test_rerunning_a_day_replaces_only_that_partition(lake, full):
    cat, statuses, tmp = lake
    write.write(cat, stage(tmp, full, START, END, "run1"), statuses)
    before = {p["partition"]["report_date"]: p for p in cat.load_table(table_name("fs_margin_balance")).inspect.partitions().to_pylist()}
    assert len(before) == (END - START).days + 1

    day = dt.date(2025, 2, 10)
    con = gold_connection()
    con.execute(f"UPDATE margin_balance_daily SET cash_balance = 777 WHERE business_date = '{day}'")  # source fixed
    build(con, day, day)
    staged = stage(tmp, con, day, day, "run2")
    write.write(cat, staged, statuses)
    assert not staged.exists()  # staging is dropped once written

    table = cat.load_table(table_name("fs_asset_balance"))
    after = {p["partition"]["report_date"]: p for p in cat.load_table(table_name("fs_margin_balance")).inspect.partitions().to_pylist()}
    assert {d: p["record_count"] for d, p in after.items()} == {d: p["record_count"] for d, p in before.items()}
    assert all(after[d]["last_updated_at"] == before[d]["last_updated_at"] for d in before if d != day)
    assert set(table.scan(row_filter=f"report_date = '{day}'").to_arrow().column("cash_balance").to_pylist()) == {777}
    assert 777 not in table.scan(row_filter=f"report_date <> '{day}'").to_arrow().column("cash_balance").to_pylist()
    assert statuses.get(day)["status"] == status.WRITTEN and statuses.get(day)["run_id"] == "run2"


def test_only_a_day_that_passed_the_gate_is_published_and_served(lake, full):
    cat, statuses, tmp = lake
    write.write(cat, stage(tmp, full, START, END, "run1"), statuses)
    day = dt.date(2025, 3, 1)
    with pytest.raises(SystemExit):
        publish.publish(day, day, statuses)       # WRITTEN, gate not run
    with pytest.raises(SystemExit):
        store.read_day(cat, day, statuses)        # never served before COMPLETE
    result = quality.check(cat, START, END, statuses)
    assert {r["status"] for r in result.values()} == {status.QUALITY_PASSED}
    publish.publish(START, END, statuses)
    snapshot, run_id = store.read_day(cat, day, statuses)
    assert run_id == "run1" and len(snapshot) == 4 and set(FEATURE_COLUMNS) <= set(snapshot.columns)
    statuses.set([day], status.WRITING)           # a re-run starts: the marker is withdrawn at once
    with pytest.raises(SystemExit):
        store.read_day(cat, day, statuses)
    assert statuses.latest_complete() == END


def gate(con_rows: dict[str, pd.DataFrame], covered, previous=None, contract=None):
    con = duckdb.connect()
    for name, frame in con_rows.items():
        con.register(name, frame)
    return quality.evaluate(con, covered, previous, load_settings()["quality"], contract or {})


def test_quality_gate_catches_broken_partitions(full):
    tables = {name: t.to_pandas() for name, t in outputs(full).items() if name in FS_TABLES}
    covered = [dt.date(2025, 2, 10), dt.date(2025, 2, 11)]
    assert {r["status"] for r in gate(tables, covered).values()} == {status.QUALITY_PASSED}

    broken = dict(tables)
    first = broken["fs_campaign"][broken["fs_campaign"]["report_date"] == covered[0]].head(1)
    broken["fs_campaign"] = pd.concat([broken["fs_campaign"], first])                      # duplicate key
    asset = broken["fs_asset_balance"].copy()
    asset.loc[asset["report_date"] == covered[1], "cash_balance"] = None                   # nulls
    broken["fs_asset_balance"] = asset
    result = gate(broken, covered)
    assert "fs_campaign.duplicate_keys" in result[covered[0]]["failed"]
    assert "fs_asset_balance.null_rate" in result[covered[1]]["failed"]

    shrunk = {n: f[(f["report_date"] != covered[1]) | (f["master_account"] != "A")] for n, f in tables.items()}
    assert gate(shrunk, covered)[covered[1]]["failed"] == {"row_count_ratio": 0.75}           # 4 -> 3 accounts
    one_day = {n: f[f["report_date"] == covered[0]] for n, f in tables.items()}  # what check() reads for one day
    assert gate(one_day, covered[:1], previous=4)[covered[0]]["status"] == status.QUALITY_PASSED
    assert "row_count_ratio" in gate(one_day, covered[:1], previous=10)[covered[0]]["failed"]  # vs the day before
    assert gate(tables, covered[:1], contract={"fs_x": {"missing": ["a"]}})[covered[0]]["status"] == status.QUALITY_FAILED


def test_contract_problems():
    observed = {name: {"master_account": "string", "report_date": "date", "event_timestamp": "timestamptz", **cols}
                for name, cols in GROUPS.items()}
    assert quality.contract_problems(observed) == {}
    observed["fs_campaign"]["has_campaign_history"] = "int"
    observed["fs_portfolio"]["surprise"] = "long"
    del observed["fs_demographic"]["margin_segment"]
    problems = quality.contract_problems(observed)
    assert problems["fs_campaign"]["types"] == {"has_campaign_history": {"expected": "long", "observed": "int"}}
    assert problems["fs_portfolio"]["extra"] == ["surprise"] and problems["fs_demographic"]["missing"] == ["margin_segment"]


# ---- small pure helpers ----

def test_backfill_cuts_at_month_ends():
    assert months(dt.date(2025, 2, 10), dt.date(2025, 4, 2)) == [
        (dt.date(2025, 2, 10), dt.date(2025, 2, 28)), (dt.date(2025, 3, 1), dt.date(2025, 3, 31)),
        (dt.date(2025, 4, 1), dt.date(2025, 4, 2))]


def test_retention_counts_back_from_the_latest_day():
    assert cutoff_for(dt.date(2026, 1, 30), 12) == dt.date(2025, 1, 30)
    assert cutoff_for(dt.date(2026, 3, 31), 1) == dt.date(2026, 2, 28)


def test_path_key_ignores_the_scheme():
    assert path_key("s3://warehouse/features.db/x/data/a.parquet") == path_key("warehouse/features.db/x/data/a.parquet")
    assert path_key("file://C:\\tmp\\wh\\a.parquet") == path_key("C:/tmp/wh/a.parquet")


def test_status_rows_keep_the_run_id_across_steps(tmp_path):
    statuses = status.StatusStore(sa.create_engine(f"sqlite:///{tmp_path / 'c.db'}"))
    day = dt.date(2026, 1, 30)
    statuses.set([day], status.WRITTEN, run_id="r1")
    statuses.set([day], status.QUALITY_PASSED, row_counts={"fs_demographic": 4731})
    statuses.set([day], status.COMPLETE, published_at=status.now())
    row = statuses.get(day)
    assert (row["status"], row["run_id"], row["row_counts"]) == (status.COMPLETE, "r1", {"fs_demographic": 4731})
    assert status.require_complete(day, statuses)["run_id"] == "r1"
    assert statuses.delete_before(dt.date(2026, 1, 31)) == 1 and statuses.get(day) is None


# ---- the sensor and the serving switch ----

def test_wait_complete_polls_until_the_marker_or_the_timeout(tmp_path):
    statuses = status.StatusStore(sa.create_engine(f"sqlite:///{tmp_path / 'w.db'}"))
    day, polls, now = dt.date(2026, 1, 30), [], [0.0]

    def sleep(seconds):                       # time only moves when the sensor sleeps
        polls.append(seconds)
        now[0] += seconds
        if len(polls) == 2:                   # the day is published between the 2nd and 3rd poll
            statuses.set([day], status.COMPLETE)

    assert status.wait_complete(day, timeout_minutes=30, poll_seconds=30, statuses=statuses, sleep=sleep,
                                clock=lambda: now[0])
    assert polls == [30, 30]
    other = dt.date(2026, 1, 31)              # never published: the sensor gives up at the deadline
    now[0], polls[:] = 0.0, []
    assert not status.wait_complete(other, timeout_minutes=2, poll_seconds=30, statuses=statuses, sleep=sleep,
                                    clock=lambda: now[0])
    assert sum(polls) == 120
    statuses.set([other], status.QUALITY_FAILED)   # a failed gate is not COMPLETE either
    assert not status.wait_complete(other, 0, statuses=statuses)


def test_read_snapshot_serves_written_days_from_the_store_and_the_rest_from_the_run(lake, full, monkeypatch, tmp_path):
    from pipeline import common
    cat, statuses, tmp = lake
    write.write(cat, stage(tmp, full, START, END, "run1"), statuses)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    old_day = dt.date(2025, 1, 31)                  # before START: the feature store never wrote it
    earlier = gold_connection()
    build(earlier, old_day, old_day)
    for name, table in outputs(earlier).items():    # the approved run only knows old_day
        pq.write_table(table, run_dir / f"{name}.parquet")
    monkeypatch.setattr(status, "store", lambda: statuses)
    monkeypatch.setattr("features.common.catalog", lambda: cat)
    statuses.set([dt.date(2025, 3, 1)], status.COMPLETE)

    assert len(common.read_snapshot(run_dir, dt.date(2025, 3, 1))) == 4        # store: COMPLETE
    assert len(common.read_snapshot(run_dir, old_day)) == 4                    # no status row: the run's parquet
    statuses.set([dt.date(2025, 3, 2)], status.WRITTEN)
    with pytest.raises(SystemExit):                                            # written but not published: refused
        common.read_snapshot(run_dir, dt.date(2025, 3, 2))
