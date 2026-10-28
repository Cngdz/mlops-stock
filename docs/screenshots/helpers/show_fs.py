"""In ra so dong, so ngay va khoang report_date cua 6 bang fs_* (Iceberg) va trang thai control.fs_status.

Can port-forward Postgres 5432 va MinIO 9000 (.\\infra\\port-forward.ps1).
Chay (tu thu muc goc repo):  uv run python docs/screenshots/helpers/show_fs.py
Doc theo metadata Iceberg (inspect.partitions), khong quet du lieu.
"""
import os
import sys

sys.path.insert(0, os.getcwd())
from features import status  # noqa: E402
from features.common import FS_TABLES, catalog, table_name  # noqa: E402

cat = catalog()
for name in FS_TABLES:
    parts = cat.load_table(table_name(name)).inspect.partitions().to_pylist()
    days = sorted(p["partition"]["report_date"] for p in parts)
    rows = sum(p["record_count"] for p in parts)
    print(f"{name:22s} dong={rows:>10,}  so_ngay={len(days):>4}  {days[0] if days else '-'} .. {days[-1] if days else '-'}")
latest = status.store().latest_complete()
print(f"ngay COMPLETE moi nhat trong control.fs_status: {latest}")
