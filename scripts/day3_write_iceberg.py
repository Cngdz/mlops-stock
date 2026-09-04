from pathlib import Path
import argparse

import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.catalog import load_catalog


ROOT = Path(__file__).resolve().parents[1]

# Bộ dữ liệu đầy đủ để đóng deliverable ngày 3.
INPUT_DIR = ROOT / "data" / "generated" / "full"

CATALOG_DIR = ROOT / "data" / "catalog_full"
CATALOG_DB = CATALOG_DIR / "pyiceberg.db"
WAREHOUSE = ROOT / "data" / "warehouse_full"

TABLE_NAMES = [
    "customer_account",
    "stock_transaction",
    "margin_balance_daily",
    "margin_cash_flow",
]


def normalize_timestamp_precision(table: pa.Table) -> pa.Table:
    """Store aware timestamps as UTC microseconds without changing the instant."""
    fields = []
    changed = False
    for field in table.schema:
        if pa.types.is_timestamp(field.type) and (field.type.unit != "us" or field.type.tz not in (None, "UTC")):
            fields.append(
                pa.field(
                    field.name,
                    pa.timestamp("us", tz="UTC" if field.type.tz else None),
                    nullable=field.nullable,
                    metadata=field.metadata,
                )
            )
            changed = True
        else:
            fields.append(field)

    if not changed:
        return table

    target_schema = pa.schema(fields, metadata=table.schema.metadata)
    return table.cast(target_schema, safe=True)


def create_catalog():
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    WAREHOUSE.mkdir(parents=True, exist_ok=True)

    return load_catalog(
        "local",
        **{
            "type": "sql",
            "uri": f"sqlite:///{CATALOG_DB.as_posix()}",
            # Dùng đường dẫn Windows thuần; một số bản PyArrow diễn giải
            # file:///C:/... thành /C:/... và gây WinError 123.
            "warehouse": str(WAREHOUSE),
        },
    )


def main():
    parser = argparse.ArgumentParser(description="Ingest sources into an explicit Iceberg namespace.")
    parser.add_argument('--input-dir', type=Path, default=INPUT_DIR)
    parser.add_argument('--namespace', default='raw')
    args = parser.parse_args()
    catalog = create_catalog()

    if not catalog.namespace_exists(args.namespace):
        catalog.create_namespace(args.namespace)
        print(f"Created namespace: {args.namespace}")

    for table_name in TABLE_NAMES:
        identifier = f"{args.namespace}.{table_name}"
        parquet_path = args.input_dir / f"{table_name}.parquet"

        if not parquet_path.exists():
            raise FileNotFoundError(parquet_path)

        arrow_table = normalize_timestamp_precision(pq.read_table(parquet_path))

        if catalog.table_exists(identifier):
            # Không append lại để tránh nhân đôi dữ liệu khi chạy lại script.
            print(f"Skipped existing table: {identifier}")
            continue

        iceberg_table = catalog.create_table(
            identifier=identifier,
            schema=arrow_table.schema,
            properties={"format-version": "2"},
        )

        iceberg_table.append(arrow_table)

        print(
            f"Created {identifier}: "
            f"{arrow_table.num_rows:,} rows, "
            f"{arrow_table.num_columns} columns"
        )


if __name__ == "__main__":
    main()
