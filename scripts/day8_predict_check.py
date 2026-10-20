"""Day 8: call the KServe endpoint with real feature vectors and compare with the MLflow model.

Usage:  python -m scripts.day8_predict_check --model loan_propensity_au --url http://127.0.0.1:8085
PASS = HTTP 200, same shape, max |KServe - MLflow| < 1e-9.
"""
from __future__ import annotations

import argparse
import json

import mlflow
import numpy as np
import pandas as pd
import requests

from training import registry
from training.data import resolve_run_dir

V2_TYPES = {"int64": "INT64", "int32": "INT32", "int8": "INT8", "float64": "FP64", "float32": "FP32"}


def v2_payload(X: pd.DataFrame) -> dict:
    """Open Inference Protocol (V2): one input tensor per column; content_type "pd" makes
    MLServer rebuild a pandas DataFrame with the column names the signature expects."""
    return {"parameters": {"content_type": "pd"},
            "inputs": [{"name": c, "datatype": V2_TYPES[str(X[c].dtype)], "shape": [len(X)],
                        "data": X[c].tolist()} for c in X.columns]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="loan_propensity_au", help="registered model name")
    parser.add_argument("--url", default="http://127.0.0.1:8085", help="predictor base URL")
    parser.add_argument("--rows", type=int, default=20)
    args = parser.parse_args()

    registry.configure()
    reference = mlflow.pyfunc.load_model(f"models:/{args.model}@production")
    version = registry.production_version(mlflow.MlflowClient(), args.model).version
    columns = reference.metadata.get_input_schema().input_names()
    segment = args.model.rsplit("_", 1)[1]

    df = pd.read_parquet(resolve_run_dir() / "training_dataset.parquet")
    X = df[(df["split"] == "validation") & (df["margin_segment"] == segment)][columns].head(args.rows)

    isvc = args.model.replace("_", "-")            # Kubernetes names: lowercase, digits, '-'
    r = requests.post(f"{args.url}/v2/models/{isvc}/infer", json=v2_payload(X), timeout=30)
    r.raise_for_status()
    out = r.json()["outputs"][0]
    served = np.asarray(out["data"]).reshape(out["shape"])
    expected = np.asarray(reference.predict(X))

    diff = float(np.max(np.abs(served - expected)))
    ok = served.shape == expected.shape and diff < 1e-9
    print(json.dumps({"model": args.model, "production_version": version, "rows": len(X),
                      "served_p1_head": served[:3, 1].round(4).tolist(), "max_abs_diff": diff,
                      "status": "PASS" if ok else "FAIL"}, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
