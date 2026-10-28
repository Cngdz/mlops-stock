"""Day 7 promotion gate. Pure logic: no MLflow, so every rule is unit-tested.

A challenger may replace @production only if EVERY segment of the use case passes:
    new_auc    >= max(prod_auc - auc_tolerance, auc_floor)   (defaults 0.03 and 0.75)
    new_recall >= prod_recall - recall_tolerance   (default 0.05)
Both are measured on the same test rows; recall at the SAME alert rate (registry.compare_with_champion).
The floor stops a slow slide: each version may lose up to auc_tolerance against the previous one, but never fall below it.
A segment with no @production model yet is a baseline: its test ROC-AUC must reach the same floor.
Passing the gate only makes a version ELIGIBLE; @production is set by the approval step (promote.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from training.config import CONFIG_PATH

EPS = 1e-9  # 0.80 - 0.03 is 0.7700000000000001 in floats; a challenger exactly on the boundary passes


@dataclass(frozen=True)
class GateConfig:
    auc_tolerance: float = 0.03
    recall_tolerance: float = 0.05
    baseline_auc_floor: float = 0.75


@dataclass
class GateDecision:
    passed: bool
    status: str                                   # PASS | BASELINE_PASS | FAIL
    reasons: dict[str, str] = field(default_factory=dict)


def load_gate_config(path: Path = CONFIG_PATH) -> GateConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return GateConfig(**raw.get("promotion", {}))


def check_segment(new: dict, current: dict | None, cfg: GateConfig) -> tuple[bool, str]:
    """new/current: {"roc_auc": float, "recall": float}; current None = no @production yet."""
    if current is None:
        ok = new["roc_auc"] + EPS >= cfg.baseline_auc_floor
        return ok, f"baseline auc {new['roc_auc']:.4f} {'>=' if ok else '<'} floor {cfg.baseline_auc_floor}"
    required = max(current["roc_auc"] - cfg.auc_tolerance, cfg.baseline_auc_floor)
    auc_ok = new["roc_auc"] + EPS >= required
    recall_ok = new["recall"] + EPS >= current["recall"] - cfg.recall_tolerance
    reason = (f"auc {new['roc_auc']:.4f} vs prod {current['roc_auc']:.4f}, need {required:.4f} ({'ok' if auc_ok else 'FAIL'}), "
              f"recall {new['recall']:.4f} vs prod {current['recall']:.4f} ({'ok' if recall_ok else 'FAIL'})")
    return auc_ok and recall_ok, reason


def evaluate_gate(new_metrics: dict[str, dict], current_metrics: dict[str, dict | None],
                  cfg: GateConfig = GateConfig()) -> GateDecision:
    """All-or-nothing over the segments in new_metrics."""
    reasons, results = {}, []
    for segment, new in new_metrics.items():
        ok, reasons[segment] = check_segment(new, current_metrics.get(segment), cfg)
        results.append(ok)
    passed = bool(results) and all(results)
    baseline = all(current_metrics.get(s) is None for s in new_metrics)
    status = "FAIL" if not passed else ("BASELINE_PASS" if baseline else "PASS")
    return GateDecision(passed, status, reasons)


def should_promote(new_metrics: dict[str, dict], current_prod_metrics: dict[str, dict | None],
                   cfg: GateConfig = GateConfig()) -> bool:
    return evaluate_gate(new_metrics, current_prod_metrics, cfg).passed
