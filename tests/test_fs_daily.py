"""Daily feature store: full read of Gold, partition-per-day write, atomic replace, retention, completion marker."""
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq

from pipeline import common
from scripts import fs_daily
from scripts.day4_feature_engineering import GROUPS, build, normalize
from test_day4 import fixture

T = date(2026, 1, 30)


def built(raw_end=T):
    con = fixture()
    normalize(con)
    build(con, raw_end)
    return con


class DailyStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_backfill_writes_one_partition_per_table_and_day_with_marker(self):
        written = fs_daily.write_partitions(built(), date(2026, 1, 28), T, self.root)
        self.assertEqual(sorted(written), ["2026-01-28", "2026-01-29", "2026-01-30"])
        for day in (date(2026, 1, 28), date(2026, 1, 29), T):
            self.assertTrue(common.fs_marker(day, self.root).exists())
            for table in GROUPS:
                path = common.fs_partition(table, day, self.root)
                self.assertEqual(pq.read_table(path).num_rows, 4)  # accounts A-D
                self.assertEqual(set(pq.read_table(path).column("report_date").to_pylist()), {day})

    def test_rerunning_a_day_replaces_only_that_partition(self):
        con = built()
        fs_daily.write_partitions(con, date(2026, 1, 28), T, self.root)
        other, target = (common.fs_partition("fs_margin_balance", d, self.root) for d in (date(2026, 1, 28), T))
        before_other, before_target = other.stat().st_mtime_ns, target.stat().st_mtime_ns
        time.sleep(0.05)
        fs_daily.write_partitions(con, T, T, self.root)
        self.assertEqual(other.stat().st_mtime_ns, before_other)
        self.assertGreater(target.stat().st_mtime_ns, before_target)

    def test_old_day_recomputed_after_newer_data_arrived_gives_same_values(self):
        # Gold already holds days up to the 30th; computing the 28th must see nothing after the 28th
        features = ", ".join(f for fields in GROUPS.values() for f in fields)
        query = f"SELECT master_account, {features} FROM scoring_features WHERE report_date = DATE '2026-01-28' ORDER BY 1"
        self.assertEqual(built(date(2026, 1, 28)).execute(query).fetchall(), built(T).execute(query).fetchall())

    def test_retention_drops_partitions_and_markers_older_than_cutoff(self):
        fs_daily.write_partitions(built(), date(2026, 1, 28), T, self.root)
        removed = fs_daily.drop_old_partitions(T, retention_days=1, root=self.root)  # cutoff = 2026-01-29
        self.assertEqual(removed, ["2026-01-28"])
        self.assertFalse(common.fs_partition("fs_campaign", date(2026, 1, 28), self.root).parent.exists())
        self.assertFalse(common.fs_marker(date(2026, 1, 28), self.root).exists())
        self.assertTrue(common.fs_partition("fs_campaign", date(2026, 1, 29), self.root).exists())

    def test_quality_gate_flags_nulls_and_missing_days(self):
        con = built()
        self.assertEqual(fs_daily.check_partitions(con, date(2026, 1, 28), T), {})
        con.execute("UPDATE scoring_features SET trade_count_7d = NULL "
                    "WHERE report_date = DATE '2026-01-30' AND master_account = 'A'")
        self.assertEqual(fs_daily.check_partitions(con, date(2026, 1, 28), T), {"null_key_or_feature": 1})
        self.assertEqual(fs_daily.check_partitions(con, T, date(2026, 2, 2)).get("missing_days"), 3)

    def test_read_snapshot_uses_complete_partitions_only(self):
        fs_daily.write_partitions(built(), T, T, self.root)
        with patch.object(common, "FS_ROOT", self.root):
            snapshot = common.read_snapshot(self.root / "no_such_run", T)  # no run dir needed
            self.assertEqual(len(snapshot), 4)
            self.assertIn("trade_count_7d", snapshot.columns)
            common.fs_marker(T, self.root).unlink()  # data written but day not marked complete
            with self.assertRaisesRegex(ValueError, "not marked complete"):
                common.read_snapshot(self.root / "no_such_run", T)


if __name__ == "__main__":
    unittest.main()
