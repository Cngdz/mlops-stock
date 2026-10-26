"""Day 13 evaluate: join stored predictions with the true labels once their 30-day window has closed.

  python -m pipeline.evaluate --start 2025-12-25 --end 2025-12-31

Live ROC-AUC per (segment, model_version) is compared with the AUC recorded at training (version tag test_roc_auc).
Drop above evaluate.warn_drop -> WARN, above evaluate.retrain_drop -> RETRAIN. Results go to monitoring.eval_<usecase>.
Caveat for this synthetic demo: labels end on 2025-12-31 and Oct-Dec 2025 is the test split the gate already used, so
these numbers are not an independent hold-out.
"""
from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.expressions import And, EqualTo, GreaterThanOrEqual, LessThanOrEqual
from sklearn.metrics import roc_auc_score

from pipeline import catalog as lakehouse
from pipeline.common import feature_run, load_settings, parse_date, write_partition
from training import registry

SCHEMA = pa.schema([
    ("window_start", pa.date32()),
    ("window_end", pa.date32()),
    ("segment", pa.string()),
    ("model_name", pa.string()),
    ("model_version", pa.string()),
    ("n_rows", pa.int64()),
    ("n_positive", pa.int64()),
    ("live_auc", pa.float64()),
    ("reference_auc", pa.float64()),
    ("auc_drop", pa.float64()),
    ("status", pa.string()),
    ("evaluated_at", pa.timestamp("us")),
])


def status_for(drop: float | None, warn_drop: float, retrain_drop: float) -> str:
    if drop is None:
        return "NO_LABELS"
    if drop > retrain_drop:
        return "RETRAIN"
    if drop > warn_drop:
        return "WARN"
    return "OK"


def evaluate(joined: pd.DataFrame, reference_auc: dict, label: str, warn_drop: float, retrain_drop: float,
             ) -> pd.DataFrame:
    """joined: predictions + label column. reference_auc: (model_name, version) -> AUC at training. Pure."""
    rows = []
    for (segment, name, version), group in joined.groupby(["segment", "model_name", "model_version"], sort=True):
        y = group[label].astype(int)
        live = float(roc_auc_score(y, group["score"])) if y.nunique() == 2 else None
        ref = reference_auc.get((name, version))
        drop = None if live is None or ref is None else ref - live
        rows.append({"segment": segment, "model_name": name, "model_version": version, "n_rows": len(group),
                     "n_positive": int(y.sum()), "live_auc": live, "reference_auc": ref, "auc_drop": drop,
                     "status": status_for(drop, warn_drop, retrain_drop)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=parse_date, required=True)
    parser.add_argument("--end", type=parse_date, required=True)
    args = parser.parse_args()

    settings = load_settings()
    usecase, cfg = settings["usecase"], settings["evaluate"]
    label = "loan_label_next"
    catalog = lakehouse.load()
    preds = catalog.load_table(f"{lakehouse.NAMESPACE}.pred_{usecase}").scan(
        row_filter=And(GreaterThanOrEqual("score_date", args.start.isoformat()),
                       LessThanOrEqual("score_date", args.end.isoformat()))).to_pandas()
    if preds.empty:
        raise SystemExit(f"no predictions between {args.start} and {args.end}: run pipeline.predict first")
    run_dir, _ = feature_run()
    labels = pq.read_table(run_dir / "loan_overdue_labels.parquet",
                           columns=["master_account", "report_date", label],
                           filters=[("report_date", ">=", args.start), ("report_date", "<=", args.end)]).to_pandas()
    labels = labels.assign(master_account=labels["master_account"].astype(str)).rename(
        columns={"report_date": "score_date"})
    joined = preds.merge(labels, on=["master_account", "score_date"], how="inner")
    print(f"{len(preds)} predictions, {len(joined)} with a closed label window")

    client = registry.configure()
    reference = {}
    for name, version in joined[["model_name", "model_version"]].drop_duplicates().itertuples(index=False):
        tag = client.get_model_version(name, version).tags.get("test_roc_auc")
        reference[(name, version)] = float(tag) if tag else None
    result = evaluate(joined, reference, label, cfg["warn_drop"], cfg["retrain_drop"])
    result = result.assign(window_start=args.start, window_end=args.end,
                           evaluated_at=dt.datetime.now(dt.UTC).replace(tzinfo=None))
    write_partition(catalog, f"{lakehouse.NAMESPACE}.eval_{usecase}",
                    pa.Table.from_pandas(result[SCHEMA.names], schema=SCHEMA, preserve_index=False), "window_end",
                    And(EqualTo("window_start", args.start.isoformat()), EqualTo("window_end", args.end.isoformat())))
    for r in result.itertuples():
        live = "n/a" if r.live_auc is None or pd.isna(r.live_auc) else f"{r.live_auc:.4f}"
        ref = "n/a" if r.reference_auc is None or pd.isna(r.reference_auc) else f"{r.reference_auc:.4f}"
        print(f"  {r.model_name} v{r.model_version}: rows {r.n_rows}, positives {r.n_positive}, "
              f"live auc {live} vs training {ref} -> {r.status}")


if __name__ == "__main__":
    main()
