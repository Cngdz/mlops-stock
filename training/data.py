"""Read an approved training run (features.build_training) and hand out train/validation/test frames per segment."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from training.config import UseCase

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ("train", "validation", "test")


def resolve_run_dir(run_dir: str | Path | None = None) -> Path:
    if run_dir:
        return Path(run_dir)
    pointer = json.loads((ROOT / "data/features/current.json").read_text(encoding="utf-8"))
    return ROOT / "data/features/day4_runs" / pointer["run_id"]  # ignore the absolute Windows path


def check_run(run_dir: Path) -> dict:
    """Refuse to train on a run that did not pass the training-data quality gate."""
    quality = json.loads((run_dir / "quality_report.json").read_text(encoding="utf-8"))
    if quality.get("status") != "PASS":
        raise RuntimeError(f"{run_dir.name}: quality gate is {quality.get('status')}, not PASS")
    weights = json.loads((run_dir / "class_weights.json").read_text(encoding="utf-8"))
    if not weights.get("approved_for_training"):
        raise RuntimeError(f"{run_dir.name}: class_weights.json not approved_for_training")
    return {"run_id": quality.get("run_id", run_dir.name), "feature_contract": quality.get("feature_contract"),
            "class_weights": weights}


def check_splits(df: pd.DataFrame, name: str) -> None:
    """train < validation < test in time, with no shared report_date."""
    dates = pd.to_datetime(df["report_date"])
    bounds = {s: (dates[df["split"] == s].min(), dates[df["split"] == s].max()) for s in SPLITS}
    for earlier, later in zip(SPLITS, SPLITS[1:]):
        if not bounds[earlier][1] < bounds[later][0]:
            raise ValueError(f"{name}: {earlier} ends {bounds[earlier][1]} but {later} starts {bounds[later][0]}")


def load_frame(run_dir: Path, uc: UseCase) -> pd.DataFrame:
    columns = list(dict.fromkeys(uc.features + [uc.label, "split", "report_date"]
                                 + ([uc.segment_column] if uc.segment_column else [])
                                 + (["overdue_eligible"] if uc.row_filter else [])))
    df = pd.read_parquet(run_dir / f"{uc.dataset}.parquet", columns=columns)
    if uc.row_filter:
        df = df.query(uc.row_filter)
    if df[uc.label].isna().any():
        raise ValueError(f"{uc.name}: {int(df[uc.label].isna().sum())} rows with null {uc.label}")
    df = df.assign(**{uc.label: df[uc.label].astype(int)})
    check_splits(df, uc.name)
    return df.reset_index(drop=True)


def cut_train(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """Backtest: pretend training happened `days` earlier by dropping the last `days` of the train
    window. Validation and test stay identical, so versions trained at different cutoffs compare fairly."""
    if days <= 0:
        return df
    dates = pd.to_datetime(df["report_date"])
    train = df["split"] == "train"
    cutoff = dates[train].max() - pd.Timedelta(days=days)
    if cutoff < dates[train].min():
        raise ValueError(f"train cutoff of {days} days removes the whole train window")
    return df[~train | (dates <= cutoff)].reset_index(drop=True)


def segment_weights(class_weights: dict, uc: UseCase, segment: str | None) -> dict[int, float]:
    node = class_weights
    for key in uc.class_weights.split("."):
        node = node[key]
    if segment is not None:
        node = node[segment]
    return {int(k): float(v) for k, v in node["weights"].items()}


@dataclass
class SegmentData:
    segment: str
    X: dict[str, pd.DataFrame]
    y: dict[str, np.ndarray]
    w_train: np.ndarray
    weights: dict[int, float]


def iter_segments(df: pd.DataFrame, uc: UseCase, class_weights: dict):
    groups = [(s, df[df[uc.segment_column] == s]) for s in uc.segments] if uc.segments else [("all", df)]
    for segment, part in groups:
        weights = segment_weights(class_weights, uc, segment if uc.segments else None)
        X = {s: part.loc[part["split"] == s, uc.features] for s in SPLITS}
        y = {s: part.loc[part["split"] == s, uc.label].to_numpy() for s in SPLITS}
        for s in SPLITS:
            if len(np.unique(y[s])) < 2:
                raise ValueError(f"{uc.name}/{segment}/{s}: needs both classes, got {np.unique(y[s])}")
        yield SegmentData(segment, X, y, np.vectorize(weights.get)(y["train"]).astype(float), weights)
