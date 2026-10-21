"""Pure decision step of the deployer: desired (@production target) vs actual (manifest in Git) -> one Action.

No I/O. The only outside question, "does the artifact exist?", arrives as a callable and is asked lazily,
only when the manifest would change, so a steady-state round never touches MinIO.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from deployer.manifest import build_isvc


@dataclass(frozen=True)
class Action:
    kind: str                    # skip | unchanged | blocked | create | update
    reason: str
    version: str | None = None
    text: str | None = None      # manifest to write; set only for create/update

    @property
    def writes(self) -> bool:
        return self.kind in ("create", "update")


def plan(registered_model: str, namespace: str, target: tuple[str, str] | None, current: str | None,
         artifact_exists: Callable[[str], bool]) -> Action:
    """target = (version, storageUri) behind @production or None; current = manifest text in Git or None."""
    if target is None:
        # A missing alias is never a reason to delete: the manifest, and the pod behind it, stay as they are.
        return Action("skip", "no @production, manifest left in place" if current is not None
                      else "no @production, nothing to deploy")
    version, storage_uri = target
    desired = build_isvc(registered_model, version, storage_uri, namespace)
    if current == desired:
        return Action("unchanged", "unchanged", version)
    if not artifact_exists(storage_uri):
        # Committing a pointer to nothing would roll a pod that can never load its model.
        return Action("blocked", f"artifact missing at {storage_uri}, nothing committed", version)
    kind = "create" if current is None else "update"
    return Action(kind, kind, version, desired)
