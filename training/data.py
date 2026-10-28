"""Read an approved Day 4 run and hand out train/validation/test frames per segment."""
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
    """Refuse to train on a run that did not pass the Day 4 quality gate."""
    quality = json.loads((run_dir / "quality_report.json").read_text(encoding="utf-8"))
    if quality.get("status") != "PASS":
        raise RuntimeError(f"{run_dir.name}: quality gate is {quality.get('status')}, not PASS")
    weights = json.loads((run_dir / "class_weights.json").read_text(encoding="utf-8"))
    if not weights.get("approved_for_training"):
        raise RuntimeError(f"{run_dir.name}: class_weights.json not approved_for_training")
    return {"run_id": quality.get("run_id", run_dir.name), "feature_contract": quality.get("feature_contract")}


def label_end(dates: pd.Series, as_of: pd.Timestamp | None, horizon_days: int) -> pd.Timestamp:
    """Last report_date whose label is known at as_of: the label of D closes at D + horizon. Pure."""
    latest = pd.to_datetime(dates).max()
    return latest if as_of is None else min(latest, pd.Timestamp(as_of) - pd.Timedelta(days=horizon_days))


def split_windows(end: pd.Timestamp, test_days: int, validation_days: int, embargo_days: int) -> dict:
    """(first, last) report_date of each split, counted back from the last labeled day. Embargo gaps keep a
    label window of the earlier split from reaching into the later one. train has no lower bound. Pure."""
    day = pd.Timedelta(days=1)
    test_first = end - (test_days - 1) * day
    val_last = test_first - (embargo_days + 1) * day
    val_first = val_last - (validation_days - 1) * day
    return {"train": (None, val_first - (embargo_days + 1) * day), "validation": (val_first, val_last),
            "test": (test_first, end)}


def resplit(df: pd.DataFrame, uc: UseCase, as_of) -> pd.DataFrame:
    """Replace the Day 4 split with the sliding split for as_of. Embargo rows and rows whose label was not
    yet known at as_of are dropped. Needs a run that keeps every labeled day (split='embargo' included)."""
    dates = pd.to_datetime(df["report_date"])
    windows = split_windows(label_end(dates, as_of, uc.label_horizon_days), **uc.windows)
    split = pd.Series(None, index=df.index, dtype=object)
    for name, (first, last) in windows.items():
        split[((dates >= first) if first is not None else True) & (dates <= last)] = name
    return df.assign(split=split).dropna(subset=["split"])


def check_splits(df: pd.DataFrame, name: str) -> None:
    """train < validation < test in time, with no shared report_date."""
    dates = pd.to_datetime(df["report_date"])
    bounds = {s: (dates[df["split"] == s].min(), dates[df["split"] == s].max()) for s in SPLITS}
    for earlier, later in zip(SPLITS, SPLITS[1:]):
        if not bounds[earlier][1] < bounds[later][0]:
            raise ValueError(f"{name}: {earlier} ends {bounds[earlier][1]} but {later} starts {bounds[later][0]}")


def load_frame(run_dir: Path, uc: UseCase, as_of=None) -> pd.DataFrame:
    """as_of=None keeps the Day 4 split (anchored on the run's last labeled day)."""
    columns = list(dict.fromkeys(uc.features + [uc.label, "split", "report_date"]
                                 + ([uc.segment_column] if uc.segment_column else [])
                                 + (["overdue_eligible"] if uc.row_filter else [])))
    df = pd.read_parquet(run_dir / f"{uc.dataset}.parquet", columns=columns)
    if uc.row_filter:
        df = df.query(uc.row_filter)
    if df[uc.label].isna().any():
        raise ValueError(f"{uc.name}: {int(df[uc.label].isna().sum())} rows with null {uc.label}")
    df = df.assign(**{uc.label: df[uc.label].astype(int)})
    df = resplit(df, uc, as_of) if as_of is not None else df[df["split"] != "embargo"]
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


def balanced_weights(y_train: np.ndarray) -> dict[int, float]:
    """N / (2 * N_class) on the train rows actually used (same formula as the Day 4 class_weights.json). Pure."""
    values, counts = np.unique(y_train, return_counts=True)
    return {int(v): len(y_train) / (2 * c) for v, c in zip(values, counts)}


@dataclass
class SegmentData:
    segment: str
    X: dict[str, pd.DataFrame]
    y: dict[str, np.ndarray]
    w_train: np.ndarray
    weights: dict[int, float]


def iter_segments(df: pd.DataFrame, uc: UseCase):
    groups = [(s, df[df[uc.segment_column] == s]) for s in uc.segments] if uc.segments else [("all", df)]
    for segment, part in groups:
        X = {s: part.loc[part["split"] == s, uc.features] for s in SPLITS}
        y = {s: part.loc[part["split"] == s, uc.label].to_numpy() for s in SPLITS}
        for s in SPLITS:
            if len(np.unique(y[s])) < 2:
                raise ValueError(f"{uc.name}/{segment}/{s}: needs both classes, got {np.unique(y[s])}")
        weights = balanced_weights(y["train"])
        yield SegmentData(segment, X, y, np.vectorize(weights.get)(y["train"]).astype(float), weights)
