"""Deterministic pilot calibration using the same Day 4 feature/label pipeline."""
import argparse
import json
from pathlib import Path

import duckdb
from data_generation.generate_accounts import generate_accounts
from data_generation.generate_all import generate_prices, generate_events, END, SEED
from scripts.day4_feature_engineering import normalize, build, records


def measure(accounts, transactions, cashflows, balances, campaigns):
    with duckdb.connect() as con:
        con.execute("SET TimeZone='Asia/Ho_Chi_Minh'")
        con.execute("SET threads=4")
        for name, frame in [('customer_account',accounts), ('stock_transaction',transactions), ('margin_cash_flow',cashflows), ('margin_balance_daily',balances), ('customer_campaign',campaigns)]:
            con.register('frame',frame)
            con.execute(f'CREATE TABLE {name} AS SELECT * FROM frame')
            con.unregister('frame')
        normalize(con)
        build(con,END)
        rates = records(con, 'SELECT margin_segment, count(*) AS rows, avg(loan_label_next) AS positive_rate FROM candidate GROUP BY ALL ORDER BY 1')
        shares = records(con, 'SELECT margin_segment,count(*)::DOUBLE/(SELECT count(*) FROM candidate WHERE report_date=(SELECT max(report_date) FROM candidate)) AS share FROM candidate WHERE report_date=(SELECT max(report_date) FROM candidate) GROUP BY ALL ORDER BY 1')
        offers = records(con, 'SELECT offer_type, count(*) AS rows, avg(campaign_response_label_14d) AS response_rate FROM campaign_candidate GROUP BY ALL ORDER BY 1')
    return {r['margin_segment']:r['positive_rate'] for r in rates}, shares, offers


def calibrate(output, pilot_size=500):
    accounts, prices = generate_accounts(pilot_size), generate_prices()
    target = {'nu':.15,'lu':.25,'au':.35}
    lower, upper = {s:-7. for s in target}, {s:-2. for s in target}
    intercepts = {s:(lower[s]+upper[s])/2 for s in target}
    history = []
    result = {'status':'FAIL','seed':SEED,'pilot_size':pilot_size,'repayment_probability':.10,'targets':target,'tolerance':.03,'history':history}
    for iteration in range(1,9):
        # Decisions 14.6: pilot runs with campaigns enabled, same as the full dataset.
        transactions,cashflows,balances,campaigns = generate_events(accounts,prices,intercepts=intercepts)
        rates, shares, offers = measure(accounts,transactions,cashflows,balances,campaigns)
        record = {'iteration':iteration,'intercepts':intercepts.copy(),'rates':rates,'last_snapshot_shares':shares,'campaign_response_by_offer':offers}
        history.append(record)
        print(json.dumps(record),flush=True)
        if all(s in rates and abs(rates[s]-target[s])<=.03 for s in target):
            result['status']='PASS'
            break
        if any(s not in rates for s in target):
            break
        if iteration < 8:
            for s in target:
                if abs(rates[s]-target[s])<=.03:
                    continue
                if rates[s]<target[s]:
                    lower[s]=intercepts[s]
                else:
                    upper[s]=intercepts[s]
                intercepts[s]=(lower[s]+upper[s])/2
    result['intercepts']=intercepts
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result['status']=='PASS'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('data/generation_calibration.json'))
    args=parser.parse_args()
    raise SystemExit(0 if calibrate(args.output) else 2)
