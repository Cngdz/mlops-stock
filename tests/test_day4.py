"""Boundary fixtures independently specify windows, segments and leakage behavior."""
import unittest
from datetime import date
import argparse
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import duckdb
from scripts import day4_feature_engineering as pipeline
from scripts.day4_feature_engineering import build, normalize, validate_sources, weights, write_json, GROUPS


def fixture():
    c = duckdb.connect()
    c.execute("SET TimeZone='Asia/Ho_Chi_Minh'")
    c.execute("""CREATE TABLE customer_account AS SELECT name AS master_account,
        DATE '2025-01-01' AS account_open_date,'ACTIVE' AS account_status,
        NULL::DATE AS account_close_date,NULL::DATE AS dormant_start_date,'LOW' AS risk_profile
        FROM (VALUES ('A'),('B'),('C'),('D')) t(name)""")
    c.execute("""CREATE TABLE margin_balance_daily AS SELECT master_account, d::DATE AS business_date,
        20::BIGINT AS cash_balance,100::BIGINT AS asset_value,
        CASE WHEN master_account='A' AND d::DATE=DATE '2025-02-01' THEN 5 ELSE 0 END::BIGINT AS margin_debt,
        0::BIGINT AS margin_limit FROM customer_account,
        generate_series(DATE '2025-01-01',DATE '2026-01-30',INTERVAL 1 DAY) s(d)""")
    c.execute("""CREATE TABLE stock_transaction(transaction_id VARCHAR,master_account VARCHAR,
        transaction_time VARCHAR,quantity BIGINT,price DOUBLE,trade_value BIGINT,side VARCHAR)""")
    # At D=Feb 1: Jan 2 outside 30d, Jan 3 included; Jan 25 outside 7d,
    # Jan 26 included; Feb 1 23:30 local included, Feb 2 excluded.
    for i, day in enumerate(['2025-01-02','2025-01-03','2025-01-25','2025-01-26','2025-02-01','2025-02-02']):
        c.execute("INSERT INTO stock_transaction VALUES (?,?,?,1,10,10,'BUY')", [str(i),'A',day+'T23:30:00+07:00'])
    c.execute("""CREATE TABLE margin_cash_flow(cash_flow_id VARCHAR,master_account VARCHAR,event_date DATE,
        status VARCHAR,fk_product VARCHAR,fk_cash_flow_type VARCHAR,fk_deliver_type VARCHAR,amount BIGINT)""")
    rows = [('A','2025-01-01','POSTED','BUY_SHARE'),
            ('A','2025-03-03','POSTED','BUY_SHARE'),  # D+30 included
            ('B','2025-02-01','POSTED','BUY_SHARE'),  # today: history, not label
            ('C','2025-03-04','POSTED','BUY_SHARE'),  # D+31 excluded
            ('C','2025-02-02','CANCELLED','BUY_SHARE'),
            ('C','2025-02-03','POSTED','WRONG'),
            ('D','2025-01-01','POSTED','BUY_SHARE')]  # last event outside 30d: lu
    for i,(acct,day,status,deliver) in enumerate(rows):
        c.execute("INSERT INTO margin_cash_flow VALUES (?,?,?,?,'MARGIN_MBS','INTERM_DELIVER',?,10)", [str(i),acct,day,status,deliver])
    return c


class Day4Tests(unittest.TestCase):
    def test_source_schema_errors_are_reported_before_sql(self):
        cases = [
            ("DROP TABLE stock_transaction", "missing_tables", "stock_transaction"),
            ("ALTER TABLE margin_balance_daily DROP COLUMN cash_balance", "missing_columns", "margin_balance_daily"),
            ("ALTER TABLE customer_account ALTER COLUMN account_open_date TYPE VARCHAR", "invalid_column_types", "customer_account"),
            ("ALTER TABLE margin_cash_flow ALTER COLUMN amount TYPE VARCHAR", "invalid_column_types", "margin_cash_flow"),
        ]
        for sql, field, table in cases:
            with self.subTest(sql=sql), fixture() as c:
                c.execute(sql)
                result = validate_sources(c, date(2026, 1, 30))
                self.assertEqual(result["status"], "FAIL")
                self.assertIn(table, result[field])
                self.assertIsNone(result["invalid_transaction_timestamps"])

    def test_missing_balance_history_and_null_open_date_are_rejected(self):
        for sql in ["DELETE FROM margin_balance_daily WHERE master_account='A'",
                    "UPDATE customer_account SET account_open_date=NULL WHERE master_account='A'"]:
            with self.subTest(sql=sql), fixture() as c:
                c.execute(sql)
                result = validate_sources(c, date(2026, 1, 30))
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["accounts_with_incomplete_balance_history"], 1)

    def test_rejected_runs_do_not_publish_artifacts_or_change_pointers(self):
        for broken_schema in [True, False]:
            with self.subTest(broken_schema=broken_schema), tempfile.TemporaryDirectory() as directory, fixture() as c:
                root = Path(directory)
                (root / "scripts").mkdir()
                (root / "scripts/day4_features.sql").write_text(
                    (pipeline.ROOT / "scripts/day4_features.sql").read_text(encoding="utf-8"), encoding="utf-8")
                (root / "data/features").mkdir(parents=True)
                pointer = root / "data/features/current.json"
                pointer.write_text('{"run_id": "previous"}', encoding="utf-8")
                source_pointer = root / "data/source_current.json"
                source_pointer.write_text('{"namespace": "previous"}', encoding="utf-8")
                if broken_schema:
                    c.execute("ALTER TABLE margin_balance_daily DROP COLUMN cash_balance")
                cat = Mock()
                tables = {}
                for name in pipeline.SOURCE_KEYS:
                    table = Mock()
                    table.metadata_location = f"{name}.metadata.json"
                    table.current_snapshot.return_value.snapshot_id = 123
                    table.scan.return_value.to_arrow.return_value = c.execute(f"SELECT * FROM {name}").to_arrow_table()
                    tables[f"test_source.{name}"] = table
                cat.load_table.side_effect = tables.__getitem__
                cat.table_exists.side_effect = lambda name: name in tables
                with patch.object(pipeline, "ROOT", root), patch.object(pipeline, "catalog", return_value=cat):
                    status = pipeline.run(argparse.Namespace(source_namespace="test_source", raw_end=date(2026, 1, 30)))
                self.assertEqual(status, 2)
                self.assertEqual(json.loads(pointer.read_text())["run_id"], "previous")
                self.assertEqual(json.loads(source_pointer.read_text())["namespace"], "previous")
                self.assertFalse((root / "data/features/day4_runs").exists())
                cat.create_namespace.assert_not_called()
                cat.create_table.assert_not_called()
                report_name = "source_validation.json" if broken_schema else "rejected_quality_report.json"
                self.assertEqual(json.loads((root / "data/features" / report_name).read_text())["status"], "FAIL")

    def test_atomic_json_keeps_previous_pointer_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.json"
            write_json(path, {"run_id": "previous"})
            with patch.object(pipeline.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    write_json(path, {"run_id": "next"})
            self.assertEqual(json.loads(path.read_text()), {"run_id": "previous"})
            self.assertEqual(list(Path(directory).iterdir()), [path])
            write_json(path, {"run_id": "next"})
            self.assertEqual(json.loads(path.read_text()), {"run_id": "next"})

    def test_mblink_and_invalid_event_combinations(self):
        c = fixture()
        c.execute("DELETE FROM margin_cash_flow")
        c.execute("""INSERT INTO margin_cash_flow VALUES
            ('1','A','2025-02-02','POSTED','MBLINK','TLO_DELIVER_CASH','BUY',10),
            ('2','B','2025-02-02','POSTED','MBLINK','TLO_DELIVER_CASH','BUY_SHARE',10),
            ('3','C','2025-02-02','POSTED','OTHER','INTERM_DELIVER','BUY_SHARE',10),
            ('4','D','2025-02-02','POSTED','MARGIN_MBS','REPAYMENT','BUY_SHARE',10)""")
        normalize(c)
        build(c,date(2026,1,30))
        self.assertEqual(c.execute("SELECT master_account,loan_label_next FROM candidate WHERE report_date='2025-02-01' ORDER BY 1").fetchall(), [('A',1),('B',0),('C',0),('D',0)])
        c.close()

    def test_legacy_schema_is_not_approved(self):
        c = fixture()
        c.execute("ALTER TABLE margin_cash_flow RENAME COLUMN fk_cash_flow_type TO fk_transaction_type")
        c.execute("ALTER TABLE margin_cash_flow DROP COLUMN fk_deliver_type")
        c.execute("ALTER TABLE margin_cash_flow ADD COLUMN fk_event_type VARCHAR DEFAULT 'DISBURSEMENT'")
        with self.assertRaisesRegex(ValueError, 'Missing cash-flow columns'):
            normalize(c)
        c.close()

    def test_source_validation_rejects_invalid_timestamp(self):
        c = fixture()
        self.assertEqual(validate_sources(c,date(2026,1,30))['status'],'PASS')
        c.execute("UPDATE stock_transaction SET transaction_time='2025-02-01T09.50:00+07:00' WHERE transaction_id='0'")
        result = validate_sources(c,date(2026,1,30))
        self.assertEqual(result['status'],'FAIL')
        self.assertEqual(result['invalid_transaction_timestamps'],1)
        c.close()

    def test_windows_label_segments_and_values(self):
        c = fixture()
        normalize(c)
        build(c,date(2026,1,30))
        actual = c.execute("""SELECT trade_count_7d,trade_count_30d,total_trading_amount_30d,
            active_trading_days_30d,margin_segment,loan_label_next,debt_change_7d,NAV,
            collateral_value,margin_utilization_ratio FROM candidate
            WHERE master_account='A' AND report_date='2025-02-01'""").fetchone()
        self.assertEqual(actual,(2,4,40,4,'au',1,5,115,60,0.0))
        self.assertEqual(c.execute("SELECT master_account,margin_segment,loan_label_next FROM candidate WHERE report_date='2025-02-01' ORDER BY 1").fetchall(),[('A','au',1),('B','au',0),('C','nu',0),('D','lu',0)])
        # embargo rows stay (tagged) so training.train --as-of can re-split by date
        self.assertEqual(c.execute("SELECT count(*) FROM candidate WHERE split IS NULL OR (report_date BETWEEN '2025-07-01' AND '2025-07-30' AND split<>'embargo')").fetchone()[0],0)
        c.close()

    def test_future_changes_do_not_change_features(self):
        columns = ','.join('"'+x+'"' for fields in GROUPS.values() for x in fields)
        results = []
        for mutate in [False,True]:
            c = fixture()
            if mutate:
                c.execute("UPDATE margin_balance_daily SET cash_balance=9999,margin_debt=888 WHERE business_date>'2025-02-01'")
                c.execute("UPDATE stock_transaction SET trade_value=99999 WHERE substr(transaction_time,1,10)>'2025-02-01'")
                c.execute("DELETE FROM margin_cash_flow WHERE event_date>'2025-02-01'")
            normalize(c)
            build(c,date(2026,1,30))
            results.append(c.execute(f"SELECT {columns} FROM candidate WHERE master_account='A' AND report_date='2025-02-01'").fetchone())
            c.close()
        self.assertEqual(*results)

    def test_lifecycle_maturity_and_censoring(self):
        c = fixture()
        c.execute("UPDATE customer_account SET dormant_start_date='2025-02-02',account_status='DORMANT' WHERE master_account='A'")
        c.execute("UPDATE customer_account SET account_open_date='2025-01-15' WHERE master_account='B'")
        normalize(c)
        build(c,date(2025,3,3))
        self.assertEqual(c.execute("SELECT count(*) FROM candidate WHERE master_account='B' OR report_date>'2025-02-01'").fetchone()[0],0)
        self.assertEqual(c.execute("SELECT count(*) FROM candidate WHERE master_account='A'").fetchone()[0],1)
        c.close()

    def test_weights_ignore_validation_test(self):
        c = duckdb.connect()
        c.execute("CREATE TABLE candidate AS SELECT * FROM (VALUES ('train','nu',0),('train','nu',0),('train','nu',0),('train','nu',1),('test','nu',1)) t(split,margin_segment,loan_label_next)")
        result = weights(c,False)
        self.assertEqual(result['segments']['nu']['weights'],{'0':2/3,'1':2.0})
        self.assertIsNone(result['segments']['lu']['weights'])
        self.assertFalse(result['approved_for_training'])
        c.close()

    def test_overdue_label_is_new_overdue_among_eligible_rows(self):
        c = fixture()
        c.execute("ALTER TABLE margin_balance_daily ADD COLUMN margin_status VARCHAR DEFAULT 'NO_MARGIN'")
        c.execute("UPDATE margin_balance_daily SET margin_status='OVERDUE' WHERE master_account='A' AND business_date='2025-02-01'")  # already overdue at D
        c.execute("UPDATE margin_balance_daily SET margin_status='OVERDUE' WHERE master_account='B' AND business_date='2025-03-03'")  # D+30
        c.execute("UPDATE margin_balance_daily SET margin_status='OVERDUE' WHERE master_account='C' AND business_date='2025-03-03'")  # no debt/history: not a candidate
        c.execute("UPDATE margin_balance_daily SET margin_status='OVERDUE' WHERE master_account='D' AND business_date='2025-03-04'")  # D+31
        normalize(c)
        build(c, date(2026, 1, 30))
        rows = c.execute("SELECT master_account,overdue_eligible,overdue_label_next_30d FROM candidate WHERE report_date='2025-02-01' ORDER BY 1").fetchall()
        self.assertEqual(rows, [('A', 0, None), ('B', 1, 1), ('C', 0, None), ('D', 1, 0)])
        c.close()

    def test_over_limit_features_use_calendar_days_up_to_d(self):
        c = fixture()
        c.execute("UPDATE margin_balance_daily SET margin_debt=10,margin_limit=5 WHERE master_account='A' AND business_date BETWEEN '2025-01-30' AND '2025-02-01'")
        c.execute("UPDATE margin_balance_daily SET margin_debt=10,margin_limit=5 WHERE master_account='A' AND business_date>'2025-02-01'")
        normalize(c)
        build(c, date(2026, 1, 30))
        self.assertEqual(c.execute("SELECT over_limit_streak,over_limit_days_30d FROM candidate WHERE master_account='A' AND report_date='2025-02-01'").fetchone(), (3, 3))
        c.close()

    def campaign_fixture(self):
        c = fixture()
        c.execute("""CREATE TABLE customer_campaign(campaign_event_id VARCHAR,campaign_id VARCHAR,master_account VARCHAR,
            sent_at TIMESTAMPTZ,channel VARCHAR,offer_type VARCHAR,interest_rate_offer DOUBLE,status VARCHAR)""")
        c.execute("DELETE FROM margin_cash_flow WHERE master_account IN ('B','C')")
        c.execute("""INSERT INTO margin_cash_flow VALUES
            ('b1','B','2025-02-01','POSTED','MARGIN_MBS','INTERM_DELIVER','BUY_SHARE',10),
            ('b2','B','2025-02-15','POSTED','MARGIN_MBS','INTERM_DELIVER','BUY_SHARE',10),
            ('c1','C','2025-02-16','POSTED','MARGIN_MBS','INTERM_DELIVER','BUY_SHARE',10)""")
        return c

    def test_campaign_response_window_and_exclusions(self):
        c = self.campaign_fixture()
        for event, account, status in [('E1','A','DELIVERED'),('E2','B','DELIVERED'),('E3','C','DELIVERED'),('E4','D','FAILED')]:
            c.execute("INSERT INTO customer_campaign VALUES (?,'MARGIN-01',?,TIMESTAMPTZ '2025-02-01 10:00:00+07','APP','RATE_DISCOUNT',0.07,?)", [event, account, status])
        normalize(c)
        build(c, date(2026, 1, 30))
        rows = c.execute("SELECT master_account,campaign_response_label_14d FROM campaign_candidate ORDER BY 1").fetchall()
        # A: no event in D+1..D+14. B: event on D is ignored, D+14 counts. C: D+15 is outside. D: FAILED is excluded.
        self.assertEqual(rows, [('A', 0), ('B', 1), ('C', 0)])
        c.close()

    def test_campaign_history_excludes_the_current_send_and_inactive_accounts_are_dropped(self):
        c = self.campaign_fixture()
        c.execute("UPDATE customer_account SET dormant_start_date='2025-02-01',account_status='DORMANT' WHERE master_account='D'")
        c.execute("INSERT INTO customer_campaign VALUES ('P1','MARGIN-01','A',TIMESTAMPTZ '2025-01-20 10:00:00+07','SMS','FEE_WAIVER',0.08,'DELIVERED')")
        c.execute("INSERT INTO customer_campaign VALUES ('P2','MARGIN-01','A',TIMESTAMPTZ '2025-02-05 10:00:00+07','APP','LIMIT_BOOST',0.09,'DELIVERED')")
        c.execute("INSERT INTO customer_campaign VALUES ('P3','MARGIN-01','D',TIMESTAMPTZ '2025-02-01 11:00:00+07','APP','LIMIT_BOOST',0.09,'DELIVERED')")
        normalize(c)
        build(c, date(2026, 1, 30))
        self.assertEqual(c.execute("SELECT count(*) FROM campaign_candidate WHERE master_account='D'").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT campaign_count_30d,days_since_last_campaign,has_campaign_history FROM campaign_candidate WHERE campaign_event_id='P2'").fetchone(), (1, 16, 1))
        self.assertEqual(c.execute("SELECT count(*) FROM campaign_candidate WHERE campaign_event_id='P1'").fetchone()[0], 0)  # before 2025-02-01
        c.close()


    def test_scoring_features_cover_latest_and_embargo_days_without_labels(self):
        c = fixture()
        normalize(c)
        build(c, date(2026, 1, 30))
        cols = {r[0] for r in c.execute("DESCRIBE scoring_features").fetchall()}
        self.assertFalse({"loan_label_next", "overdue_label_next_30d", "overdue_eligible", "split"} & cols)
        self.assertEqual(c.execute("SELECT max(report_date) FROM scoring_features").fetchone()[0], date(2026, 1, 30))
        # Embargo day: scoring rows and training rows tagged 'embargo'. Inside the last 30 days: no label, no training row.
        for day, training_rows in [("2025-07-15", 4), ("2026-01-20", 0)]:
            self.assertEqual(c.execute("SELECT count(*) FROM scoring_features WHERE report_date=?", [day]).fetchone()[0], 4)
            self.assertEqual(c.execute("SELECT count(*) FROM candidate WHERE report_date=?", [day]).fetchone()[0], training_rows)
        self.assertEqual({r[0] for r in c.execute("SELECT split FROM candidate WHERE report_date='2025-07-15'").fetchall()},
                         {"embargo"})
        c.close()

    def test_training_features_equal_scoring_features_for_the_same_key(self):
        c = fixture()
        normalize(c)
        build(c, date(2026, 1, 30))
        feature_cols = [f for values in GROUPS.values() for f in values]
        mismatch = c.execute("SELECT count(*) FROM candidate t JOIN scoring_features f USING(master_account,report_date) WHERE "
                             + " OR ".join(f't."{k}" IS DISTINCT FROM f."{k}"' for k in feature_cols)).fetchone()[0]
        missing = c.execute("SELECT count(*) FROM candidate t ANTI JOIN scoring_features f USING(master_account,report_date)").fetchone()[0]
        self.assertEqual((mismatch, missing), (0, 0))
        self.assertGreater(c.execute("SELECT count(*) FROM scoring_features").fetchone()[0], c.execute("SELECT count(*) FROM candidate").fetchone()[0])
        c.close()

    def test_scoring_features_ignore_data_after_d(self):
        # Data up to T gives features at T, while labels only exist up to T-30.
        c = fixture()
        normalize(c)
        build(c, date(2025, 3, 3))
        self.assertEqual(c.execute("SELECT max(report_date) FROM scoring_features").fetchone()[0], date(2025, 3, 3))
        self.assertEqual(c.execute("SELECT max(report_date) FROM candidate").fetchone()[0], date(2025, 2, 1))
        c.close()


if __name__ == '__main__':
    unittest.main()
