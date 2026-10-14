"""Deterministic extension sources for the multi-use-case demo.

These tables enrich the shared feature platform; they do not contain labels.
Labels are derived point-in-time in the Day 4 pipeline.

Campaigns are NOT generated here: since generator 0.2.0 they are produced
inside the daily state machine in ``generate_all.generate_events`` because a
delivered campaign raises the probability of a disbursement in the following
14 days (see docs/data_generation_decisions.md section 8.6).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

import numpy as np
import pandas as pd
import pyarrow as pa


CAMPAIGN_COLUMNS = [
    "campaign_event_id", "campaign_id", "master_account", "sent_at", "channel",
    "offer_type", "interest_rate_offer", "status",
]
HOLDING_COLUMNS = [
    "master_account", "business_date", "symbol", "quantity", "average_cost",
    "market_value", "unrealized_pnl", "portfolio_weight",
]


def generate_security_master(symbols: list[str], seed: int = 42) -> pd.DataFrame:
    """Return a stable symbol dimension with deterministic risk attributes."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, 17]))
    sectors = ["BANKING", "TECH", "ENERGY", "CONSUMER", "INDUSTRIAL"]
    rows = []
    for symbol in symbols:
        risk = str(rng.choice(["LOW", "MEDIUM", "HIGH"], p=[.45, .40, .15]))
        rows.append({
            "symbol": symbol,
            "sector": str(rng.choice(sectors)),
            "exchange": str(rng.choice(["HOSE", "HNX", "UPCOM"], p=[.65, .25, .10])),
            "liquidity_group": str(rng.choice(["LARGE", "MID", "SMALL"], p=[.25, .50, .25])),
            "margin_eligible": bool(rng.random() < .82),
            "risk_level": risk,
            "effective_from": date(2025, 1, 1),
            "effective_to": None,
        })
    frame = pd.DataFrame(rows)
    # All-null object column would be written as parquet null type, which Iceberg v2 rejects.
    frame["effective_to"] = frame["effective_to"].astype(pd.ArrowDtype(pa.date32()))
    return frame


def iter_portfolio_holdings(accounts: pd.DataFrame, prices: pd.DataFrame,
                            transactions: pd.DataFrame, batch_size: int = 250) -> Iterator[pd.DataFrame]:
    """Yield reconstructed end-of-day positions in account batches.

    The full table is ~20 million rows for 5,000 accounts, so callers should
    stream batches to Parquet instead of holding everything in memory.
    The reconstruction is intentionally independent of ``asset_value`` in
    margin_balance_daily (decisions section 9.2).
    """
    price_map = {(r.business_date, r.symbol): r.price for r in prices.itertuples()}
    last_day = prices.business_date.max()
    tx_by_account_day: dict[tuple[str, date], list[tuple[str, str, int, float]]] = {}
    for row in transactions.itertuples(index=False):
        day = row.transaction_time.date()
        tx_by_account_day.setdefault((row.master_account, day), []).append(
            (row.symbol, row.side, int(row.quantity), float(row.price)))

    for start in range(0, len(accounts), batch_size):
        rows = []
        for account in accounts.iloc[start:start + batch_size].itertuples(index=False):
            positions: dict[str, dict[str, float]] = {}
            days = (last_day - account.account_open_date).days + 1
            for offset in range(max(0, days)):
                day = account.account_open_date + timedelta(days=offset)
                for symbol, side, quantity, price in tx_by_account_day.get((account.master_account, day), []):
                    position = positions.setdefault(symbol, {"quantity": 0.0, "cost": 0.0})
                    if side == "BUY":
                        old_qty = position["quantity"]
                        position["cost"] = (position["cost"] * old_qty + price * quantity) / max(old_qty + quantity, 1)
                        position["quantity"] += quantity
                    else:
                        position["quantity"] = max(0.0, position["quantity"] - quantity)
                    if position["quantity"] == 0:
                        positions.pop(symbol, None)
                values = []
                for symbol, position in positions.items():
                    market_value = round(position["quantity"] * price_map[(day, symbol)])
                    pnl = round((price_map[(day, symbol)] - position["cost"]) * position["quantity"])
                    values.append((symbol, position, market_value, pnl))
                total_value = sum(value for _, _, value, _ in values)
                for symbol, position, market_value, pnl in values:
                    rows.append((
                        account.master_account, day, symbol, int(position["quantity"]),
                        round(position["cost"], 2), market_value, pnl,
                        market_value / total_value if total_value else 0.0,
                    ))
        yield pd.DataFrame(rows, columns=HOLDING_COLUMNS)


def generate_portfolio_holdings(accounts: pd.DataFrame, prices: pd.DataFrame,
                                transactions: pd.DataFrame) -> pd.DataFrame:
    """Return all positions at once; use ``iter_portfolio_holdings`` for full runs."""
    frames = list(iter_portfolio_holdings(accounts, prices, transactions))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=HOLDING_COLUMNS)
