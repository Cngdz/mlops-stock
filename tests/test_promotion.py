"""Day 7: promotion gate rules, approval checks and the backtest train cutoff. No MLflow server needed."""
import unittest
from types import SimpleNamespace

import pandas as pd

from training.data import cut_train
from training.evaluate import recall_at_alert_rate
from training.promote import check
from training.promotion import GateConfig, evaluate_gate, load_gate_config, should_promote

PROD = {"nu": {"roc_auc": 0.90, "recall": 0.60}, "lu": {"roc_auc": 0.85, "recall": 0.50},
        "au": {"roc_auc": 0.80, "recall": 0.55}}  # all well above the 0.75 floor, so the relative rule decides


def shifted(auc=0.0, recall=0.0, segments=("nu", "lu", "au")):
    return {s: {"roc_auc": PROD[s]["roc_auc"] + (auc if s in segments else 0),
                "recall": PROD[s]["recall"] + (recall if s in segments else 0)} for s in PROD}


class GateTests(unittest.TestCase):
    def test_all_three_segments_pass(self):
        self.assertTrue(should_promote(shifted(auc=0.01, recall=-0.02), PROD))

    def test_one_segment_failing_blocks_all(self):
        new = shifted(auc=-0.05, segments=("lu",))
        decision = evaluate_gate(new, PROD)
        self.assertFalse(decision.passed)
        self.assertEqual(decision.status, "FAIL")
        self.assertIn("FAIL", decision.reasons["lu"])
        self.assertNotIn("FAIL", decision.reasons["nu"])

    def test_recall_drop_alone_fails(self):
        self.assertFalse(should_promote(shifted(recall=-0.06, segments=("au",)), PROD))

    def test_exact_boundary_passes(self):
        # 0.90 - 0.03 and 0.60 - 0.05 are not exact in binary floats; the gate must still accept them
        self.assertTrue(should_promote(shifted(auc=-0.03, recall=-0.05), PROD))

    def test_just_beyond_boundary_fails(self):
        self.assertFalse(should_promote(shifted(auc=-0.0301), PROD))
        self.assertFalse(should_promote(shifted(recall=-0.0501), PROD))

    def test_baseline_uses_auc_floor(self):
        none = {s: None for s in PROD}
        decision = evaluate_gate(PROD, none, GateConfig(baseline_auc_floor=0.55))
        self.assertEqual(decision.status, "BASELINE_PASS")
        self.assertFalse(should_promote({"nu": {"roc_auc": 0.54, "recall": 0.9}}, {"nu": None}))

    def test_floor_stops_slow_slide_below_it(self):
        # champion at 0.77: the tolerance alone would accept 0.74, the 0.75 floor must not
        cfg = GateConfig(auc_tolerance=0.03, recall_tolerance=0.05, baseline_auc_floor=0.75)
        champion = {"nu": {"roc_auc": 0.77, "recall": 0.60}}
        self.assertTrue(should_promote({"nu": {"roc_auc": 0.75, "recall": 0.60}}, champion, cfg))
        self.assertFalse(should_promote({"nu": {"roc_auc": 0.74, "recall": 0.60}}, champion, cfg))
        # a strong champion keeps the relative rule: 0.90 - 0.03 = 0.87 is the bar, not the floor
        strong = {"nu": {"roc_auc": 0.90, "recall": 0.60}}
        self.assertFalse(should_promote({"nu": {"roc_auc": 0.86, "recall": 0.60}}, strong, cfg))

    def test_new_segment_next_to_existing_production(self):
        decision = evaluate_gate(PROD, {"nu": PROD["nu"], "lu": PROD["lu"], "au": None})
        self.assertEqual(decision.status, "PASS")

    def test_no_segments_never_passes(self):
        self.assertFalse(should_promote({}, {}))

    def test_repo_config(self):
        self.assertEqual(load_gate_config(), GateConfig(0.03, 0.05, 0.75))


def version(v, run="r1", gate="PASS"):
    return SimpleNamespace(version=v, tags={"train_run_id": run, "promotion_gate": gate, "gate_reason": "x"})


class ApprovalTests(unittest.TestCase):
    def test_gate_pass_from_one_run_is_approvable(self):
        rows = [{"name": "m_nu", "staging": version("2")}, {"name": "m_au", "staging": version("3", gate="BASELINE_PASS")}]
        self.assertEqual(check(rows), [])

    def test_failed_gate_refused(self):
        rows = [{"name": "m_nu", "staging": version("2")}, {"name": "m_au", "staging": version("3", gate="FAIL")}]
        self.assertEqual(len(check(rows)), 1)

    def test_mixed_training_runs_refused(self):
        rows = [{"name": "m_nu", "staging": version("2", run="r1")}, {"name": "m_au", "staging": version("3", run="r2")}]
        self.assertEqual(len(check(rows)), 1)


class AlertRateTests(unittest.TestCase):
    y = [1, 0, 1, 0, 0, 1, 0, 0, 0, 0]

    def test_recall_at_alert_rate(self):
        proba = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]  # positives ranked 1st, 3rd, 6th
        self.assertAlmostEqual(recall_at_alert_rate(self.y, proba, 0.3), 2 / 3)  # top 3 alerts
        self.assertAlmostEqual(recall_at_alert_rate(self.y, proba, 0.6), 1.0)
        self.assertEqual(recall_at_alert_rate(self.y, proba, 0.0), 0.0)

    def test_independent_of_each_models_own_threshold(self):
        # same ranking, different probability scale -> same recall at the same alert rate
        proba = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
        squashed = [p / 10 for p in proba]
        self.assertEqual(recall_at_alert_rate(self.y, proba, 0.3), recall_at_alert_rate(self.y, squashed, 0.3))


class CutoffTests(unittest.TestCase):
    def test_only_train_window_is_cut(self):
        df = pd.DataFrame({
            "split": ["train"] * 4 + ["validation", "test"],
            "report_date": ["2025-02-01", "2025-05-01", "2025-06-10", "2025-06-30", "2025-07-31", "2025-10-31"]})
        cut = cut_train(df, 40)  # train max 06-30 -> keep <= 05-21
        self.assertEqual(cut["report_date"].tolist(), ["2025-02-01", "2025-05-01", "2025-07-31", "2025-10-31"])
        self.assertTrue(cut_train(df, 0).equals(df))
        with self.assertRaises(ValueError):
            cut_train(df, 400)


if __name__ == "__main__":
    unittest.main()
