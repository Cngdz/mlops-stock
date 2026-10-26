"""Deployer entry point.

In the cluster it runs as Deployment mlops/deployer (deployer/k8s/deployer.yaml) with --loop: GITHUB_TOKEN from
Secret deployer-github, MLflow and MinIO through their service DNS names, kubectl through the pod's service
account (read-only on InferenceServices). Logs: kubectl -n mlops logs -f deploy/deployer

From a workstation (debugging, dry runs) with the port-forwards of infra/port-forward.ps1:
  uv run --env-file .env python -m deployer --dry-run             # show what would be committed
  uv run --env-file .env python -m deployer                       # one round
Never run a second --loop next to the Deployment: two writers race on the same files.
"""
from __future__ import annotations

import argparse
import time
import traceback
from pathlib import Path

import yaml

from deployer.sources import ArtifactStore, GitHubRepo, resolve_target
from deployer.sync import sync_model
from deployer.verify import compare_live, read_live_isvc
from training import registry


def verify_all(cfg: dict, client) -> None:
    for model in cfg["models"]:
        try:
            target = resolve_target(client, model)
            finding = compare_live(target[0] if target else None, read_live_isvc(model, cfg["namespace"]))
            print(f"verify {model}: {finding.status.upper()} {finding.detail}", flush=True)
        except Exception as err:  # the check is advisory: it must never stop the sync loop
            print(f"verify {model}: UNKNOWN ({err})", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print the diff, commit nothing")
    parser.add_argument("--loop", action="store_true", help="repeat every --interval seconds")
    parser.add_argument("--interval", type=int, default=60, help="seconds between sync rounds")
    parser.add_argument("--verify-every", type=int, default=600,
                        help="seconds between convergence checks of the live InferenceService (0 = never)")
    args = parser.parse_args()

    cfg = yaml.safe_load((Path(__file__).parent / "models.yaml").read_text(encoding="utf-8"))
    client = registry.configure()
    repo, store = GitHubRepo(cfg["repo"], cfg["branch"]), ArtifactStore()
    last_verify = None
    while True:
        try:
            for model in cfg["models"]:
                print(sync_model(client, repo, store, model, cfg["namespace"], args.dry_run), flush=True)
        except Exception:
            traceback.print_exc()  # a failed round commits nothing; the next round retries
        if args.verify_every and (last_verify is None or time.monotonic() - last_verify >= args.verify_every):
            verify_all(cfg, client)
            last_verify = time.monotonic()
        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
