"""One-off: copy the 8 Gold tables from the local SQLite catalog (data/catalog_full) into the lakehouse catalog.

  .\\infra\\port-forward.ps1                                   # Postgres 5432 + MinIO 9000
  uv run python scripts/migrate_gold.py                        # source namespace from data/source_current.json
  uv run python scripts/migrate_gold.py --source-namespace raw_day4_v3e --replace

Target: namespace `gold` of the Postgres catalog iceberg_catalog, data in s3://warehouse/gold.db/, so the feature
pods read Gold the same way they read fs_* (the old catalog stores C:\\ paths a pod cannot open). Daily tables are
written one calendar month per append, so every data file covers one month and its min/max statistics let a scan of
a 30-day window skip the other months (month partitioning would do the same but needs the pyiceberg-core extra).
Gold itself stays out of scope (docs 1.4): in production an upstream job keeps these tables up to date.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
from pyiceberg.catalog import load_catalog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.common import gold_name  # noqa: E402
from features.gold import SOURCE_SCHEMA  # noqa: E402
from pipeline import catalog as lakehouse  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MONTH_COLUMN = {"margin_balance_daily": "business_date", "portfolio_holding_daily": "business_date",
                "stock_price_daily": "business_date", "margin_cash_flow": "event_date",
                "stock_transaction": "transaction_time", "customer_campaign": "sent_at"}


def by_month(data: pa.Table, column: str) -> list[pa.Table]:
    """Slices of one calendar month each (UTC month for timestamps), oldest first."""
    values = data.column(column)
    key = pc.add(pc.multiply(pc.year(values), 100), pc.month(values))
    return [data.filter(pc.equal(key, month)) for month in sorted(set(key.to_pylist()))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-namespace", help="default: data/source_current.json")
    parser.add_argument("--replace", action="store_true", help="drop and re-create tables that already exist")
    args = parser.parse_args()
    namespace = args.source_namespace or json.loads((ROOT / "data/source_current.json").read_text())["namespace"]
    source = load_catalog("local", **{"type": "sql", "uri": f"sqlite:///{(ROOT / 'data/catalog_full/pyiceberg.db').as_posix()}",
                                      "warehouse": str(ROOT / "data/warehouse_full")})
    target = lakehouse.load()
    gold_namespace = gold_name("x").split(".")[0]
    lakehouse.ensure_namespace(target, gold_namespace)
    for name in SOURCE_SCHEMA:
        identifier = gold_name(name)
        if target.table_exists(identifier):
            if not args.replace:
                print(f"{identifier}: exists, skipped (--replace to copy again)")
                continue
            target.drop_table(identifier)
        data = source.load_table(f"{namespace}.{name}").scan().to_arrow()
        table = target.create_table(identifier, schema=data.schema,
                                    properties={"gold.source": f"{namespace}.{name}"})
        for part in by_month(data, MONTH_COLUMN[name]) if name in MONTH_COLUMN else [data]:
            table.append(part)
        copied = target.load_table(identifier).scan().count()
        if copied != data.num_rows:
            raise RuntimeError(f"{identifier}: wrote {data.num_rows} rows, read back {copied}")
        print(f"{namespace}.{name} -> {identifier}: {copied:,} rows", flush=True)


if __name__ == "__main__":
    main()
