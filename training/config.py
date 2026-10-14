"""Load training/usecases.yaml and reject feature lists that could leak the label."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).with_name("usecases.yaml")

LABELS = {"loan_label_next", "overdue_label_next_30d", "campaign_response_label_14d"}
KEYS = {"master_account", "report_date", "campaign_event_id", "campaign_id", "event_timestamp", "sent_at"}
# overdue_eligible defines the overdue population; portfolio_value is not reconciled with asset_value.
FORBIDDEN = LABELS | KEYS | {"split", "overdue_eligible", "portfolio_value"}


@dataclass(frozen=True)
class UseCase:
    name: str
    dataset: str
    label: str
    numeric_features: list[str]
    categorical_features: list[str]
    class_weights: str
    threshold: dict
    segment_column: str | None = None
    segments: list[str] | None = None
    row_filter: str | None = None
    seed: int = 42
    n_jobs: int = 4
    lgbm: dict = field(default_factory=dict)
    lr: dict = field(default_factory=dict)

    @property
    def features(self) -> list[str]:
        return self.numeric_features + self.categorical_features

    def feature_hash(self) -> str:
        payload = json.dumps([self.numeric_features, self.categorical_features])
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


def validate(uc: UseCase) -> None:
    features = uc.features
    if not features:
        raise ValueError(f"{uc.name}: empty feature allowlist")
    duplicated = {f for f in features if features.count(f) > 1}
    if duplicated:
        raise ValueError(f"{uc.name}: duplicated features {sorted(duplicated)}")
    leaked = set(features) & FORBIDDEN
    if leaked:
        raise ValueError(f"{uc.name}: forbidden columns in allowlist {sorted(leaked)}")
    if uc.segments and uc.segment_column in features:
        raise ValueError(f"{uc.name}: {uc.segment_column} is constant inside a segment model")
    if uc.threshold.get("rule") not in {"max_f1", "min_recall"}:
        raise ValueError(f"{uc.name}: unknown threshold rule {uc.threshold}")


def load_usecases(path: Path = CONFIG_PATH) -> dict[str, UseCase]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    usecases = {}
    for name, spec in raw["use_cases"].items():
        uc = UseCase(name=name, **{**defaults, **spec})
        validate(uc)
        usecases[name] = uc
    return usecases
