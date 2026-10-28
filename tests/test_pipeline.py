"""Day 13 batch jobs: the pure parts (joins, segment routing, severity, retrain decision, evaluation status)."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from pipeline.common import assemble, date_range
from pipeline.drift import column_results, severity_for, should_retrain
from pipeline.evaluate import evaluate, status_for
from pipeline.predict import SCHEMA, score_segments, to_arrow

BOUNDS = {"none": 0.0, "medium": 0.20, "high": 0.50}
DAY = dt.date(2026, 1, 30)


class ConstantModel:
    def __init__(self, p):
        self.p = p

    def predict_proba(self, X):
        return np.column_stack([np.full(len(X), 1 - self.p), np.full(len(X), self.p)])


def _snapshot():
    return pd.DataFrame({"master_account": ["a", "b", "c", "d"], "report_date": [DAY] * 4,
                         "segment": ["au", "au", "lu", "nu"], "f1": [1.0, 2.0, 3.0, 4.0]})


# ---- assemble / dates ----

def test_assemble_joins_on_keys_and_drops_event_timestamp():
    a = pd.DataFrame({"master_account": ["x", "y"], "report_date": [DAY, DAY], "event_timestamp": [1, 2], "f1": [1, 2]})
    b = pd.DataFrame({"master_account": ["y", "x"], "report_date": [DAY, DAY], "event_timestamp": [3, 4], "f2": [9, 8]})
    out = assemble([a, b]).sort_values("master_account")
    assert list(out.columns) == ["master_account", "report_date", "f1", "f2"]
    assert out["f2"].tolist() == [8, 9]


def test_assemble_rejects_duplicate_keys():
    a = pd.DataFrame({"master_account": ["x"], "report_date": [DAY], "f1": [1]})
    b = pd.DataFrame({"master_account": ["x", "x"], "report_date": [DAY, DAY], "f2": [1, 2]})
    with pytest.raises(Exception):
        assemble([a, b])


def test_date_range():
    assert date_range(DAY, None) == [DAY]
    assert len(date_range(dt.date(2025, 12, 25), dt.date(2025, 12, 31))) == 7
    with pytest.raises(ValueError):
        date_range(DAY, dt.date(2026, 1, 1))


# ---- predict ----

def test_each_segment_uses_its_own_model_and_version():
    models = {"au": ("m_au", "4", ConstantModel(0.9)), "lu": ("m_lu", "2", ConstantModel(0.1))}
    scored, unscored = score_segments(_snapshot(), models, ["f1"], "segment")
    by_account = scored.set_index("master_account")
    assert by_account.loc["a", "model_version"] == "4" and by_account.loc["a", "score"] == pytest.approx(0.9)
    assert by_account.loc["c", "model_name"] == "m_lu" and by_account.loc["c", "score"] == pytest.approx(0.1)
    assert unscored == ["nu"] and "d" not in by_account.index  # no model -> left unscored, never a wrong model


def test_to_arrow_matches_the_table_schema():
    scored, _ = score_segments(_snapshot(), {"au": ("m", "4", ConstantModel(0.5))}, ["f1"], "segment")
    table = to_arrow(scored, "run1", dt.datetime(2026, 1, 31, 8, 0))
    assert table.schema.equals(SCHEMA) and table.num_rows == 2
    assert set(table.column("feature_run_id").to_pylist()) == {"run1"}


# ---- drift ----

@pytest.mark.parametrize("ratio,expected", [(0.0, "none"), (0.04, "medium"), (0.20, "medium"), (0.21, "high"),
                                            (0.50, "high"), (0.75, "critical")])
def test_severity_bounds(ratio, expected):
    assert severity_for(ratio, BOUNDS) == expected


def test_column_results_distance_vs_p_value():
    report = {"metrics": [
        {"config": {"type": "evidently:metric_v2:DriftedColumnsCount"}, "value": {"count": 1}},
        {"config": {"type": "evidently:metric_v2:ValueDrift", "column": "a", "method": "Wasserstein distance (normed)",
                    "threshold": 0.1}, "value": 0.25},
        {"config": {"type": "evidently:metric_v2:ValueDrift", "column": "b", "method": "Wasserstein distance (normed)",
                    "threshold": 0.1}, "value": 0.05},
        {"config": {"type": "evidently:metric_v2:ValueDrift", "column": "c", "method": "K-S p_value",
                    "threshold": 0.05}, "value": 0.01},
    ]}
    assert {r["column"]: r["drifted"] for r in column_results(report)} == {"a": True, "b": False, "c": True}


def test_retrain_only_on_critical_and_after_cooldown():
    now = dt.datetime(2026, 1, 30, 12)
    assert should_retrain("high", None, now, 7)[0] is False
    assert should_retrain("critical", now - dt.timedelta(days=2), now, 7)[0] is False
    assert should_retrain("critical", now - dt.timedelta(days=8), now, 7)[0] is True
    assert should_retrain("critical", None, now, 7)[0] is True


def test_no_retrain_without_labels_after_production_data_end():
    now = dt.datetime(2026, 1, 30, 12)
    end = dt.date(2025, 12, 31)
    # frozen data: the newest label is the one production was already tested on -> the loop stops
    assert should_retrain("critical", None, now, 7, data_end=end, labeled_until=end)[0] is False
    assert should_retrain("critical", None, now, 7, data_end=end, labeled_until=dt.date(2026, 1, 7))[0] is True
    assert should_retrain("critical", None, now, 7, data_end=None, labeled_until=end)[0] is True


# ---- evaluate ----

@pytest.mark.parametrize("drop,expected", [(None, "NO_LABELS"), (-0.02, "OK"), (0.05, "OK"), (0.06, "WARN"),
                                           (0.11, "RETRAIN")])
def test_status_for(drop, expected):
    assert status_for(drop, 0.05, 0.10) == expected


def test_evaluate_per_model_version():
    joined = pd.DataFrame({
        "segment": ["au"] * 4 + ["lu"] * 2, "model_name": ["m_au"] * 4 + ["m_lu"] * 2,
        "model_version": ["4"] * 4 + ["2"] * 2, "score": [0.9, 0.8, 0.2, 0.1, 0.3, 0.4],
        "y": [1, 1, 0, 0, 0, 0]})
    out = evaluate(joined, {("m_au", "4"): 0.70, ("m_lu", "2"): 0.60}, "y", 0.05, 0.10).set_index("segment")
    assert out.loc["au", "live_auc"] == pytest.approx(1.0) and out.loc["au", "status"] == "OK"
    assert out.loc["lu", "status"] == "NO_LABELS"  # a single class: AUC undefined, never reported as OK
