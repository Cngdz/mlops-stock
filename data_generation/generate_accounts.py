"""Generate the deterministic customer_account source table.

This is step 1 of the generator pipeline.  The values mirror the decisions in
``docs/data_generation_decisions.md`` and deliberately keep account-level RNG
independent, so adding an account does not alter existing accounts.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


RAW_START = date(2025, 1, 1)
RAW_END = date(2026, 1, 30)
SEED = 42
DEFAULT_NUM_ACCOUNTS = 5_000


def _choice(rng: np.random.Generator, values: list[str], probabilities: list[float]) -> str:
    return str(rng.choice(values, p=probabilities))


def generate_accounts(
    num_accounts: int = DEFAULT_NUM_ACCOUNTS,
    seed: int = SEED,
    raw_start: date = RAW_START,
    raw_end: date = RAW_END,
) -> pd.DataFrame:
    """Return accounts with the exact source-table schema and deterministic IDs."""
    if num_accounts <= 0:
        raise ValueError("num_accounts must be positive")
    if raw_end <= raw_start:
        raise ValueError("raw_end must be after raw_start")

    rows: list[dict[str, object]] = []
    # SeedSequence makes each account's stream independent of iteration count.
    for index in range(1, num_accounts + 1):
        rng = np.random.default_rng(np.random.SeedSequence([seed, index]))
        account = f"{index:010d}"
        open_date = raw_start + timedelta(days=int(rng.integers(0, 31)))
        status = _choice(rng, ["ACTIVE", "DORMANT", "CLOSED"], [0.95, 0.04, 0.01])
        close_date: date | None = None
        dormant_date: date | None = None
        if status == "CLOSED":
            close_date = date(raw_start.year, 10, 1) + timedelta(days=int(rng.integers(0, 61)))
            close_date = min(close_date, raw_end)
        elif status == "DORMANT":
            dormant_date = date(raw_start.year, 9, 1) + timedelta(days=int(rng.integers(0, 91)))
            dormant_date = min(dormant_date, raw_end)

        archetype = int(rng.choice(3, p=[0.45, 0.30, 0.25]))
        trading_beta = [(2.0, 5.0), (2.5, 4.0), (3.0, 3.0)][archetype]
        margin_beta = [(1.5, 8.0), (3.0, 5.0), (6.0, 3.0)][archetype]
        risk_beta = [(2.0, 5.0), (3.0, 4.0), (4.0, 3.0)][archetype]
        rows.append(
            {
                "master_account": account,
                "account_open_date": open_date,
                "account_status": status,
                "account_close_date": close_date,
                "dormant_start_date": dormant_date,
                "customer_group": _choice(rng, ["RETAIL", "VIP", "CORPORATE"], [0.85, 0.10, 0.05]),
                "risk_profile": _choice(rng, ["LOW", "MEDIUM", "HIGH"], [0.30, 0.50, 0.20]),
                "created_at": "2025-01-01T00:00:00+07:00",
                # Latent variables are retained in the Silver account table;
                # downstream Gold features must not expose them.
                "wealth_level": float(rng.beta(2.5, 2.5)),
                "trading_propensity": float(rng.beta(*trading_beta)),
                "margin_affinity": float(rng.beta(*margin_beta)),
                "risk_appetite": float(rng.beta(*risk_beta)),
                "activity_stability": float(rng.beta(4.0, 2.0)),
            }
        )

    frame = pd.DataFrame(rows)
    frame["account_open_date"] = pd.to_datetime(frame["account_open_date"]).dt.date
    frame["account_close_date"] = pd.to_datetime(frame["account_close_date"]).dt.date
    frame["dormant_start_date"] = pd.to_datetime(frame["dormant_start_date"]).dt.date
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-accounts", type=int, default=DEFAULT_NUM_ACCOUNTS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path, default=Path("data/generated/customer_account.parquet"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame = generate_accounts(args.num_accounts, args.seed)
    frame.to_parquet(args.output, index=False)
    print(f"wrote {len(frame):,} accounts to {args.output}")


if __name__ == "__main__":
    main()
