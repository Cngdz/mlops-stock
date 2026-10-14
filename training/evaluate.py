"""Metrics and threshold choice. Thresholds come from validation only; test is scored once."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score)


def choose_threshold(y, proba, rule: dict) -> float:
    precision, recall, thresholds = precision_recall_curve(y, proba)
    precision, recall = precision[:-1], recall[:-1]  # the last point has no threshold
    if rule["rule"] == "max_f1":
        f1 = np.divide(2 * precision * recall, precision + recall,
                       out=np.zeros_like(precision), where=(precision + recall) > 0)
        return float(thresholds[int(np.argmax(f1))])
    # min_recall: the highest threshold (best precision) that still reaches the recall floor
    ok = np.flatnonzero(recall >= rule["value"])
    return float(thresholds[ok[-1]]) if len(ok) else float(thresholds[0])


def recall_at_alert_rate(y, proba, alert_rate: float) -> float:
    """Recall when the model flags the top `alert_rate` share of rows. Lets two models with different
    thresholds be compared at the same operating point (same number of alerts)."""
    y = np.asarray(y)
    k = int(round(alert_rate * len(y)))
    if k == 0 or y.sum() == 0:
        return 0.0
    top = np.argsort(-np.asarray(proba), kind="stable")[:k]
    return float(y[top].sum() / y.sum())


def metrics(y, proba, threshold: float) -> dict:
    pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "rows": int(len(y)), "positives": int(np.sum(y)), "positive_rate": float(np.mean(y)),
        "roc_auc": float(roc_auc_score(y, proba)), "pr_auc": float(average_precision_score(y, proba)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }
