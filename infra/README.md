# Infra runbook

Namespace `mlops` on a kind cluster: Postgres (MLflow backend), Redis (Feast online, phase 2),
MinIO (artifact store, bucket `mlflow`), MLflow 3.15.2.

## Bring up

```powershell
kind create cluster --name mlops-cluster     # or reuse an existing kind cluster (kubectl config use-context kind-<name>)
.\infra\bootstrap.ps1                        # loads the MinIO image into kind, helmfile sync, waits for Ready
.\infra\port-forward.ps1                     # MLflow -> 127.0.0.1:5050, MinIO -> 127.0.0.1:9000 (keep the window open)
uv run python scripts/day1_verify.py         # end-to-end: log a model to MLflow + MinIO
```

## Check

```powershell
kind get clusters ; kubectl config current-context   # which cluster kubectl talks to
helm list -n mlops                                   # postgres, redis, minio, mlflow = deployed
kubectl get pods,svc -n mlops                        # all Running 1/1
kubectl describe pod <pod> -n mlops                  # Events at the bottom when a pod is stuck
```

## Pitfalls already hit

| Symptom | Cause | Fix in repo |
|---|---|---|
| MinIO `ImagePullBackOff`, `401 UNAUTHORIZED` | MinIO no longer serves public images (quay.io 401, Docker Hub denied) | `minio-values.yaml` uses `minio/minio:RELEASE.2024-12-18T13-15-44Z` with `pullPolicy: Never`; `bootstrap.ps1` runs `kind load docker-image`. The image exists only in the local Docker cache: keep it (`docker save` it for another machine) |
| MLflow `2.1.1` in the pod, aliases fail | chart `~0.7.0` shipped MLflow 2.1.1 | chart pinned to `1.11.6` (MLflow 3.15.2 = client version) |
| `port-forward svc/mlflow 5050:5000` fails | chart 1.x service port is 80 | `5050:80` |
| MLflow artifact upload fails, no bucket | bucket was never created by the chart | `buckets: [mlflow]` in `minio-values.yaml` |
| MLflow starts before Postgres/MinIO | releases installed in parallel | `needs:` + `helmDefaults.wait` in `helmfile.yaml` |

## Client settings

`training/registry.py` defaults (override with env vars):
`MLFLOW_TRACKING_URI=http://127.0.0.1:5050`, `MLFLOW_S3_ENDPOINT_URL=http://127.0.0.1:9000`,
`AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY=minioadmin`. Artifacts land in `s3://mlflow/...`
(server flag `--default-artifact-root=s3://mlflow/`), the path KServe reads on Day 8.
