"""Deployer entry point.

  uv run --env-file .env python -m deployer --dry-run             # show what would be committed
  uv run --env-file .env python -m deployer                       # one round
  uv run --env-file .env python -m deployer --loop                # sync every 60 s, verify every 600 s

Needs GITHUB_TOKEN (fine-grained, Contents read/write on the repo), the MLflow (5050) and MinIO (9000)
port-forwards (infra/port-forward.ps1), and kubectl for the convergence check (--verify-every 0 turns it off).
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
