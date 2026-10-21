"""Convergence check: does the live InferenceService run what @production says?

Detection only. The deployer never edits the cluster: ArgoCD does that. This answers "did the chain
alias -> Git -> ArgoCD -> KServe actually arrive?" so a stuck link shows up instead of staying silent.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from deployer.manifest import kube_name


@dataclass(frozen=True)
class Finding:
    status: str      # ok | lagging | not_ready | missing | skip
    detail: str


def compare_live(expected_version: str | None, live: dict | None) -> Finding:
    """expected_version: version behind @production (None = no alias); live: the ISVC as JSON, None if absent."""
    if expected_version is None:
        return Finding("skip", "no @production")
    if live is None:
        return Finding("missing", f"@production is v{expected_version} but no InferenceService exists")
    running = (live.get("metadata", {}).get("annotations") or {}).get("mlops/model-version")
    ready = any(c.get("type") == "Ready" and c.get("status") == "True"
                for c in (live.get("status", {}).get("conditions") or []))
    if running != expected_version:
        return Finding("lagging", f"@production is v{expected_version} but the cluster runs v{running}")
    if not ready:
        return Finding("not_ready", f"v{expected_version} is declared but the InferenceService is not Ready")
    return Finding("ok", f"v{expected_version} is serving")


def read_live_isvc(registered_model: str, namespace: str) -> dict | None:
    """The live InferenceService via kubectl, None if it does not exist. Other failures raise."""
    proc = subprocess.run(["kubectl", "-n", namespace, "get", "isvc", kube_name(registered_model), "-o", "json"],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode == 0:
        return json.loads(proc.stdout)
    if "NotFound" in proc.stderr:
        return None
    raise RuntimeError(f"kubectl failed: {proc.stderr.strip()}")
