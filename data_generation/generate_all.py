"""Deterministic synthetic sources. Feature/label construction belongs to Day 4."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from pathlib import Path

import hashlib

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .generate_accounts import generate_accounts
from .generate_extensions import CAMPAIGN_COLUMNS, generate_security_master, iter_portfolio_holdings

GENERATOR_VERSION = "0.2.0"
START, END, SEED = date(2025, 1, 1), date(2026, 1, 30), 42
LOCAL_TZ = timezone(timedelta(hours=7))
HOLIDAYS = {date(2025, 1, 1), date(2025, 4, 30), date(2025, 5, 1), date(2025, 9, 2), date(2026, 1, 1)}
SYMBOLS = [f"SYN{i:03d}" for i in range(1, 31)]
COLLATERAL_RATIOS = {"LOW": .60, "MEDIUM": .70, "HIGH": .80}
DEFAULT_INTERCEPTS = {"nu": -5.40, "lu": -4.60, "au": -3.80}
TRADE_EFFECTS = {"nu": -.30, "lu": 0.0, "au": .30}
# Decisions section 8.6. Campaigns are generated inside the daily state machine
# and raise the margin-event logit for 14 days after a DELIVERED campaign.
CAMPAIGN_CONFIG = {
    "enabled": True,
    "min_days_since_open": 30,
    "last_send_offset_days": 14,
    "send_probability_base": 0.035,
    "send_multiplier": {"nu": 1.20, "lu": 1.20, "au": 0.60},
    "min_gap_days": 14,
    "max_campaigns_per_account": 12,
    "delivered_probability": 0.96,
    "channel": {"APP": 0.50, "SMS": 0.30, "EMAIL": 0.20},
    "offer_type": {"RATE_DISCOUNT": 0.40, "FEE_WAIVER": 0.30, "LIMIT_BOOST": 0.30},
    "rate_min": 0.065, "rate_max": 0.105,
    "campaign_id_pool": 4,
    "uplift": {
        "active_from_day": 1, "active_to_day": 14,
        "offer_effect": {"RATE_DISCOUNT": 0.60, "LIMIT_BOOST": 0.45, "FEE_WAIVER": 0.25},
        "rate_slope": 0.30,
        "channel_effect": {"APP": 0.15, "SMS": 0.00, "EMAIL": -0.10},
        "affinity_interaction": 0.80,
    },
}
TX_COLUMNS = ["transaction_id", "master_account", "symbol", "transaction_time", "side", "quantity", "price", "trade_value"]
CF_COLUMNS = ["cash_flow_id", "master_account", "event_date", "status", "fk_product", "fk_cash_flow_type", "fk_deliver_type", "amount"]
BAL_COLUMNS = ["master_account", "business_date", "cash_balance", "asset_value", "margin_debt", "margin_limit", "collateral_value", "NAV", "margin_utilization_ratio", "margin_status"]


def sigmoid(value):
    return 1 / (1 + math.exp(-max(-30, min(30, value))))


def status_at(account, day):
    if pd.notna(account.account_close_date) and day >= account.account_close_date:
        return "CLOSED"
    if pd.notna(account.dormant_start_date) and day >= account.dormant_start_date:
        return "DORMANT"
    return "ACTIVE"


def limit_for(asset, ratio, active=True):
    return round(min(500_000_000, max(5_000_000, asset * ratio * .5))) if active and asset > 0 else 0


def _pick(u, options):
    """Deterministic categorical draw from a uniform ``u`` using cumulative weights."""
    cumulative = 0.0
    last = None
    for key, weight in options.items():
        cumulative += weight
        last = key
        if u < cumulative:
            return key
    return last


def campaign_logit_uplift(config, campaign, day, margin_affinity):
    """Logit added to p_margin_event while a delivered campaign is in effect."""
    if not config["enabled"] or campaign is None:
        return 0.0
    sent_day, offer, channel, rate = campaign
    uplift = config["uplift"]
    gap = (day - sent_day).days
    if not (uplift["active_from_day"] <= gap <= uplift["active_to_day"]):
        return 0.0
    return (uplift["offer_effect"][offer]
            + uplift["rate_slope"] * (config["rate_max"] - rate) / (config["rate_max"] - config["rate_min"])
            + uplift["channel_effect"][channel]
            + uplift["affinity_interaction"] * margin_affinity)


def generate_prices(seed=SEED):
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0, 1]))
    prices = rng.uniform(10_000, 150_000, len(SYMBOLS))
    rows = []
    for offset in range((END - START).days + 1):
        day = START + timedelta(days=offset)
        if day.weekday() < 5 and day not in HOLIDAYS:
            prices = np.clip(prices * np.exp(rng.normal(.0002, .02, len(SYMBOLS))), 1_000, 500_000)
        rows.extend((day, symbol, round(float(price), 2)) for symbol, price in zip(SYMBOLS, prices))
    return pd.DataFrame(rows, columns=["business_date", "symbol", "price"])


def generate_events(accounts, prices, seed=SEED, intercepts=None, repayment_probability=.10, campaign_config=None):
    """Return (transactions, cash_flows, balances, campaigns)."""
    intercepts = DEFAULT_INTERCEPTS if intercepts is None else intercepts
    cc = CAMPAIGN_CONFIG if campaign_config is None else campaign_config
    if set(intercepts) != {"nu", "lu", "au"}:
        raise ValueError("Expected intercepts for nu, lu, au")
    price_map = {(r.business_date, r.symbol): r.price for r in prices.itertuples()}
    transactions, cashflows, balances, campaigns = [], [], [], []
    days = (END - START).days + 1
    for account in accounts.itertuples(index=False):
        account_id = account.master_account
        # Independent streams: cash-flow calibration cannot consume trading RNG.
        trade_rng = np.random.default_rng(np.random.SeedSequence([seed, int(account_id), 1]))
        cash_rng = np.random.default_rng(np.random.SeedSequence([seed, int(account_id), 2]))
        balance_rng = np.random.default_rng(np.random.SeedSequence([seed, int(account_id), 3]))
        # Dedicated campaign stream (decisions section 8.6): adding or removing
        # campaigns never consumes the trading, cash-flow or balance streams.
        campaign_u = np.random.default_rng(np.random.SeedSequence([seed, int(account_id), 4])).random((days, 8))
        active_campaign, last_send, sent_count = None, None, 0
        uniforms = cash_rng.random((days, 10))
        margin_noise = cash_rng.normal(0, .2, days)
        repayment_ratios = cash_rng.normal(.15, .05, days)
        market_returns = balance_rng.normal(.0002, .01, days)
        asset = round(min(500_000_000, max(10_000_000, math.exp(balance_rng.normal(17.5, .7)))))
        cash = round(asset * balance_rng.uniform(.20, .60))
        debt, over_limit_streak = 0, 0
        last_event = None
        recent_trades = deque()
        last_buy = None
        collateral_ratio = COLLATERAL_RATIOS[account.risk_profile]
        for offset in range(days):
            day = START + timedelta(days=offset)
            if day < account.account_open_date:
                continue
            state = status_at(account, day)
            active = state == "ACTIVE"
            market = day.weekday() < 5 and day not in HOLIDAYS
            if state == "CLOSED":
                cash = asset = debt = 0
            segment = "au" if debt > 0 or (last_event is not None and (day-last_event).days <= 30) else ("lu" if last_event is not None else "nu")
            # Uplift uses only campaigns sent on earlier days (effect starts at t+1).
            campaign_logit = campaign_logit_uplift(cc, active_campaign, day, account.margin_affinity)
            if (cc["enabled"] and active and sent_count < cc["max_campaigns_per_account"]
                    and day >= account.account_open_date + timedelta(days=cc["min_days_since_open"])
                    and day <= END - timedelta(days=cc["last_send_offset_days"])
                    and (last_send is None or (day - last_send).days >= cc["min_gap_days"])):
                cu = campaign_u[offset]
                if cu[0] < cc["send_probability_base"] * cc["send_multiplier"][segment]:
                    sent_count += 1
                    last_send = day
                    channel = _pick(cu[1], cc["channel"])
                    offer = _pick(cu[2], cc["offer_type"])
                    rate = round(cc["rate_min"] + (cc["rate_max"] - cc["rate_min"]) * float(cu[3]), 4)
                    sent_at = datetime.combine(day, time(10), LOCAL_TZ) + timedelta(minutes=int(cu[4] * 480))
                    delivered = cu[5] < cc["delivered_probability"]
                    campaigns.append((
                        f"CMP-{account_id}-{sent_count:03d}",
                        f"MARGIN-{1 + int(cu[6] * cc['campaign_id_pool']):02d}",
                        account_id, sent_at, channel, offer, rate, "DELIVERED" if delivered else "FAILED"))
                    if delivered:
                        active_campaign = (day, offer, channel, rate)
            day_tx = []
            if active and market:
                probability = sigmoid(-2.4 + 1.6*account.trading_propensity + .5*account.activity_stability + TRADE_EFFECTS[segment] + trade_rng.normal(0, .25))
                count = min(20, int(trade_rng.poisson(min(8, max(.2, .2 + 5*probability))))) if trade_rng.random() < probability else 0
                for _ in range(count):
                    symbol = SYMBOLS[int(trade_rng.integers(len(SYMBOLS)))]
                    side = "BUY" if trade_rng.random() < .55 else "SELL"
                    quantity = round(min(100_000, max(10, trade_rng.lognormal(6, .8))))
                    price = price_map[(day, symbol)]
                    stamp = datetime.combine(day, time(9), LOCAL_TZ) + timedelta(seconds=int(trade_rng.integers(0, 20_701)))
                    day_tx.append((stamp, symbol, side, quantity, price, round(quantity*price)))
                day_tx.sort()
                for sequence, (stamp, symbol, side, quantity, price, value) in enumerate(day_tx, 1):
                    transactions.append((f"TXN-{account_id}-{day:%Y%m%d}-{sequence:05d}", account_id, symbol, stamp, side, quantity, price, value))
                    recent_trades.append((day, value))
                    if side == "BUY":
                        last_buy = (day, value)
            while recent_trades and (day-recent_trades[0][0]).days > 29:
                recent_trades.popleft()
            activity = .5*min(len(recent_trades)/30, 1) + .5*min(sum(v for _,v in recent_trades)/50_000_000, 1)
            buy = sum(row[5] for row in day_tx if row[2] == "BUY")
            sell = sum(row[5] for row in day_tx if row[2] == "SELL")
            asset = max(0, round(asset*(1 + (market_returns[offset] if market and state != "CLOSED" else 0)) + buy-sell))
            limit = limit_for(asset, collateral_ratio, active)
            disbursed = repaid = fees = 0
            sequence = 0
            u = uniforms[offset]
            if active and debt > 0 and u[0] < repayment_probability:
                amount = debt if debt < 1_000_000 else min(debt, max(1_000_000, round(debt*repayment_ratios[offset])))
                posted = u[1] >= .02
                sequence += 1
                cashflows.append((f"CF-{account_id}-{day:%Y%m%d}-{sequence:03d}", account_id, day, "POSTED" if posted else "CANCELLED", "MARGIN_MBS", "REPAYMENT", "OTHER", amount))
                if posted:
                    debt -= amount
                    repaid = amount
            probability = sigmoid(intercepts[segment] + 1.4*account.margin_affinity + activity + .6*account.wealth_level + .4*account.risk_appetite + campaign_logit + margin_noise[offset])
            if active and market and last_buy is not None and (day-last_buy[0]).days <= 6 and u[2] < probability:
                posted = u[3] >= .02
                product, flow, deliver, amount = "OTHER", "OTHER", "OTHER", 0
                valid = u[4] < .85
                if valid:
                    available = max(0, limit-debt)
                    if available >= 1_000_000:
                        amount = max(1_000_000, round(min((.2 + .4*u[5])*last_buy[1], available)))
                        product, flow, deliver = ("MARGIN_MBS", "INTERM_DELIVER", "BUY_SHARE") if u[6] < .7 else ("MBLINK", "TLO_DELIVER_CASH", "BUY")
                elif u[7] < .6:
                    product, flow, deliver, amount = "MBLINK", "FEE", "OTHER", round(10_000 + u[8]*490_000)
                else:
                    amount = round(100_000 + u[8]*4_900_000)
                if amount:
                    sequence += 1
                    cashflows.append((f"CF-{account_id}-{day:%Y%m%d}-{sequence:03d}", account_id, day, "POSTED" if posted else "CANCELLED", product, flow, deliver, amount))
                    if posted and valid:
                        disbursed = amount
                        debt += amount
                        last_event = day
                    elif posted and flow == "FEE":
                        fees = amount
            cash = max(0, cash + sell - buy + disbursed - repaid - fees)
            collateral = round(asset*collateral_ratio)
            if debt == 0:
                over_limit_streak = 0
                margin_status = "NO_MARGIN"
            else:
                if market:
                    over_limit_streak = over_limit_streak + 1 if debt > limit else 0
                margin_status = "OVERDUE" if over_limit_streak >= 3 else "ACTIVE"
            balances.append((account_id, day, cash, asset, debt, limit, collateral, asset+cash-debt, debt/limit if limit else 0.0, margin_status))
    tx = pd.DataFrame(transactions, columns=TX_COLUMNS)
    tx["transaction_time"] = pd.to_datetime(tx["transaction_time"], utc=True).dt.tz_convert(LOCAL_TZ)
    cf = pd.DataFrame(cashflows, columns=CF_COLUMNS)
    bal = pd.DataFrame(balances, columns=BAL_COLUMNS)
    camp = pd.DataFrame(campaigns, columns=CAMPAIGN_COLUMNS)
    camp["sent_at"] = pd.to_datetime(camp["sent_at"], utc=True).dt.tz_convert(LOCAL_TZ)  # typed even when empty
    camp["interest_rate_offer"] = camp["interest_rate_offer"].astype("float64")
    for frame, cols in [(tx, ["quantity","trade_value"]), (cf, ["amount"]), (bal, ["cash_balance","asset_value","margin_debt","margin_limit","collateral_value","NAV"])]:
        for col in cols:
            frame[col] = frame[col].astype("int64")
    return tx, cf, bal, camp


def _sha256(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-accounts", type=int, default=5000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calibration", type=Path)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"Use a new output directory: {args.output}")
    calibration = json.loads(args.calibration.read_text()) if args.calibration else None
    if calibration and calibration["status"] != "PASS":
        raise ValueError("Calibration has not passed")
    intercepts = calibration["intercepts"] if calibration else DEFAULT_INTERCEPTS
    accounts, prices = generate_accounts(args.num_accounts), generate_prices()
    tx, cf, balances, campaigns = generate_events(
        accounts, prices, intercepts=intercepts,
        repayment_probability=calibration.get('repayment_probability', .10) if calibration else .10)
    securities = generate_security_master(SYMBOLS)
    args.output.mkdir(parents=True, exist_ok=True)
    frames = {"customer_account": accounts, "stock_price_daily": prices, "security_master": securities,
              "stock_transaction": tx, "margin_cash_flow": cf, "margin_balance_daily": balances,
              "customer_campaign": campaigns}
    for name, frame in frames.items():
        frame.to_parquet(args.output / f"{name}.parquet", index=False)

    # Holdings are streamed: ~20M rows for 5,000 accounts must not sit in memory.
    holdings_path = args.output / "portfolio_holding_daily.parquet"
    writer, holding_rows, ratios = None, 0, []
    zero_asset_days = holding_days = 0
    for batch in iter_portfolio_holdings(accounts, prices, tx):
        if batch.empty:
            continue
        table = pa.Table.from_pandas(batch, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(holdings_path, table.schema)
        writer.write_table(table.cast(writer.schema))
        holding_rows += len(batch)
        daily = batch.groupby(["master_account", "business_date"], as_index=False).market_value.sum()
        merged = daily.merge(balances[balances.master_account.isin(daily.master_account.unique())]
                             [["master_account", "business_date", "asset_value"]],
                             on=["master_account", "business_date"], how="left")
        holding_days += len(merged)
        zero_asset_days += int((merged.asset_value.fillna(0) <= 0).sum())
        positive = merged[merged.asset_value > 0]
        ratios.append((positive.market_value / positive.asset_value).sample(min(20_000, len(positive)), random_state=SEED))
    if writer is not None:
        writer.close()
    else:
        pd.DataFrame(columns=["master_account"]).to_parquet(holdings_path, index=False)
    ratio_all = pd.concat(ratios) if ratios else pd.Series(dtype=float)
    frames_rows = {k: len(v) for k, v in frames.items()}
    frames_rows["portfolio_holding_daily"] = holding_rows

    metadata = {
        "generator_version": GENERATOR_VERSION, "seed": SEED, "raw_start": START.isoformat(), "raw_end": END.isoformat(),
        "num_accounts": args.num_accounts, "intercepts": intercepts, "calibration": calibration,
        "campaign_config": CAMPAIGN_CONFIG, "rows": frames_rows,
        # Decisions 9.2: holdings are NOT reconciled with asset_value; recorded for transparency only.
        "portfolio_vs_asset_value": {
            "median_ratio_sample": float(ratio_all.median()) if len(ratio_all) else None,
            "holding_days_with_zero_asset_value": zero_asset_days, "holding_days": holding_days,
        },
        "output_sha256": {f"{name}.parquet": _sha256(args.output / f"{name}.parquet") for name in [*frames, "portfolio_holding_daily"]},
    }
    (args.output / "generation_run.json").write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    print(json.dumps(frames_rows))


if __name__ == "__main__":
    main()
