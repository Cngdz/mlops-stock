"""Step 6 iceberg_maintenance (weekly): keep 12 months, expire old snapshots, delete orphan files.

  python -m features.maintenance --retention-months 12 --expire-snapshots --remove-orphans
  python -m features.maintenance --remove-orphans --dry-run       # list what would be deleted
  python -m features.maintenance --keep-training-runs 12           # PVC: drop older build_training runs

Retention counts back from the latest COMPLETE report_date, not from the wall clock: with the synthetic data the
latest day is 2026-01-30, and a wall-clock cutoff would delete everything. Every overwrite (re-run of a day) leaves
the replaced files behind, still referenced by older snapshots; expiring those snapshots unreferences them and the
orphan pass deletes them. Files younger than maintenance.orphan_min_age_days are never touched: they may belong to
a write that has not committed yet.
Training runs on the PVC (one per <usecase>_train DAG run) are pruned to the newest N; the run that
data/features/current.json points to is always kept.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil

import pandas as pd
from pyarrow import fs as pafs
from pyiceberg.catalog import Catalog
from pyiceberg.exceptions import NoSuchTableError
from pyiceberg.expressions import LessThanOrEqual
from pyiceberg.table import Table

from features import status
from features.common import FS_TABLES, POINTER, RUNS_ROOT, STATE_TABLE, catalog, load_settings, table_name

TABLES = FS_TABLES + [STATE_TABLE]


def cutoff_for(latest: dt.date, months: int) -> dt.date:
    """Last report_date to delete: everything up to `months` before the latest day. Pure."""
    return (pd.Timestamp(latest) - pd.DateOffset(months=months)).date()


def tables(cat: Catalog) -> list[Table]:
    out = []
    for name in TABLES:
        try:
            out.append(cat.load_table(table_name(name)))
        except NoSuchTableError:
            pass
    return out


def drop_old_partitions(cat: Catalog, months: int, statuses: status.StatusStore, dry_run: bool) -> dt.date | None:
    latest = statuses.latest_complete()
    if latest is None:
        print("retention: no COMPLETE day yet, nothing to drop")
        return None
    cutoff = cutoff_for(latest, months)
    for table in tables(cat):
        old = [p for p in table.inspect.partitions().to_pylist() if p["partition"]["report_date"] <= cutoff]
        print(f"retention {table.name()}: {len(old)} partitions <= {cutoff} (latest {latest})")
        if old and not dry_run:
            table.delete(LessThanOrEqual("report_date", cutoff.isoformat()))
    if not dry_run:
        statuses.delete_before(cutoff + dt.timedelta(days=1))
    return cutoff


def expire_snapshots(cat: Catalog, max_age_days: int, dry_run: bool) -> None:
    older_than = dt.datetime.now(dt.UTC) - dt.timedelta(days=max_age_days)
    for table in tables(cat):
        current = table.current_snapshot()
        old = [s for s in table.snapshots() if s.timestamp_ms < older_than.timestamp() * 1000
               and (current is None or s.snapshot_id != current.snapshot_id)]
        print(f"expire {table.name()}: {len(old)} of {len(table.snapshots())} snapshots older than {max_age_days} days")
        if old and not dry_run:
            table.maintenance.expire_snapshots().older_than(older_than).commit()


def path_key(path: str) -> str:
    """Compare locations without scheme: s3://warehouse/x and warehouse/x (pyarrow listing) are the same file."""
    return path.replace("\\", "/").split("://", 1)[-1].lstrip("/")


def referenced(table: Table) -> set[str]:
    """Every file a snapshot still kept can reach: data/delete files, manifests, manifest lists, metadata JSONs."""
    files = set(table.inspect.all_files().column("file_path").to_pylist())
    files |= set(table.inspect.all_manifests().column("path").to_pylist())
    files |= {s.manifest_list for s in table.snapshots()}
    files |= {table.metadata_location} | {e.metadata_file for e in table.metadata.metadata_log}
    return {path_key(f) for f in files}


def filesystem(table: Table) -> tuple[pafs.FileSystem, str]:
    scheme, netloc, path = table.io.parse_location(table.location())
    fs = table.io.fs_by_scheme(scheme, netloc)
    return fs, (f"{netloc}{path}" if scheme in ("s3", "s3a", "s3n") else path)


def remove_orphans(cat: Catalog, min_age_days: int, dry_run: bool) -> int:
    newest = dt.datetime.now(dt.UTC) - dt.timedelta(days=min_age_days)
    removed = 0
    for table in tables(cat):
        keep = referenced(table)
        fs, root = filesystem(table)
        listing = fs.get_file_info(pafs.FileSelector(root, recursive=True))
        orphans = [f for f in listing if f.type == pafs.FileType.File and path_key(f.path) not in keep
                   and f.mtime is not None and f.mtime.astimezone(dt.UTC) < newest]
        size = sum(f.size or 0 for f in orphans)
        print(f"orphans {table.name()}: {len(orphans)} files, {size / 2**20:.1f} MiB (older than {min_age_days} days)")
        if not dry_run:
            for f in orphans:
                fs.delete_file(f.path)
        removed += len(orphans)
    return removed


def prune_training_runs(keep: int, dry_run: bool) -> list[str]:
    """Delete all but the newest `keep` run dirs (by modification time), never the current one."""
    if not RUNS_ROOT.exists():
        return []
    current = json.loads(POINTER.read_text(encoding="utf-8"))["run_id"] if POINTER.exists() else None
    runs = sorted((d for d in RUNS_ROOT.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    old = [d for d in runs[keep:] if d.name != current]
    print(f"training runs: {len(runs)} on disk, deleting {len(old)} (keep {keep} + current {current})")
    if not dry_run:
        for d in old:
            shutil.rmtree(d)
    return [d.name for d in old]


def main() -> None:
    settings = load_settings()["maintenance"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--retention-months", type=int, help=f"drop partitions (config: {settings['retention_months']})")
    parser.add_argument("--expire-snapshots", action="store_true")
    parser.add_argument("--remove-orphans", action="store_true")
    parser.add_argument("--keep-training-runs", type=int, help="prune build_training runs on the PVC to the newest N")
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    args = parser.parse_args()
    if not (args.retention_months or args.expire_snapshots or args.remove_orphans or args.keep_training_runs):
        parser.error("nothing to do: give --retention-months, --expire-snapshots, --remove-orphans "
                     "and/or --keep-training-runs")
    cat = catalog()
    if args.retention_months:
        drop_old_partitions(cat, args.retention_months, status.store(), args.dry_run)
    if args.expire_snapshots:
        expire_snapshots(cat, settings["snapshot_max_age_days"], args.dry_run)
    if args.remove_orphans:
        remove_orphans(cat, settings["orphan_min_age_days"], args.dry_run)
    if args.keep_training_runs:
        prune_training_runs(args.keep_training_runs, args.dry_run)


if __name__ == "__main__":
    main()
