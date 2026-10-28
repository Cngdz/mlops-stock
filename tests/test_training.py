"""Day 6 training: leakage guard, run/split checks, and an end-to-end run on a synthetic Day 4 run."""
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from training.config import load_usecases, validate
from training.data import balanced_weights, check_run, check_splits, label_end, resplit, split_windows
from training.train import run

SPLIT_DAYS = {"train": "2025-02-01", "validation": "2025-04-01", "test": "2025-06-01"}


def synthetic(uc, rows_per_split, rng, extra=None):
    """Rows for every split/segment; the label depends on two features so models can learn."""
    parts = []
    segments = uc.segments or ["nu", "lu", "au"]
    for split, start in SPLIT_DAYS.items():
        n = rows_per_split
        df = pd.DataFrame({f: rng.normal(size=n) for f in uc.numeric_features})
        for col, values in (extra or {}).items():
            df[col] = rng.choice(values, size=n)
        df["margin_segment"] = rng.choice(segments, size=n)
        logit = 1.5 * df[uc.numeric_features[0]] - 1.0 * df[uc.numeric_features[1]]
        df[uc.label] = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
        df["split"] = split
        df["report_date"] = (pd.Timestamp(start) + pd.to_timedelta(rng.integers(0, 30, n), "D")).strftime("%Y-%m-%d")
        df["master_account"] = [f"{i:010d}" for i in range(n)]
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


def write_fixture_run(run_dir: Path, rng) -> None:
    ucs = load_usecases()
    loan = synthetic(ucs["loan_propensity"], 3000, rng)
    features = ucs["overdue_risk"].numeric_features
    logit = 1.5 * loan[features[0]] - 1.0 * loan[features[1]]
    loan["overdue_label_next_30d"] = (rng.random(len(loan)) < 1 / (1 + np.exp(-logit))).astype(float)
    loan["overdue_eligible"] = (loan["margin_segment"] != "nu").astype(int)
    loan.loc[loan["overdue_eligible"] == 0, "overdue_label_next_30d"] = np.nan
    loan.to_parquet(run_dir / "training_dataset.parquet")
    campaign = synthetic(ucs["campaign_response"], 3000, rng,
                         extra={"channel": ["APP", "SMS", "EMAIL"], "offer_type": ["FEE_WAIVER", "LIMIT_BOOST"]})
    campaign.to_parquet(run_dir / "campaign_training_dataset.parquet")
    balanced = {"weights": {"0": 0.7, "1": 1.8}}
    (run_dir / "class_weights.json").write_text(json.dumps({
        "approved_for_training": True,
        "segments": {s: balanced for s in ("nu", "lu", "au")},
        "overdue_risk": {"segments": {s: balanced for s in ("lu", "au")}},
        "campaign_response": balanced,
    }))
    (run_dir / "quality_report.json").write_text(json.dumps(
        {"status": "PASS", "run_id": "fixture", "feature_contract": "day4-v5"}))


class ConfigTests(unittest.TestCase):
    def test_repo_config_is_valid(self):
        ucs = load_usecases()
        self.assertEqual(set(ucs), {"loan_propensity", "overdue_risk", "campaign_response"})
        self.assertNotIn("portfolio_value", ucs["loan_propensity"].features)

    def test_label_in_allowlist_is_rejected(self):
        uc = load_usecases()["loan_propensity"]
        for leak in ("loan_label_next", "overdue_label_next_30d", "split", "overdue_eligible", "report_date"):
            with self.assertRaises(ValueError, msg=leak):
                validate(replace(uc, numeric_features=uc.numeric_features + [leak]))

    def test_segment_column_cannot_be_a_feature_of_a_segment_model(self):
        uc = load_usecases()["loan_propensity"]
        with self.assertRaises(ValueError):
            validate(replace(uc, categorical_features=["margin_segment"]))


class DataTests(unittest.TestCase):
    def test_overlapping_splits_are_rejected(self):
        df = pd.DataFrame({"split": ["train", "validation", "test"],
                           "report_date": ["2025-03-01", "2025-03-01", "2025-05-01"]})
        with self.assertRaises(ValueError):
            check_splits(df, "x")

    def test_failed_quality_gate_blocks_training(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        (tmp / "quality_report.json").write_text(json.dumps({"status": "FAIL"}))
        (tmp / "class_weights.json").write_text(json.dumps({"approved_for_training": True}))
        with self.assertRaises(RuntimeError):
            check_run(tmp)


class SlidingSplitTests(unittest.TestCase):
    def test_windows_at_default_as_of_match_day4_split(self):
        uc = load_usecases()["loan_propensity"]
        end = label_end(pd.Series(["2025-12-31"]), pd.Timestamp("2026-01-30"), uc.label_horizon_days)
        w = split_windows(end, **uc.windows)
        ts = pd.Timestamp
        self.assertEqual(w["test"], (ts("2025-10-31"), ts("2025-12-31")))
        self.assertEqual(w["validation"], (ts("2025-07-31"), ts("2025-09-30")))
        self.assertEqual(w["train"], (None, ts("2025-06-30")))

    def test_windows_slide_with_as_of_and_drop_unlabeled_and_embargo_rows(self):
        uc = replace(load_usecases()["loan_propensity"], windows={"test_days": 10, "validation_days": 10,
                                                                  "embargo_days": 5})
        days = pd.date_range("2025-01-01", "2025-03-31").strftime("%Y-%m-%d")
        df = pd.DataFrame({"report_date": days, "split": "train"})
        out = resplit(df, uc, "2025-03-01")  # labels known up to 2025-01-30
        dates = pd.to_datetime(out["report_date"])
        self.assertEqual(dates.max(), pd.Timestamp("2025-01-30"))
        self.assertEqual(out.groupby("split")["report_date"].agg(["min", "max"]).loc["test"].tolist(),
                         ["2025-01-21", "2025-01-30"])
        self.assertEqual(len(out), 30 - 2 * 5)  # 30 labeled days minus two 5-day embargoes
        later = resplit(df, uc, "2025-03-31")  # a month later: every window moves a month forward
        self.assertEqual(later.loc[later["split"] == "test", "report_date"].max(), "2025-03-01")
        self.assertEqual(later.loc[later["split"] == "train", "report_date"].max(), "2025-01-30")

    def test_balanced_weights(self):
        self.assertEqual(balanced_weights(np.array([0, 0, 0, 1])), {0: 4 / 6, 1: 2.0})


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.run_dir = cls.tmp / "run"
        cls.run_dir.mkdir()
        write_fixture_run(cls.run_dir, np.random.default_rng(0))
        cls.out_a = run(run_dir=cls.run_dir, out_root=cls.tmp / "a")
        cls.out_b = run(run_dir=cls.run_dir, out_root=cls.tmp / "b")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_expected_models_written(self):
        expected = {"loan_propensity": {"nu", "lu", "au"}, "overdue_risk": {"lu", "au"}, "campaign_response": {"all"}}
        for usecase, segments in expected.items():
            self.assertEqual({p.name for p in (self.out_a / usecase).iterdir()}, segments)
            for segment in segments:
                for f in ("lr.joblib", "lgbm.joblib", "metrics.json"):
                    self.assertTrue((self.out_a / usecase / segment / f).exists(), f"{usecase}/{segment}/{f}")

    def test_metrics_and_lineage(self):
        m = json.loads((self.out_a / "overdue_risk/au/metrics.json").read_text())
        self.assertEqual(m["feature_run_id"], "fixture")
        self.assertIn(m["selected"], {"lr", "lgbm"})
        for model in ("lr", "lgbm"):
            self.assertGreater(m["models"][model]["test"]["roc_auc"], 0.7)  # signal is learnable
            self.assertTrue(0 < m["models"][model]["threshold"] < 1)

    def test_artifact_scores_raw_feature_vector(self):
        m = json.loads((self.out_a / "campaign_response/all/metrics.json").read_text())
        pipe = joblib.load(self.out_a / "campaign_response/all/lgbm.joblib")
        row = pd.read_parquet(self.run_dir / "campaign_training_dataset.parquet").head(3)[m["features"]]
        proba = pipe.predict_proba(row)[:, 1]
        self.assertEqual(proba.shape, (3,))

    def test_reproducible(self):
        for path in self.out_a.glob("*/*/metrics.json"):
            a = json.loads(path.read_text())["models"]
            b = json.loads((self.out_b / path.relative_to(self.out_a)).read_text())["models"]
            for model in ("lr", "lgbm"):
                a[model].pop("fit_seconds"), b[model].pop("fit_seconds")
            self.assertEqual(a, b, str(path))


if __name__ == "__main__":
    unittest.main()
