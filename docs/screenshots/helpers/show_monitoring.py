"""Liet ke so dong theo partition cua cac bang Iceberg trong namespace monitoring (pred_, drift_, eval_).

Can port-forward Postgres 5432 va MinIO 9000 (.\infra\port-forward.ps1).
Chay (tu thu muc goc repo):  uv run python docs/screenshots/helpers/show_monitoring.py
"""
import os
import sys

sys.path.insert(0, os.getcwd())
from pipeline import catalog  # noqa: E402

PARTITION = {f"{kind}_{usecase}": key
             for usecase in ("loan_propensity", "overdue_risk", "campaign_response")
             for kind, key in (("pred", "score_date"), ("drift", "current_date"), ("eval", "window_end"))}
cat = catalog.load()
for name, key in PARTITION.items():
    try:
        df = cat.load_table(f"monitoring.{name}").scan().to_pandas()
    except Exception as err:  # bang chua ton tai
        print(f"\n== monitoring.{name}: khong doc duoc ({err})")
        continue
    print(f"\n== monitoring.{name}  (partition theo {key})  tong dong = {len(df):,}")
    print(df.groupby(key).size().tail(10).to_string())
