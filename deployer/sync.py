"""One reconcile step for one model: desired (@production in MLflow) vs actual (the manifest in Git)."""
from __future__ import annotations

import difflib

from deployer.manifest import build_isvc, manifest_path
from deployer.sources import resolve_target


def sync_model(client, repo, registered_model: str, namespace: str, dry_run: bool = False) -> str:
    """Commit the manifest only if it differs from Git. Returns a one-line (or diff) report."""
    target = resolve_target(client, registered_model)
    if target is None:
        return f"{registered_model}: no @production, left alone"  # a missing alias never deletes anything
    version, storage_uri = target
    desired = build_isvc(registered_model, version, storage_uri, namespace)
    path = manifest_path(registered_model)
    current, sha = repo.get_file(path)
    if current == desired:
        return f"{registered_model}: v{version} unchanged"
    if dry_run:
        diff = "".join(difflib.unified_diff((current or "").splitlines(True), desired.splitlines(True),
                                            "git", "desired"))
        return f"{registered_model}: v{version} WOULD COMMIT\n{diff}"
    repo.put_file(path, desired, sha, f"deploy {registered_model} v{version}")
    return f"{registered_model}: v{version} committed"
