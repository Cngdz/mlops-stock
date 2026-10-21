"""Outbound edges of the deployer: MLflow (desired state) and GitHub (actual state = the file in Git)."""
from __future__ import annotations

import base64
import os

import requests
from botocore.exceptions import ClientError
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


class ArtifactStore:
    """Does the model artifact behind a storageUri exist in S3/MinIO? Needs the MinIO port-forward (9000)."""

    def __init__(self, s3=None):
        self._s3 = s3

    @property
    def s3(self):
        if self._s3 is None:
            import boto3
            from botocore.config import Config
            self._s3 = boto3.client("s3", endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"],
                                    region_name="us-east-1", config=Config(signature_version="s3v4"))
        return self._s3

    def exists(self, storage_uri: str) -> bool:
        """True if <storage_uri>/MLmodel exists, False if it is not there. Any other failure (MinIO down,
        bad credentials) propagates: "could not look" must never read as "missing"."""
        bucket, _, key = storage_uri.removeprefix("s3://").partition("/")
        try:
            self.s3.head_object(Bucket=bucket, Key=f"{key.rstrip('/')}/MLmodel")
            return True
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise


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
