"""One reconcile step for one model: desired (@production in MLflow) vs actual (the manifest in Git)."""
from __future__ import annotations

import difflib

from deployer.manifest import manifest_path
from deployer.plan import plan
from deployer.sources import resolve_target


def sync_model(client, repo, store, registered_model: str, namespace: str, dry_run: bool = False) -> str:
    """Decide with plan(), then commit only if the manifest must change. Returns a one-line (or diff) report."""
    target = resolve_target(client, registered_model)
    path = manifest_path(registered_model)
    current, sha = repo.get_file(path)
    action = plan(registered_model, namespace, target, current, store.exists)
    head = f"{registered_model}: " + (f"v{action.version} " if action.version else "")
    if not action.writes:
        return head + action.reason          # skip / unchanged / blocked: nothing is written
    if dry_run:
        diff = "".join(difflib.unified_diff((current or "").splitlines(True), action.text.splitlines(True),
                                            "git", "desired"))
        return head + f"WOULD COMMIT\n{diff}"
    repo.put_file(path, action.text, sha, f"deploy {registered_model} v{action.version}")
    return head + "committed"
