"""End-to-end Feast test on the Day 4 fixture: publish tables, feast apply, retrieve, check parity."""
import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from scripts.day4_feature_engineering import build, normalize, output_queries, utc_timestamps
from tests.test_day4 import fixture

ROOT = Path(__file__).resolve().parents[1]


class FeastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.run_dir, cls.repo = cls.tmp / "run", cls.tmp / "repo"
        cls.run_dir.mkdir()
        (cls.repo / "data").mkdir(parents=True)
        shutil.copy(ROOT / "feature_repo/feature_store.yaml", cls.repo)
        shutil.copy(ROOT / "feature_repo/definitions.py", cls.repo)
        c = fixture()
        c.execute("UPDATE customer_account SET dormant_start_date='2025-06-01',account_status='DORMANT' WHERE master_account='D'")
        c.execute("""CREATE TABLE customer_campaign(campaign_event_id VARCHAR,campaign_id VARCHAR,master_account VARCHAR,
            sent_at TIMESTAMPTZ,channel VARCHAR,offer_type VARCHAR,interest_rate_offer DOUBLE,status VARCHAR)""")
        c.execute("""INSERT INTO customer_campaign VALUES
            ('E1','MARGIN-01','A',TIMESTAMPTZ '2025-03-10 10:37:00+07','APP','RATE_DISCOUNT',0.07,'DELIVERED'),
            ('E2','MARGIN-01','B',TIMESTAMPTZ '2025-08-05 15:00:00+07','SMS','FEE_WAIVER',0.08,'DELIVERED'),
            ('E3','MARGIN-01','C',TIMESTAMPTZ '2025-02-01 09:00:00+07','EMAIL','LIMIT_BOOST',0.09,'DELIVERED')""")
        normalize(c)
        build(c, date(2026, 1, 30))
        cls.campaign_candidates = c.execute("SELECT count(*) FROM campaign_candidate").fetchone()[0]
        for name, (sql, _) in output_queries().items():
            pq.write_table(utc_timestamps(c.execute(sql).to_arrow_table()), cls.run_dir / f"{name}.parquet")
        c.close()
        os.environ["FEAST_RUN_DIR"] = str(cls.run_dir)
        from scripts.day5_feast_check import apply, run_checks
        cls.store, cls.defs = apply(cls.repo)
        cls.report = run_checks(cls.store, cls.run_dir, accounts=0)

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("FEAST_RUN_DIR", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_all_feast_checks_pass(self):
        failed = [c for c in self.report["checks"] if not c["passed"]]
        self.assertEqual(failed, [])
        names = {c["check"] for c in self.report["checks"]}
        for required in ["loan.parity_with_training_dataset.mismatched_rows", "campaign.parity_with_previous_day_snapshot.mismatched_rows",
                         "latest_day.rows_returned", "ttl.no_stale_values_after_last_snapshot"]:
            self.assertIn(required, names)

    def test_registry_contents(self):
        self.assertEqual(sorted(v.name for v in self.store.list_feature_views()),
                         sorted(["fs_demographic", "fs_trading_behavior", "fs_margin_balance", "fs_asset_balance", "fs_portfolio", "fs_campaign"]))
        self.assertEqual(sorted(s.name for s in self.store.list_feature_services()), ["campaign_response", "loan_propensity", "overdue_risk"])

    def test_services_exclude_unreconciled_and_leaky_features(self):
        from scripts.day5_feast_check import service_features
        self.assertNotIn("portfolio_value", service_features(self.store, "loan_propensity"))
        self.assertFalse({"campaign_count_30d", "has_campaign_history"} & set(service_features(self.store, "campaign_response")))

    def test_campaign_sent_on_first_eligible_day_is_dropped(self):
        # C's send on 2025-02-01 has no 2025-01-31 snapshot (account younger than 30 days).
        self.assertEqual(self.report["entity_rows"]["campaign"], self.campaign_candidates - 1)

    def test_labels_never_in_feature_views(self):
        features = {f.name for v in self.store.list_feature_views() for f in v.features}
        self.assertFalse({"loan_label_next", "overdue_label_next_30d", "overdue_eligible", "campaign_response_label_14d", "split"} & features)


if __name__ == "__main__":
    unittest.main()
