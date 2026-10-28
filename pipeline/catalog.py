"""Iceberg catalog for in-cluster tables: the feature store (features), Gold (gold) and monitoring (predictions, drift, evaluation).

Catalog = PyIceberg SqlCatalog stored in the Postgres database `iceberg_catalog` (the Postgres that already backs
MLflow); data files live in MinIO under s3://warehouse/. Locations are s3:// URIs, so pods and the host read the
same tables. The Day 3-4 source/feature tables stay in the local SQLite catalog (data/catalog_full).

Defaults = the host port-forwards (infra/port-forward.ps1); pods override them with in-cluster addresses.
"""
from __future__ import annotations

import os

from pyiceberg.catalog import Catalog
from pyiceberg.catalog.sql import SqlCatalog

NAMESPACE = "monitoring"
FEATURES_NAMESPACE = "features"


def load() -> Catalog:
    endpoint = os.environ.get("MLFLOW_S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    return SqlCatalog(
        "lakehouse",
        **{
            "uri": os.environ.get(
                "ICEBERG_CATALOG_URI", "postgresql+psycopg2://postgres:mlflowpassword@127.0.0.1:5432/iceberg_catalog"),
            "warehouse": os.environ.get("ICEBERG_WAREHOUSE", "s3://warehouse"),
            "s3.endpoint": endpoint,
            "s3.access-key-id": os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
            "s3.secret-access-key": os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"),
            "s3.region": "us-east-1",
            "s3.path-style-access": "true",  # MinIO serves buckets as http://host/bucket, not bucket.host
        },
    )


def ensure_namespace(catalog: Catalog, namespace: str = NAMESPACE) -> None:
    catalog.create_namespace_if_not_exists(namespace)
