"""Deployer entry point.

  uv run --env-file .env python -m deployer --dry-run             # show what would be committed
  uv run --env-file .env python -m deployer                       # one round
  uv run --env-file .env python -m deployer --loop --interval 60  # keep polling

Needs GITHUB_TOKEN (fine-grained, Contents read/write on the repo) and the MLflow port-forward.
"""
from __future__ import annotations

import argparse
import time
import traceback
from pathlib import Path

import yaml

from deployer.sources import GitHubRepo
from deployer.sync import sync_model
from training import registry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="print the diff, commit nothing")
    parser.add_argument("--loop", action="store_true", help="repeat every --interval seconds")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()

    cfg = yaml.safe_load((Path(__file__).parent / "models.yaml").read_text(encoding="utf-8"))
    client = registry.configure()
    repo = GitHubRepo(cfg["repo"], cfg["branch"])
    while True:
        try:
            for model in cfg["models"]:
                print(sync_model(client, repo, model, cfg["namespace"], args.dry_run), flush=True)
        except Exception:
            traceback.print_exc()  # a failed round commits nothing; the next round retries
        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
