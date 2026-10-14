"""Print the key numbers of the generated sources and the current approved feature run."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()

    gen = json.loads((ROOT / args.source_dir / "generation_run.json").read_text(encoding="utf-8"))
    print(f"generator_version={gen.get('generator_version')} seed={gen.get('seed')} accounts={gen.get('num_accounts')}")
    for name, rows in gen.get("rows", {}).items():
        print(f"  {name:<26}{rows:>12,}")
    print("  portfolio vs asset_value:", gen.get("portfolio_vs_asset_value"))

    pointer = json.loads((ROOT / "data/features/current.json").read_text(encoding="utf-8"))
    report = json.loads((Path(pointer["path"]) / "quality_report.json").read_text(encoding="utf-8"))
    print(f"\nfeature run {report.get('run_id')} status={report.get('status')} rows={report.get('rows'):,}")
    failed = [c for c in report.get("checks", []) if not c.get("passed")]
    print(f"checks: {len(report.get('checks', [])) - len(failed)}/{len(report.get('checks', []))} passed")
    for c in failed:
        print(f"  FAIL {c['check']}: observed={c.get('observed')} expected={c.get('expected')}")

    print(f"scoring features (fs_*): rows={report.get('scoring_rows')} dates={report.get('scoring_report_date_range')}")
    print(f"\n[loan] positive rate {pct(report.get('positive_rate'))}")
    for r in report.get("by_segment", []):
        print(f"  {r['margin_segment']}: rows={r['rows']:,} pos={pct(r['positive_rate'])}")
    print("  last snapshot shares:", {k: pct(v) for k, v in report.get("last_snapshot_shares", {}).items()})

    print(f"\n[overdue] positive rate on eligible rows {pct(report.get('overdue_positive_rate'))}")
    for r in report.get("overdue_by_split_segment", []):
        print(f"  {r['split']:<10} {r['margin_segment']}: rows={r['rows']:,} pos={pct(r['positive_rate'])}")

    print("feast label tables:", report.get("feast_label_rows"))
    camp = report.get("campaign", {})
    print(f"\n[campaign] positive rate {pct(camp.get('positive_rate'))} lift={camp.get('lift')} offer_spread={camp.get('offer_spread')}")
    for key in ("by_split", "by_offer"):
        for r in camp.get(key, []) or []:
            print(f"  {key}: {r}")
    feast_summary(ROOT / "data/features/day4_runs" / pointer["run_id"])


def feast_summary(run_dir):
    path = run_dir / "feast_check.json"
    if not path.exists():
        print("\n[feast] not checked yet (run scripts/day5_feast_check.py)")
        return
    f = json.loads(path.read_text(encoding="utf-8"))
    failed = [c for c in f["checks"] if not c["passed"]]
    print(f"\n[feast] {f['status']} accounts={f['accounts']} rows={f['entity_rows']} seconds={f['seconds']}")
    for c in failed:
        print(f"  FAIL {c['check']}: observed={c['observed']} expected={c['expected']}")


if __name__ == "__main__":
    main()
