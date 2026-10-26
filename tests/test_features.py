"""Daily feature store (features/): incremental = full rebuild = legacy, partition writes, gate, marker, training data.

The legacy full-rebuild script (scripts/day4_feature_engineering.py) is the oracle: the daily job must produce the
same rows from 30 days of Gold plus the carried state as the old job did from all of it.
"""
import datetime as dt
import json

import duckdb
import pandas as pd
import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa
from pyiceberg.catalog.sql import SqlCatalog

from features import build_training, publish, quality, status, store, write
from features.backfill import months
from features.common import FEATURE_COLUMNS, FS_TABLES, GROUPS, OVERDUE_ELIGIBLE_SQL, load_settings, table_name
from features.compute import build, connect, outputs, seed_from
from features.maintenance import cutoff_for, path_key
from scripts.day4_feature_engineering import build as legacy_build, normalize as legacy_normalize
from tests.test_day4 import fixture

GOLD = ["customer_account", "margin_balance_daily", "stock_transaction", "margin_cash_flow"]
START, END = dt.date(2025, 2, 1), dt.date(2025, 3, 10)
COLUMNS = ["master_account", "report_date"] + [c for c in FEATURE_COLUMNS if c != "margin_status"]


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
    build(con, START, END, bootstrap=True)
    return con


def test_full_range_equals_the_legacy_rebuild(full):
    legacy = scenario(fixture())
    legacy_normalize(legacy)
    legacy_build(legacy, dt.date(2026, 1, 30))
    legacy.execute(f"CREATE TABLE legacy_rows AS SELECT * FROM scoring_features WHERE report_date BETWEEN '{START}' AND '{END}'")
    assert rows(full) == rows(legacy, "legacy_rows")


def test_day_by_day_with_carried_state_equals_the_full_range(full):
    con, daily, day = gold_connection(), [], START
    while day <= END:
        if day > START:
            seed_from(con, con.execute("SELECT * FROM state_out WHERE report_date = ?", [day - dt.timedelta(days=1)]).to_arrow_table())
        build(con, day, day, bootstrap=day == START)
        daily += rows(con)
        day += dt.timedelta(days=1)
    assert sorted(daily) == rows(full)


def test_bootstrap_on_a_later_day_rebuilds_the_same_state(full):
    con = gold_connection()
    build(con, dt.date(2025, 2, 20), END, bootstrap=True)
    assert rows(con) == [r for r in rows(full) if r[1] >= dt.date(2025, 2, 20)]


def test_a_day_reads_at_most_30_days_of_gold(full):
    con = gold_connection()
    day = dt.date(2025, 3, 10)
    seed_from(con, full.execute("SELECT * FROM state_out WHERE report_date = ?", [day - dt.timedelta(days=1)]).to_arrow_table())
    for table, column in [("margin_balance_daily", "business_date"), ("margin_cash_flow", "event_date")]:
        con.execute(f"DELETE FROM {table} WHERE {column} < DATE '{day}' - INTERVAL 30 DAY")  # older history is gone
    con.execute("DELETE FROM stock_transaction WHERE CAST(transaction_time AS TIMESTAMPTZ) < TIMESTAMPTZ '2025-02-08 00:00:00+07'")
    con.execute("DELETE FROM customer_campaign WHERE sent_at < TIMESTAMPTZ '2025-02-08 00:00:00+07'")
    build(con, day, day)
    assert rows(con) == [r for r in rows(full) if r[1] == day]


def test_outputs_follow_the_contract(full):
    tables = outputs(full)
    for name, columns in GROUPS.items():
        assert tables[name].schema.names == ["master_account", "report_date", "event_timestamp", *columns]
        assert str(tables[name].schema.field("event_timestamp").type) == "timestamp[us, tz=UTC]"
    assert tables["fs_state"].num_rows >= tables["fs_demographic"].num_rows  # young accounts carry state too


# ---- training data ----

@pytest.fixture(scope="module")
def training():
    con = gold_connection()
    build(con, START, dt.date(2026, 1, 30), bootstrap=True)
    con.execute("CREATE TABLE fs AS SELECT * FROM scoring_features")
    build_training.build(con, dt.date(2026, 1, 30), load_settings()["training"]["splits"])
    return con


def test_training_rows_and_labels_equal_the_legacy_job(training):
    legacy = scenario(fixture())
    legacy_normalize(legacy)
    legacy_build(legacy, dt.date(2026, 1, 30))
    columns = COLUMNS + ["loan_label_next", "overdue_eligible", "overdue_label_next_30d", "split"]
    select = ", ".join(f'"{c}"' for c in columns)
    assert (training.execute(f"SELECT {select} FROM candidate ORDER BY 1, 2").fetchall()
            == legacy.execute(f"SELECT {select} FROM candidate ORDER BY 1, 2").fetchall())
    campaign = [r[0] for r in legacy.execute("DESCRIBE campaign_candidate").fetchall()]
    assert [r[0] for r in training.execute("DESCRIBE campaign_candidate").fetchall()] == campaign
    assert (training.execute("SELECT * FROM campaign_candidate ORDER BY campaign_event_id").fetchall()
            == legacy.execute("SELECT * FROM campaign_candidate ORDER BY campaign_event_id").fetchall())
    # gate helpers: same population as the legacy internal columns
    assert (training.execute("SELECT sum(response_14d), sum(no_campaign_14d) FROM candidate").fetchone()
            == legacy.execute("SELECT sum(CAST(baseline_events_14d>0 AS INT)), sum(CAST(campaign_count_14d_internal=0 AS INT)) FROM candidate").fetchone())


def test_scored_rows_use_the_training_overdue_population(training):
    frame = training.execute("SELECT * EXCLUDE(overdue_eligible) FROM candidate").df()
    expected = training.execute("SELECT overdue_eligible FROM candidate").df()["overdue_eligible"]
    assert store.with_overdue_eligible(frame)["overdue_eligible"].tolist() == expected.tolist()
    assert "margin_status" in OVERDUE_ELIGIBLE_SQL and "margin_segment" in OVERDUE_ELIGIBLE_SQL


def test_campaign_rows_for_scoring_equal_the_training_rows(training):
    day = dt.date(2025, 2, 5)
    accounts = training.execute("SELECT * FROM scoring_features WHERE report_date = ?", [day]).df()
    con = connect()
    con.register("x", training.execute("SELECT * FROM customer_campaign").to_arrow_table())
    con.execute("CREATE TABLE customer_campaign AS SELECT * FROM x")
    store.campaign_rows(con, accounts)
    scored = con.execute("SELECT * FROM campaign_rows ORDER BY campaign_event_id").df()
    trained = training.execute("SELECT * EXCLUDE(campaign_response_label_14d, split) FROM campaign_candidate "
                               "WHERE report_date = ? ORDER BY campaign_event_id", [day]).df()
    pd.testing.assert_frame_equal(scored, trained)


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
    seed_from(con, full.execute("SELECT * FROM state_out WHERE report_date = ?", [day - dt.timedelta(days=1)]).to_arrow_table())
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
    margin = broken["fs_margin_balance"].copy()
    margin.loc[margin["report_date"] == covered[1], "margin_status"] = None                # nulls
    broken["fs_margin_balance"] = margin
    result = gate(broken, covered)
    assert "fs_campaign.duplicate_keys" in result[covered[0]]["failed"]
    assert {"fs_margin_balance.null_rate", "domain.margin_status"} <= set(result[covered[1]]["failed"])

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


def test_feature_contract_doc_lists_every_column():
    from features.common import ROOT
    doc = (ROOT / "docs/feature_contract.md").read_text(encoding="utf-8")
    for name, columns in GROUPS.items():
        assert f"`{name}`" in doc
        for column in columns:
            assert f"`{column}`" in doc, column


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
