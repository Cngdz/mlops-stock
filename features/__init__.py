"""Gold -> Feature Store, one report_date partition per day (docs chapter 3).

Daily steps, each a module with its own CLI (one Airflow task each, DAG feature_store_daily):

  check_source  Gold has day T and the expected schema
  compute       Gold rows of T-30..T + carried state of T-1 -> 6 fs_* tables + state for T (staging parquet)
  write         overwrite partition report_date = T of features.fs_* and features.fs_state, drop the staging dir
  quality       contract + quality checks on partition T only
  publish       control.fs_status(T) = COMPLETE: the marker the predict DAGs wait for
  maintenance   weekly: drop partitions older than 12 months, expire snapshots, delete orphan files

Plus backfill (all of the above over a date range, month by month) and build_training (fs_* partitions + labels
from Gold -> a versioned training run on the PVC that training.train reads).
"""
