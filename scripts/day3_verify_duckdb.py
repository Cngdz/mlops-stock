from pathlib import Path

import duckdb
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

con = duckdb.connect()
con.execute("INSTALL iceberg")
con.execute("LOAD iceberg")
print("DuckDB iceberg extension: loaded")

for identifier in catalog.list_tables("raw"):
    name = ".".join(identifier)
    table = catalog.load_table(identifier)
    metadata_path = table.metadata_location.replace("'", "''")

    count = con.execute(
        f"SELECT count(*) FROM iceberg_scan('{metadata_path}')"
    ).fetchone()[0]
    sample = con.execute(
        f"SELECT * FROM iceberg_scan('{metadata_path}') LIMIT 3"
    ).fetchdf()

    print(f"\n{name}: {count:,} rows")
    print(sample)

    if count <= 0:
        raise RuntimeError(f"Iceberg table is empty: {name}")

print("\nDuckDB verification: OK")
