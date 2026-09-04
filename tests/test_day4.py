"""Boundary fixtures independently specify windows, segments and leakage behavior."""
import unittest
from datetime import date
import duckdb
from scripts.day4_feature_engineering import build, normalize, validate_sources, weights, GROUPS


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
        self.assertEqual(c.execute("SELECT count(*) FROM candidate WHERE split IS NULL OR report_date BETWEEN '2025-07-01' AND '2025-07-30'").fetchone()[0],0)
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


if __name__ == '__main__':
    unittest.main()
