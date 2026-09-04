"""Deterministic synthetic sources. Feature/label construction belongs to Day 4."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .generate_accounts import generate_accounts

START, END, SEED = date(2025, 1, 1), date(2026, 1, 30), 42
LOCAL_TZ = timezone(timedelta(hours=7))
HOLIDAYS = {date(2025, 1, 1), date(2025, 4, 30), date(2025, 5, 1), date(2025, 9, 2), date(2026, 1, 1)}
SYMBOLS = [f"SYN{i:03d}" for i in range(1, 31)]
COLLATERAL_RATIOS = {"LOW": .60, "MEDIUM": .70, "HIGH": .80}
DEFAULT_INTERCEPTS = {"nu": -5.40, "lu": -4.60, "au": -3.80}
TRADE_EFFECTS = {"nu": -.30, "lu": 0.0, "au": .30}
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


def generate_events(accounts, prices, seed=SEED, intercepts=None, repayment_probability=.10):
    intercepts = DEFAULT_INTERCEPTS if intercepts is None else intercepts
    if set(intercepts) != {"nu", "lu", "au"}:
        raise ValueError("Expected intercepts for nu, lu, au")
    price_map = {(r.business_date, r.symbol): r.price for r in prices.itertuples()}
    transactions, cashflows, balances = [], [], []
    days = (END - START).days + 1
    for account in accounts.itertuples(index=False):
        account_id = account.master_account
        # Independent streams: cash-flow calibration cannot consume trading RNG.
        trade_rng = np.random.default_rng(np.random.SeedSequence([seed, int(account_id), 1]))
        cash_rng = np.random.default_rng(np.random.SeedSequence([seed, int(account_id), 2]))
        balance_rng = np.random.default_rng(np.random.SeedSequence([seed, int(account_id), 3]))
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
            probability = sigmoid(intercepts[segment] + 1.4*account.margin_affinity + activity + .6*account.wealth_level + .4*account.risk_appetite + margin_noise[offset])
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
    for frame, cols in [(tx, ["quantity","trade_value"]), (cf, ["amount"]), (bal, ["cash_balance","asset_value","margin_debt","margin_limit","collateral_value","NAV"])]:
        for col in cols:
            frame[col] = frame[col].astype("int64")
    return tx, cf, bal


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
    tx, cf, balances = generate_events(accounts, prices, intercepts=intercepts,
                                     repayment_probability=calibration.get('repayment_probability', .10) if calibration else .10)
    args.output.mkdir(parents=True, exist_ok=True)
    frames = {"customer_account": accounts, "stock_price_daily": prices, "stock_transaction": tx, "margin_cash_flow": cf, "margin_balance_daily": balances}
    for name, frame in frames.items():
        frame.to_parquet(args.output / f"{name}.parquet", index=False)
    metadata = {"seed": SEED, "raw_end": END.isoformat(), "num_accounts": args.num_accounts, "intercepts": intercepts, "calibration": calibration, "rows": {k:len(v) for k,v in frames.items()}}
    (args.output / "generation_run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({k:len(v) for k,v in frames.items()}))


if __name__ == "__main__":
    main()
