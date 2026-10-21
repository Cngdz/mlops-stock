"""Outbound edges of the deployer: MLflow (desired state) and GitHub (actual state = the file in Git)."""
from __future__ import annotations

import base64
import os

import requests
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

API = "https://api.github.com"


def resolve_target(client: MlflowClient, registered_model: str) -> tuple[str, str] | None:
    """(version, storageUri) behind @production, or None if the alias is not set.

    Any other failure (server down, auth) propagates: "could not read" must never look like
    "no model", or one MLflow hiccup would read as an empty desired state.
    """
    try:
        mv = client.get_model_version_by_alias(registered_model, "production")
    except MlflowException as err:
        # Measured on MLflow 3.15.2: unknown model -> RESOURCE_DOES_NOT_EXIST; model without the alias ->
        # INVALID_PARAMETER_VALUE "alias production not found". Both mean "nothing to deploy".
        missing_model = err.error_code == "RESOURCE_DOES_NOT_EXIST"
        missing_alias = err.error_code == "INVALID_PARAMETER_VALUE" and "not found" in str(err)
        if missing_model or missing_alias:
            return None
        raise
    # MLflow 3: mv.source is "models:/m-<id>" and mv.model_id is None; the S3 path lives on the logged model.
    model_id = mv.source.removeprefix("models:/")
    return str(mv.version), client.get_logged_model(model_id).artifact_location


class GitHubRepo:
    def __init__(self, repo: str, branch: str, token: str | None = None):
        self.repo, self.branch = repo, branch
        self.headers = {"Authorization": f"Bearer {token or os.environ['GITHUB_TOKEN']}",
                        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    def get_file(self, path: str) -> tuple[str | None, str | None]:
        """(text, sha) of the file on the branch, or (None, None) if it does not exist."""
        r = requests.get(f"{API}/repos/{self.repo}/contents/{path}", headers=self.headers,
                         params={"ref": self.branch}, timeout=15)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        body = r.json()
        # CRLF -> LF so a Windows checkout cannot make identical content look different
        return base64.b64decode(body["content"]).decode("utf-8").replace("\r\n", "\n"), body["sha"]

    def put_file(self, path: str, text: str, sha: str | None, message: str) -> None:
        payload = {"message": message, "branch": self.branch,
                   "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}
        if sha:
            payload["sha"] = sha  # GitHub rejects the write (409) if the file changed since we read it
        r = requests.put(f"{API}/repos/{self.repo}/contents/{path}", headers=self.headers,
                         json=payload, timeout=15)
        r.raise_for_status()
