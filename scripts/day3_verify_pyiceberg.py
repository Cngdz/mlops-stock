from pathlib import Path

from pyiceberg.catalog import load_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG_DB = ROOT / "data" / "catalog_full" / "pyiceberg.db"
WAREHOUSE = ROOT / "data" / "warehouse_full"

catalog = load_catalog(
    "local",
    **{
        "type": "sql",
        "uri": f"sqlite:///{CATALOG_DB.as_posix()}",
        "warehouse": str(WAREHOUSE),
    },
)

print("Namespaces:", catalog.list_namespaces())
tables = catalog.list_tables("raw")
print("Tables:", tables)

expected = {
    "raw.customer_account",
    "raw.stock_transaction",
    "raw.margin_balance_daily",
    "raw.margin_cash_flow",
}
actual = {".".join(identifier) for identifier in tables}
missing = expected - actual
if missing:
    raise RuntimeError(f"Missing tables: {sorted(missing)}")

for identifier in tables:
    table = catalog.load_table(identifier)
    print(f"\n{'.'.join(identifier)}")
    print("  metadata:", table.metadata_location)
    print("  schema:")
    print(table.schema())
