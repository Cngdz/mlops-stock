"""Create data/analytics/qoredb.duckdb: views over the current parquet files, for GUI clients (QoreDB)."""
import json
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/analytics/qoredb.duckdb"


def main():
    pointer = json.loads((ROOT / "data/features/current.json").read_text(encoding="utf-8"))
    source = ROOT / "data/generated" / json.loads((ROOT / "data/source_current.json").read_text(encoding="utf-8"))["namespace"].removeprefix("raw_")
    features = ROOT / "data/features/day4_runs" / pointer["run_id"]
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    for schema, folder in [("raw", source), ("features", features)]:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for path in sorted(folder.glob("*.parquet")):
            con.execute(f"CREATE OR REPLACE VIEW {schema}.{path.stem} AS SELECT * FROM read_parquet('{path.as_posix()}')")
            print(f"{schema}.{path.stem}: {con.execute(f'SELECT count(*) FROM {schema}.{path.stem}').fetchone()[0]:,}")
    con.close()
    print(f"\nDuckDB file: {DB}")


if __name__ == "__main__":
    main()
