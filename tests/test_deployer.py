"""Deployer: pure manifest builder and the safety properties of one sync step (no network, no MLflow)."""
import pytest
import yaml
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INTERNAL_ERROR, INVALID_PARAMETER_VALUE, RESOURCE_DOES_NOT_EXIST

from deployer import sources
from deployer.manifest import build_isvc, kube_name, manifest_path
from deployer.sync import sync_model

URI = "s3://mlflow/1/models/m-abc/artifacts"


class FakeRepo:
    def __init__(self, text=None):
        self.text, self.writes = text, []

    def get_file(self, path):
        return self.text, ("sha1" if self.text is not None else None)

    def put_file(self, path, text, sha, message):
        self.text = text
        self.writes.append(message)


def test_build_isvc_is_deterministic():
    assert build_isvc("loan_propensity_au", "4", URI) == build_isvc("loan_propensity_au", "4", URI)


def test_build_isvc_content():
    doc = yaml.safe_load(build_isvc("loan_propensity_au", "4", URI))
    assert doc["metadata"]["name"] == "loan-propensity-au"
    assert doc["metadata"]["annotations"]["mlops/model-version"] == "4"
    assert doc["spec"]["predictor"]["model"]["storageUri"] == URI
    assert doc["spec"]["predictor"]["model"]["runtime"] == "mlflow-mlserver"


def test_names_and_path():
    assert kube_name("overdue_risk_lu") == "overdue-risk-lu"
    assert manifest_path("loan_propensity_au") == "serving/k8s/30-isvc-loan-propensity-au.yaml"


def test_new_version_changes_the_manifest():
    assert build_isvc("loan_propensity_au", "2", URI) != build_isvc("loan_propensity_au", "4", URI)


def test_second_run_does_not_commit(monkeypatch):
    monkeypatch.setattr("deployer.sync.resolve_target", lambda c, m: ("4", URI))
    repo = FakeRepo("# old\n")
    assert "committed" in sync_model(None, repo, "loan_propensity_au", "serving")
    assert "unchanged" in sync_model(None, repo, "loan_propensity_au", "serving")
    assert len(repo.writes) == 1


def test_dry_run_commits_nothing(monkeypatch):
    monkeypatch.setattr("deployer.sync.resolve_target", lambda c, m: ("4", URI))
    repo = FakeRepo("# old\n")
    assert "WOULD COMMIT" in sync_model(None, repo, "loan_propensity_au", "serving", dry_run=True)
    assert repo.writes == []


def test_missing_alias_writes_nothing(monkeypatch):
    monkeypatch.setattr("deployer.sync.resolve_target", lambda c, m: None)
    repo = FakeRepo("existing")
    sync_model(None, repo, "loan_propensity_au", "serving")
    assert repo.writes == [] and repo.text == "existing"


def test_unreadable_registry_propagates_and_writes_nothing(monkeypatch):
    def boom(c, m):
        raise RuntimeError("mlflow down")
    monkeypatch.setattr("deployer.sync.resolve_target", boom)
    repo = FakeRepo("existing")
    with pytest.raises(RuntimeError):
        sync_model(None, repo, "loan_propensity_au", "serving")
    assert repo.writes == []


class _Client:
    def __init__(self, error):
        self.error = error

    def get_model_version_by_alias(self, name, alias):
        raise self.error


def test_resolve_target_none_only_for_missing_alias():
    missing = MlflowException("no alias", error_code=RESOURCE_DOES_NOT_EXIST)
    assert sources.resolve_target(_Client(missing), "m") is None
    no_alias = MlflowException("Registered model alias production not found.", error_code=INVALID_PARAMETER_VALUE)
    assert sources.resolve_target(_Client(no_alias), "m") is None
    with pytest.raises(MlflowException):
        sources.resolve_target(_Client(MlflowException("bad request", error_code=INVALID_PARAMETER_VALUE)), "m")
    with pytest.raises(MlflowException):
        sources.resolve_target(_Client(MlflowException("down", error_code=INTERNAL_ERROR)), "m")
