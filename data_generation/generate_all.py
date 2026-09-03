"""End-to-end MVP synthetic data generator.

The implementation follows the decisions document and intentionally keeps the
source tables inspectable. Run with ``--num-accounts 100`` for a quick smoke
test, or omit it for the configured 5,000-account dataset.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .generate_accounts import generate_accounts

START, END, SEED, LABEL_DAYS = date(2025, 1, 1), date(2026, 1, 30), 42, 30
HOLIDAYS = {date(2025, 1, 1), date(2025, 4, 30), date(2025, 5, 1), date(2025, 9, 2), date(2026, 1, 1)}
SYMBOLS = [f"SYN{i:03d}" for i in range(1, 31)]

def sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-np.clip(x, -30, 30))))

def generate_prices(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    prices = rng.uniform(10_000, 150_000, len(SYMBOLS))
    d = START
    while d <= END:
        market = d.weekday() < 5 and d not in HOLIDAYS
        for i, symbol in enumerate(SYMBOLS):
            if market:
                prices[i] = np.clip(prices[i] * np.exp(rng.normal(.0002, .02)), 1_000, 500_000)
            rows.append({"business_date": d, "symbol": symbol, "price": round(float(prices[i]), 2)})
        d += timedelta(days=1)
    return pd.DataFrame(rows)

def generate_events(accounts: pd.DataFrame, prices: pd.DataFrame, seed: int = SEED):
    tx, cf, balances = [], [], []
    price_map = {(r.business_date, r.symbol): r.price for r in prices.itertuples()}
    for row in accounts.itertuples(index=False):
        rng = np.random.default_rng(np.random.SeedSequence([seed, int(row.master_account)]))
        debt = cash = 0.0
        asset = float(np.clip(np.exp(rng.normal(17.5, .7)), 10_000_000, 500_000_000))
        cash = asset * float(rng.uniform(.2, .6))
        last_buys: list[tuple[date, float]] = []
        seq_day = {}
        d = START
        while d <= END:
            if d < row.account_open_date or (row.account_close_date is not None and pd.notna(row.account_close_date) and d > row.account_close_date):
                d += timedelta(days=1); continue
            market = d.weekday() < 5 and d not in HOLIDAYS
            day_tx = []
            dormant = row.dormant_start_date is not None and pd.notna(row.dormant_start_date) and d >= row.dormant_start_date
            if market and not dormant and row.account_status != "CLOSED":
                p = sigmoid(-2.4 + 1.6*row.trading_propensity + .5*row.activity_stability + rng.normal(0, .25))
                n = int(rng.poisson(np.clip(.2 + 5*p, .0, 20))) if rng.random() < p else 0
                for k in range(n):
                    symbol = str(rng.choice(SYMBOLS)); side = "BUY" if rng.random() < .55 else "SELL"
                    qty = int(np.clip(rng.lognormal(6, .8), 10, 100_000)); price = price_map[(d, symbol)]
                    seq_day[d] = seq_day.get(d, 0) + 1
                    day_tx.append({"transaction_id": f"TXN-{row.master_account}-{d:%Y%m%d}-{seq_day[d]:05d}", "master_account": row.master_account, "symbol": symbol, "transaction_time": f"{d}T{9 + rng.random()*5.75:05.2f}:00+07:00", "side": side, "quantity": qty, "price": price, "trade_value": int(round(qty*price))})
                    if side == "BUY": last_buys.append((d, qty*price))
                tx.extend(day_tx)
            recent = [(x, v) for x, v in last_buys if (d-x).days <= 30]
            last_buys = recent
            activity = .5*min(sum(1 for x,_ in recent)/30, 1) + .5*min(sum(v for _,v in recent)/50_000_000, 1)
            repay = 0.0
            if debt > 0 and not dormant and rng.random() < .05:
                repay = debt if debt < 1_000_000 else min(debt, max(1_000_000, round(debt*float(np.clip(rng.normal(.15,.05), .01, .5)))))
                cf.append({"cash_flow_id": f"CF-{row.master_account}-{d:%Y%m%d}-001", "master_account": row.master_account, "event_date": d, "status": "POSTED", "fk_product": "MARGIN_MBS", "fk_event_type": "REPAYMENT", "fk_transaction_type": "REPAYMENT", "amount": int(repay)})
                debt -= repay; cash -= repay
            p_margin = sigmoid(-4.6 + 1.4*row.margin_affinity + activity + .6*row.wealth_level + .4*row.risk_appetite + rng.normal(0,.2))
            if day_tx and any(x["side"] == "BUY" for x in day_tx) and not dormant and rng.random() < p_margin:
                amount = int(max(1_000_000, min(100_000_000, round(rng.uniform(.2,.6)*max(1_000_000, asset*.7)-debt))))
                product = "MARGIN_MBS" if rng.random() < .7 else "MBLINK"
                status = "CANCELLED" if rng.random() < .02 else "POSTED"
                cf.append({"cash_flow_id": f"CF-{row.master_account}-{d:%Y%m%d}-002", "master_account": row.master_account, "event_date": d, "status": status, "fk_product": product, "fk_event_type": "DISBURSEMENT", "fk_transaction_type": "INTERM_DELIVER" if product == "MARGIN_MBS" else "TLO_DELIVER_CASH", "amount": amount})
                if status == "POSTED": debt += amount; cash += amount
            buy = sum(x["trade_value"] for x in day_tx if x["side"] == "BUY"); sell = sum(x["trade_value"] for x in day_tx if x["side"] == "SELL")
            cash = max(0, cash + sell - buy); asset = max(0, asset + buy - sell)
            limit = 0 if dormant or asset <= 0 else int(np.clip(asset*.7*.5, 5_000_000, 500_000_000))
            balances.append({"master_account": row.master_account, "business_date": d, "cash_balance": int(round(cash)), "asset_value": int(round(asset)), "margin_debt": int(round(max(0,debt))), "margin_limit": limit, "margin_utilization_ratio": None if limit == 0 else round(debt/limit, 6), "margin_status": "NO_MARGIN" if debt == 0 else ("OVERDUE" if debt > limit else "ACTIVE")})
            d += timedelta(days=1)
    return pd.DataFrame(tx), pd.DataFrame(cf), pd.DataFrame(balances)

def build_training(accounts, tx, cf, balances):
    # Convert timestamps once, then index each account's events once.  The old
    # implementation filtered the complete tx/cf frames for every snapshot.
    tx = tx.copy(); tx["event_date"] = pd.to_datetime(tx["transaction_time"]).dt.date
    balances_by_account = {k: g.sort_values("business_date") for k, g in balances.groupby("master_account", sort=False)}
    tx_by_account = {k: g.sort_values("event_date") for k, g in tx.groupby("master_account", sort=False)}
    cf_by_account = {k: g.sort_values("event_date") for k, g in cf.groupby("master_account", sort=False)}
    rows = []
    for account, bg in balances_by_account.items():
        tg = tx_by_account.get(account, tx.iloc[0:0])
        cg = cf_by_account.get(account, cf.iloc[0:0])
        tx_dates = np.array(tg["event_date"].tolist(), dtype="datetime64[D]")
        tx_values = tg["trade_value"].to_numpy(dtype=np.int64, copy=False) if len(tg) else np.array([], dtype=np.int64)
        cf_dates = np.array(cg["event_date"].tolist(), dtype="datetime64[D]")
        valid_cf_dates = np.sort(np.array(cg.loc[(cg.status == "POSTED") & (cg.fk_event_type == "DISBURSEMENT"), "event_date"].tolist(), dtype="datetime64[D]")) if len(cg) else np.array([], dtype="datetime64[D]")
        for b in bg.itertuples(index=False):
            if b.business_date < date(2025, 2, 1) or b.business_date > date(2025, 12, 31):
                continue
            day = np.datetime64(b.business_date)
            lo = np.searchsorted(tx_dates, day - np.timedelta64(30, "D"), side="left")
            hi = np.searchsorted(tx_dates, day, side="left")
            event_lo = np.searchsorted(valid_cf_dates, day + np.timedelta64(1, "D"), side="left")
            event_hi = np.searchsorted(valid_cf_dates, day + np.timedelta64(LABEL_DAYS, "D"), side="right")
            rows.append({"master_account": b.master_account, "report_date": b.business_date, "trade_count_30d": int(hi - lo), "trade_amount_30d": int(tx_values[lo:hi].sum()), "cash_balance": b.cash_balance, "asset_value": b.asset_value, "margin_debt": b.margin_debt, "margin_limit": b.margin_limit, "margin_utilization_ratio": b.margin_utilization_ratio, "label": int(event_hi > event_lo)})
    return pd.DataFrame(rows)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--num-accounts',type=int,default=5000); ap.add_argument('--output',type=Path,default=Path('data/generated')); args=ap.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    a=generate_accounts(args.num_accounts); p=generate_prices(); t,c,b=generate_events(a,p); tr=build_training(a,t,c,b)
    for name,frame in [('customer_account',a),('stock_price_daily',p),('stock_transaction',t),('margin_cash_flow',c),('margin_balance_daily',b),('training_dataset',tr)]: frame.to_parquet(args.output/f'{name}.parquet',index=False)
    (args.output/'metadata.json').write_text(json.dumps({'seed':SEED,'num_accounts':args.num_accounts,'generated_at':datetime.now().isoformat(),'rows':{n:len(f) for n,f in [('accounts',a),('prices',p),('transactions',t),('cashflows',c),('balances',b),('training',tr)]}},indent=2),encoding='utf-8')
    print(f'generated {args.num_accounts:,} accounts; training rows={len(tr):,}; positives={tr.label.mean() if len(tr) else 0:.3%}')
if __name__=='__main__': main()
