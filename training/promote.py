"""Day 7 approval step: move a use case's @staging versions to @production, all segments at once.

Usage:  python -m training.promote --usecase loan_propensity            # show what would change
        python -m training.promote --usecase loan_propensity --approve  # set @production

Refuses unless every segment's @staging version comes from the same training run and carries
promotion_gate PASS or BASELINE_PASS. Running with --approve IS the human approval; who/when is
recorded on the versions. Rollback (Day 10) = point @production back at an older version.
"""
from __future__ import annotations

import argparse
import getpass
from datetime import datetime, timezone

from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from training import registry
from training.config import load_usecases

APPROVABLE = {"PASS", "BASELINE_PASS"}


def plan(client: MlflowClient, usecase: str) -> list[dict]:
    uc = load_usecases()[usecase]
    rows = []
    for segment in uc.segments or ["all"]:
        name = registry.model_name(usecase, segment)
        try:
            staging = client.get_model_version_by_alias(name, registry.STAGING)
        except MlflowException:
            raise SystemExit(f"{name}: no @staging version; train first")
        current = registry.production_version(client, name)
        rows.append({"name": name, "segment": segment, "staging": staging,
                     "production": current.version if current else None})
    return rows


def check(rows: list[dict]) -> list[str]:
    problems = []
    runs = {r["staging"].tags.get("train_run_id") for r in rows}
    if len(runs) != 1:
        problems.append(f"@staging versions come from different training runs {sorted(map(str, runs))}")
    for r in rows:
        gate = r["staging"].tags.get("promotion_gate")
        if gate not in APPROVABLE:
            problems.append(f"{r['name']} v{r['staging'].version}: gate {gate} ({r['staging'].tags.get('gate_reason')})")
    return problems


def promote(client: MlflowClient, usecase: str, approve: bool) -> bool:
    rows = plan(client, usecase)
    for r in rows:
        print(f"{r['name']:24s} @production v{r['production']} -> v{r['staging'].version} "
              f"(gate {r['staging'].tags.get('promotion_gate')}, auc {float(r['staging'].tags['test_roc_auc']):.4f})")
    problems = check(rows)
    if problems:
        print("REFUSED:\n  " + "\n  ".join(problems))
        return False
    if all(r["production"] == r["staging"].version for r in rows):
        print("already in production, nothing to do")
        return True
    if not approve:
        print("gate OK. Re-run with --approve to set @production.")
        return True
    stamp = {"approved_by": getpass.getuser(), "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for r in rows:
        version = r["staging"].version
        for key, value in {**stamp, "replaced_version": str(r["production"])}.items():
            client.set_model_version_tag(r["name"], version, key, value)
        client.set_registered_model_alias(r["name"], registry.PRODUCTION, version)
    print(f"@production updated for {len(rows)} models")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--usecase", required=True)
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    ok = promote(registry.configure(), args.usecase, args.approve)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
