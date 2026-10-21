"""Deployer: pure manifest builder, the decision step, the artifact check and the convergence check.
No network, no MLflow, no cluster: every outside dependency is a small fake."""
import pytest
import yaml
from botocore.exceptions import ClientError
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import INTERNAL_ERROR, INVALID_PARAMETER_VALUE, RESOURCE_DOES_NOT_EXIST

from deployer import sources
from deployer.manifest import build_isvc, kube_name, manifest_path
from deployer.plan import plan
from deployer.sources import ArtifactStore
from deployer.sync import sync_model
from deployer.verify import compare_live

URI = "s3://mlflow/1/models/m-abc/artifacts"
MODEL, NS = "loan_propensity_au", "serving"


class FakeRepo:
    def __init__(self, text=None):
        self.text, self.writes = text, []

    def get_file(self, path):
        return self.text, ("sha1" if self.text is not None else None)

    def put_file(self, path, text, sha, message):
        self.text = text
        self.writes.append(message)


class FakeStore:
    def __init__(self, present=True):
        self.present, self.calls = present, 0

    def exists(self, storage_uri):
        self.calls += 1
        return self.present


# ---- manifest (pure) ----

def test_build_isvc_is_deterministic():
    assert build_isvc(MODEL, "4", URI) == build_isvc(MODEL, "4", URI)


def test_build_isvc_content():
    doc = yaml.safe_load(build_isvc(MODEL, "4", URI))
    assert doc["metadata"]["name"] == "loan-propensity-au"
    assert doc["metadata"]["annotations"]["mlops/model-version"] == "4"
    assert doc["spec"]["predictor"]["model"]["storageUri"] == URI
    assert doc["spec"]["predictor"]["model"]["runtime"] == "mlflow-mlserver"


def test_names_and_path():
    assert kube_name("overdue_risk_lu") == "overdue-risk-lu"
    assert manifest_path(MODEL) == "serving/k8s/30-isvc-loan-propensity-au.yaml"


def test_new_version_changes_the_manifest():
    assert build_isvc(MODEL, "2", URI) != build_isvc(MODEL, "4", URI)


# ---- plan (pure decision) ----

def test_plan_creates_when_no_manifest_yet():
    action = plan(MODEL, NS, ("4", URI), None, lambda uri: True)
    assert action.kind == "create" and action.text == build_isvc(MODEL, "4", URI) and action.version == "4"


def test_plan_updates_when_version_differs():
    old = build_isvc(MODEL, "2", URI)
    assert plan(MODEL, NS, ("4", URI), old, lambda uri: True).kind == "update"


def test_plan_unchanged_never_asks_the_artifact_store():
    current = build_isvc(MODEL, "4", URI)

    def boom(uri):
        raise AssertionError("steady state must not touch MinIO")
    assert plan(MODEL, NS, ("4", URI), current, boom).kind == "unchanged"


def test_plan_blocks_when_artifact_is_missing():
    action = plan(MODEL, NS, ("4", URI), build_isvc(MODEL, "2", URI), lambda uri: False)
    assert action.kind == "blocked" and not action.writes and action.text is None


def test_plan_missing_alias_is_a_skip_and_never_a_delete():
    existing = build_isvc(MODEL, "2", URI)
    action = plan(MODEL, NS, None, existing, lambda uri: True)
    assert action.kind == "skip" and not action.writes and "left in place" in action.reason


def test_plan_asks_the_store_about_the_new_uri():
    seen = []
    plan(MODEL, NS, ("4", URI), None, lambda uri: seen.append(uri) or True)
    assert seen == [URI]


# ---- sync_model: plan + the edges ----

def _patch_target(monkeypatch, target):
    monkeypatch.setattr("deployer.sync.resolve_target", lambda c, m: target)


def test_second_run_does_not_commit(monkeypatch):
    _patch_target(monkeypatch, ("4", URI))
    repo, store = FakeRepo("# old\n"), FakeStore()
    assert "committed" in sync_model(None, repo, store, MODEL, NS)
    assert "unchanged" in sync_model(None, repo, store, MODEL, NS)
    assert len(repo.writes) == 1 and store.calls == 1


def test_dry_run_commits_nothing(monkeypatch):
    _patch_target(monkeypatch, ("4", URI))
    repo = FakeRepo("# old\n")
    assert "WOULD COMMIT" in sync_model(None, repo, FakeStore(), MODEL, NS, dry_run=True)
    assert repo.writes == []


def test_missing_artifact_commits_nothing(monkeypatch):
    _patch_target(monkeypatch, ("4", URI))
    repo = FakeRepo(build_isvc(MODEL, "2", URI))
    before = repo.text
    assert "artifact missing" in sync_model(None, repo, FakeStore(present=False), MODEL, NS)
    assert repo.writes == [] and repo.text == before


def test_missing_alias_writes_nothing(monkeypatch):
    _patch_target(monkeypatch, None)
    repo = FakeRepo("existing")
    sync_model(None, repo, FakeStore(), MODEL, NS)
    assert repo.writes == [] and repo.text == "existing"


def test_unreadable_registry_propagates_and_writes_nothing(monkeypatch):
    def boom(c, m):
        raise RuntimeError("mlflow down")
    monkeypatch.setattr("deployer.sync.resolve_target", boom)
    repo = FakeRepo("existing")
    with pytest.raises(RuntimeError):
        sync_model(None, repo, FakeStore(), MODEL, NS)
    assert repo.writes == []


def test_unreadable_artifact_store_propagates_and_writes_nothing(monkeypatch):
    _patch_target(monkeypatch, ("4", URI))

    class Down:
        def exists(self, uri):
            raise ConnectionError("minio down")
    repo = FakeRepo(build_isvc(MODEL, "2", URI))
    with pytest.raises(ConnectionError):
        sync_model(None, repo, Down(), MODEL, NS)
    assert repo.writes == []


def test_rollback_is_just_another_alias_change(monkeypatch):
    repo, store = FakeRepo(), FakeStore()
    for version in ("2", "4", "2"):
        _patch_target(monkeypatch, (version, URI.replace("m-abc", f"m-v{version}")))
        sync_model(None, repo, store, MODEL, NS)
    assert repo.writes == ["deploy loan_propensity_au v2", "deploy loan_propensity_au v4",
                           "deploy loan_propensity_au v2"]
    assert yaml.safe_load(repo.text)["metadata"]["annotations"]["mlops/model-version"] == "2"


# ---- resolve_target ----

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


# ---- ArtifactStore ----

class _S3:
    def __init__(self, error=None):
        self.error, self.keys = error, []

    def head_object(self, Bucket, Key):
        self.keys.append((Bucket, Key))
        if self.error:
            raise self.error


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "HeadObject")


def test_artifact_store_looks_for_the_mlmodel_file():
    s3 = _S3()
    assert ArtifactStore(s3).exists("s3://mlflow/1/models/m-abc/artifacts/") is True
    assert s3.keys == [("mlflow", "1/models/m-abc/artifacts/MLmodel")]


def test_artifact_store_false_only_for_not_found():
    assert ArtifactStore(_S3(_client_error("404"))).exists(URI) is False
    assert ArtifactStore(_S3(_client_error("NoSuchKey"))).exists(URI) is False
    with pytest.raises(ClientError):
        ArtifactStore(_S3(_client_error("403"))).exists(URI)
    with pytest.raises(ConnectionError):
        ArtifactStore(_S3(ConnectionError("down"))).exists(URI)


# ---- convergence check (pure) ----

def _live(version, ready):
    return {"metadata": {"annotations": {"mlops/model-version": version}},
            "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


def test_compare_live_statuses():
    assert compare_live(None, None).status == "skip"
    assert compare_live("4", None).status == "missing"
    assert compare_live("4", _live("2", True)).status == "lagging"
    assert compare_live("4", _live("4", False)).status == "not_ready"
    assert compare_live("4", _live("4", True)).status == "ok"
    assert compare_live("4", {"metadata": {}}).status == "lagging"
