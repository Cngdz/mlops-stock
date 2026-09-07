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


def ingest_sources(catalog, input_dir: Path, namespace: str):
    """Preflight the complete source batch before creating any table.

    A reused namespace could mix two generator runs. Refuse all collisions,
    including an incomplete previous attempt; the caller must choose a new name.
    """
    paths = {name: input_dir / f"{name}.parquet" for name in TABLE_NAMES}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing source files: {missing}")
    if catalog.namespace_exists(namespace):
        existing = [f"{namespace}.{name}" for name in TABLE_NAMES
                    if catalog.table_exists(f"{namespace}.{name}")]
        if existing:
            raise FileExistsError(f"Use a new namespace; source tables already exist: {existing}")
    # Read every footer up front so a missing/corrupt schema cannot create a partial batch.
    for path in paths.values():
        schema = pq.read_schema(path)
        normalize_timestamp_precision(pa.Table.from_batches([], schema=schema))

    if not catalog.namespace_exists(namespace):
        catalog.create_namespace(namespace)
        print(f"Created namespace: {namespace}")

    for table_name, parquet_path in paths.items():
        identifier = f"{namespace}.{table_name}"
        arrow_table = normalize_timestamp_precision(pq.read_table(parquet_path))
        iceberg_table = catalog.create_table(
            identifier=identifier,
            schema=arrow_table.schema,
            properties={"format-version": "2"},
        )
        iceberg_table.append(arrow_table)
        print(f"Created {identifier}: {arrow_table.num_rows:,} rows, {arrow_table.num_columns} columns")


def main():
    parser = argparse.ArgumentParser(description="Ingest sources into an explicit Iceberg namespace.")
    parser.add_argument('--input-dir', type=Path, default=INPUT_DIR)
    parser.add_argument('--namespace', default='raw')
    args = parser.parse_args()
    ingest_sources(create_catalog(), args.input_dir, args.namespace)


if __name__ == "__main__":
    main()
