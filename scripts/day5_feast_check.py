"""Day 5: register the Feast definitions and prove Feast returns the same features as Day 4.

Checks (all must pass):
  1. every entity row comes back (file offline store silently DROPS rows with no feature in TTL)
  2. no null feature
  3. loan/overdue parity: Feast features == training_dataset features for the same (account, D)
  4. campaign parity: Feast at exact sent_at == fs_* snapshot of D-1 (latest complete day)
  5. latest day: every account scorable on max(report_date)
  6. TTL: an account with no snapshot for 2+ days gets nothing (no stale values)

Usage:  python scripts/day5_feast_check.py --accounts 300     # sample (fast)
        python scripts/day5_feast_check.py --accounts 0       # all accounts
Writes feast_check.json next to the run's quality_report.json. Exit 1 on any failure.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "feature_repo"
KEYS = ["master_account", "report_date"]


def load_definitions(repo: Path = REPO):
    spec = importlib.util.spec_from_file_location("feast_definitions", repo / "definitions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply(repo: Path = REPO):
    """`feast apply` equivalent; returns (store, definitions module)."""
    from feast import FeatureStore
    defs = load_definitions(repo)
    store = FeatureStore(repo_path=str(repo))
    store.apply([defs.account, *defs.views.values(), defs.loan_propensity, defs.overdue_risk, defs.campaign_response])
    return store, defs


def service_features(store, name):
    service = store.get_feature_service(name)
    return [f.name for projection in service.feature_view_projections for f in projection.features]


def _utc(series):
    return pd.to_datetime(series, utc=True).astype("datetime64[ns, UTC]")


def _eod(day):
    """23:59:59 Asia/Ho_Chi_Minh on `day`, as a UTC timestamp (Day 4 snapshot convention)."""
    return pd.Timestamp(f"{day} 23:59:59", tz="Asia/Ho_Chi_Minh").tz_convert("UTC")


def retrieve(store, service, entity_df):
    started = time.monotonic()
    out = store.get_historical_features(entity_df=entity_df, features=store.get_feature_service(service)).to_df()
    return out, round(time.monotonic() - started, 2)


def compare(left, right, keys, columns):
    """Number of rows whose value differs in any column (float tolerance 1e-9, NaN == NaN)."""
    merged = left[keys + columns].merge(right[keys + columns], on=keys, how="inner", suffixes=("_l", "_r"))
    bad = np.zeros(len(merged), dtype=bool)
    for column in columns:
        a, b = merged[f"{column}_l"], merged[f"{column}_r"]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            a, b = a.astype("float64").to_numpy(), b.astype("float64").to_numpy()
            bad |= ~(np.isclose(a, b, rtol=0, atol=1e-9) | (np.isnan(a) & np.isnan(b)))
        else:
            bad |= ~((a.astype(str) == b.astype(str)).to_numpy())
    return int(bad.sum()), len(merged)


def run_checks(store, run_dir: Path, accounts: int = 300, seed: int = 42):
    checks, timings = [], {}

    def check(name, observed, expected):
        checks.append({"check": name, "observed": observed, "expected": expected, "passed": observed == expected})

    labels = pd.read_parquet(run_dir / "loan_overdue_labels.parquet")
    labels["event_timestamp"] = _utc(labels["event_timestamp"])
    all_accounts = np.sort(labels.master_account.unique())
    chosen = set(all_accounts if accounts in (0, None) or accounts >= len(all_accounts)
                 else np.random.default_rng(seed).choice(all_accounts, accounts, replace=False))
    labels = labels[labels.master_account.isin(chosen)].reset_index(drop=True)

    # 1-3: loan / overdue
    loan_cols = service_features(store, "loan_propensity")
    loan, timings["loan_propensity"] = retrieve(store, "loan_propensity", labels)
    check("loan.rows_returned", len(loan), len(labels))
    check("loan.null_features", int(loan[loan_cols].isna().sum().sum()), 0)
    reference = pd.read_parquet(run_dir / "training_dataset.parquet", columns=KEYS + loan_cols)
    reference = reference[reference.master_account.isin(chosen)]
    mismatches, compared = compare(loan, reference, KEYS, loan_cols)
    check("loan.parity_with_training_dataset.mismatched_rows", mismatches, 0)
    check("loan.parity_with_training_dataset.rows_compared", compared, len(labels))
    check("overdue.same_features_as_loan", sorted(service_features(store, "overdue_risk")), sorted(loan_cols))

    # wide fs_* table for the chosen accounts (reference for campaign / latest-day checks)
    fs = None
    for name in ["fs_demographic", "fs_trading_behavior", "fs_margin_balance", "fs_asset_balance", "fs_portfolio", "fs_campaign"]:
        part = pd.read_parquet(run_dir / f"{name}.parquet").drop(columns=["event_timestamp"])
        part = part[part.master_account.isin(chosen)]
        fs = part if fs is None else fs.merge(part, on=KEYS, how="inner")

    # 4: campaign at exact sent_at -> D-1 snapshot
    camp_cols = service_features(store, "campaign_response")
    camp_labels = pd.read_parquet(run_dir / "campaign_labels.parquet")
    camp_labels = camp_labels[camp_labels.master_account.isin(chosen)].reset_index(drop=True)
    camp_labels["event_timestamp"] = _utc(camp_labels["event_timestamp"])
    if len(camp_labels):
        camp, timings["campaign_response"] = retrieve(store, "campaign_response", camp_labels)
        check("campaign.rows_returned", len(camp), len(camp_labels))
        check("campaign.null_features", int(camp[camp_cols].isna().sum().sum()), 0)
        camp["report_date"] = pd.to_datetime(camp["send_date"]).dt.date - pd.Timedelta(days=1)
        camp["report_date"] = pd.to_datetime(camp["report_date"]).dt.date
        mismatches, compared = compare(camp, fs, KEYS, camp_cols)
        check("campaign.parity_with_previous_day_snapshot.mismatched_rows", mismatches, 0)
        check("campaign.parity_with_previous_day_snapshot.rows_compared", compared, len(camp_labels))
        check("campaign.no_fs_campaign_features", sorted(set(camp_cols) & {"campaign_count_30d", "days_since_last_campaign", "has_campaign_history"}), [])

    # 5: latest day
    last_day = fs.report_date.max()
    latest = fs.loc[fs.report_date == last_day, ["master_account"]].copy()
    latest["event_timestamp"] = _utc(pd.Series([_eod(last_day)] * len(latest), index=latest.index))
    scored, timings["latest_day"] = retrieve(store, "loan_propensity", latest)
    check("latest_day.rows_returned", len(scored), len(latest))
    check("latest_day.null_features", int(scored[loan_cols].isna().sum().sum()), 0)

    # 6: TTL - accounts whose snapshots stop before the last day (closed / dormant)
    last_seen = fs.groupby("master_account").report_date.max()
    stopped = last_seen[last_seen < last_day]
    if len(stopped):
        probe = pd.DataFrame({"master_account": stopped.index})
        probe["event_timestamp"] = _utc(pd.Series([_eod(d + pd.Timedelta(days=2)) for d in stopped.values]))
        stale, _ = retrieve(store, "loan_propensity", probe)
        check("ttl.no_stale_values_after_last_snapshot", int(stale[loan_cols].notna().any(axis=1).sum()), 0)

    return {"status": "PASS" if all(c["passed"] for c in checks) else "FAIL", "run_dir": str(run_dir),
            "accounts": len(chosen), "entity_rows": {"loan_overdue": len(labels), "campaign": len(camp_labels), "latest_day": len(latest)},
            "latest_day": str(last_day), "seconds": timings, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--accounts", type=int, default=300, help="sample size; 0 = all accounts")
    args = parser.parse_args()
    store, defs = apply()
    report = run_checks(store, defs.RUN_DIR, args.accounts)
    (defs.RUN_DIR / "feast_check.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    for c in report["checks"]:
        print(("PASS " if c["passed"] else "FAIL ") + f"{c['check']}: observed={c['observed']} expected={c['expected']}")
    print(f"\n{report['status']}  accounts={report['accounts']}  rows={report['entity_rows']}  seconds={report['seconds']}")
    sys.exit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
