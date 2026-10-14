"""Day 6: train LR baseline + LightGBM per (use case, segment) on an approved Day 4 run.

Usage:  python -m training.train                                 # all use cases, run in current.json
        python -m training.train --usecase loan_propensity --run-dir data/features/day4_runs/<id>

Writes data/models/day6_runs/<train_run_id>/<usecase>/<segment>/{lr,lgbm}.joblib + metrics.json,
and summary.json with lineage. Model choice (higher validation ROC-AUC) and threshold use validation
only; test is scored once for the report. Day 7 consumes SegmentResult to log to MLflow.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import joblib
from sklearn.pipeline import Pipeline

from training.config import UseCase, load_usecases
from training.data import ROOT, SegmentData, check_run, iter_segments, load_frame, resolve_run_dir
from training.evaluate import choose_threshold, metrics
from training.models import fit_lgbm, fit_lr

OUT_ROOT = ROOT / "data/models/day6_runs"


@dataclass
class SegmentResult:
    usecase: str
    segment: str
    models: dict[str, Pipeline]
    metrics: dict[str, dict]      # model name -> {threshold, validation, test, ...}
    selected: str


def train_segment(uc: UseCase, data: SegmentData) -> SegmentResult:
    X, y = data.X, data.y
    models, results = {}, {}
    for name in ("lr", "lgbm"):
        start = time.perf_counter()
        if name == "lr":
            pipe = fit_lr(uc, X["train"], y["train"], data.w_train)
        else:
            pipe = fit_lgbm(uc, X["train"], y["train"], data.w_train, X["validation"], y["validation"])
        fit_seconds = time.perf_counter() - start
        proba = {s: pipe.predict_proba(X[s])[:, 1] for s in ("validation", "test")}
        threshold = choose_threshold(y["validation"], proba["validation"], uc.threshold)
        results[name] = {
            "threshold": threshold, "threshold_rule": uc.threshold, "fit_seconds": round(fit_seconds, 2),
            "train_rows": int(len(y["train"])),
            "validation": metrics(y["validation"], proba["validation"], threshold),
            "test": metrics(y["test"], proba["test"], threshold),
        }
        if name == "lgbm":
            results[name]["best_iteration"] = int(pipe.named_steps["model"].best_iteration_)
        models[name] = pipe
    selected = max(results, key=lambda n: results[n]["validation"]["roc_auc"])
    return SegmentResult(uc.name, data.segment, models, results, selected)


def git_commit() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_segment(out: Path, uc: UseCase, result: SegmentResult, lineage: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, pipe in result.models.items():
        joblib.dump(pipe, out / f"{name}.joblib")
    (out / "metrics.json").write_text(json.dumps({
        "usecase": uc.name, "segment": result.segment, "label": uc.label, "selected": result.selected,
        "features": uc.features, "feature_hash": uc.feature_hash(), "models": result.metrics, **lineage,
    }, indent=2), encoding="utf-8")


def run(usecases: list[str] | None = None, run_dir: str | Path | None = None,
        out_root: Path = OUT_ROOT, config: Path | None = None) -> Path:
    all_usecases = load_usecases(config) if config else load_usecases()
    names = usecases or list(all_usecases)
    run_dir = resolve_run_dir(run_dir)
    approved = check_run(run_dir)
    train_run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    out_dir = out_root / train_run_id
    lineage = {
        "train_run_id": train_run_id, "feature_run_id": approved["run_id"],
        "feature_contract": approved["feature_contract"], "git_commit": git_commit(),
        "python": platform.python_version(),
        "libraries": {p: version(p) for p in ("scikit-learn", "lightgbm", "pandas", "numpy")},
    }
    summary = {**lineage, "usecases": {}}
    for name in names:
        uc = all_usecases[name]
        df = load_frame(run_dir, uc)
        summary["usecases"][name] = {"seed": uc.seed, "feature_hash": uc.feature_hash(), "segments": {}}
        for data in iter_segments(df, uc, approved["class_weights"]):
            result = train_segment(uc, data)
            write_segment(out_dir / name / data.segment, uc, result, lineage)
            summary["usecases"][name]["segments"][data.segment] = {
                "selected": result.selected,
                **{m: {"val_auc": r["validation"]["roc_auc"], "test_auc": r["test"]["roc_auc"],
                       "test_pr_auc": r["test"]["pr_auc"], "test_recall": r["test"]["recall"]}
                   for m, r in result.metrics.items()},
            }
            print_result(result)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return out_dir


def print_result(result: SegmentResult) -> None:
    for name, r in result.metrics.items():
        v, t = r["validation"], r["test"]
        mark = "*" if name == result.selected else " "
        print(f"{result.usecase:18s} {result.segment:4s} {name:4s}{mark} thr={r['threshold']:.3f} "
              f"val_auc={v['roc_auc']:.4f} | test auc={t['roc_auc']:.4f} pr_auc={t['pr_auc']:.4f} "
              f"P={t['precision']:.3f} R={t['recall']:.3f} F1={t['f1']:.3f}  ({r['fit_seconds']}s)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--usecase", action="append", help="repeatable; default: all in usecases.yaml")
    parser.add_argument("--run-dir", help="Day 4 run dir; default: data/features/current.json")
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    args = parser.parse_args()
    out_dir = run(args.usecase, args.run_dir, args.out)
    print(f"artifacts: {out_dir}")


if __name__ == "__main__":
    main()
