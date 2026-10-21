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

## Serving via GitOps (ArgoCD, Day 9)

`serving/k8s/` is owned by ArgoCD (Application `serving`, `argocd/serving-app.yaml`, auto-sync + prune +
self-heal, server-side apply). Change serving by committing to `master`; do not `kubectl apply` those files.

Not in Git, so apply once by hand after the cluster exists:

```powershell
helmfile -f infra\helmfile.yaml sync                          # includes argocd and metrics-server
kubectl apply -f infraootstrap\minio-s3-secret.yaml          # S3 credentials for the storage-initializer (outside ArgoCD's path)
kubectl -n argocd create secret generic repo-mlops-stock `
  --from-literal=type=git --from-literal=url=https://github.com/Cngdz/mlops-stock.git `
  --from-literal=username=Cngdz --from-literal=password=<read-only fine-grained token>
kubectl -n argocd label secret repo-mlops-stock argocd.argoproj.io/secret-type=repository
kubectl apply -f argocd\serving-app.yaml                       # the only manual apply for serving
```

UI: `kubectl -n argocd port-forward svc/argocd-server 8090:80` -> http://localhost:8090 (user `admin`,
password: `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}"`, base64-decoded).

Measured on this lab (kind, 1 node, 8 GB): ArgoCD costs about 0.5 GB RAM; a Git push reaches the cluster in up to
about 2 min (`timeout.reconciliation` 60 s + up to 60 s jitter; the UI Refresh button skips the wait); a manual
edit is reverted in about 2 s (self-heal watches the cluster, it does not wait for the poll).

Behaviour to remember: KServe copies ISVC annotations and labels onto the pod template, so any change to them
(including ArgoCD's own tracking annotation on first adoption, and `mlops/model-version` on every promotion)
rolls the pod once. Rollout is zero-downtime: the old pod stays until the new one is Ready.

## Pitfalls already hit

| Symptom | Cause | Fix in repo |
|---|---|---|
| MinIO `ImagePullBackOff`, `401 UNAUTHORIZED` | MinIO no longer serves public images (quay.io 401, Docker Hub denied) | `minio-values.yaml` uses `minio/minio:RELEASE.2024-12-18T13-15-44Z` with `pullPolicy: Never`; `bootstrap.ps1` runs `kind load docker-image`. The image exists only in the local Docker cache: keep it (`docker save` it for another machine) |
| MLflow `2.1.1` in the pod, aliases fail | chart `~0.7.0` shipped MLflow 2.1.1 | chart pinned to `1.11.6` (MLflow 3.15.2 = client version) |
| `port-forward svc/mlflow 5050:5000` fails | chart 1.x service port is 80 | `5050:80` |
| MLflow artifact upload fails, no bucket | bucket was never created by the chart | `buckets: [mlflow]` in `minio-values.yaml` |
| Application `OutOfSync` right after creating it | auto-sync not enabled (form saved Prune/Self Heal without the Automatic switch) | `spec.syncPolicy.automated` present, see `argocd/serving-app.yaml` |
| HPA `Degraded`, `kubectl top` says Metrics API not available | kind has no metrics-server; KServe creates an HPA per ISVC | `metrics-server` release in `helmfile.yaml` with `--kubelet-insecure-tls` |
| MLflow starts before Postgres/MinIO | releases installed in parallel | `needs:` + `helmDefaults.wait` in `helmfile.yaml` |

## Client settings

`training/registry.py` defaults (override with env vars):
`MLFLOW_TRACKING_URI=http://127.0.0.1:5050`, `MLFLOW_S3_ENDPOINT_URL=http://127.0.0.1:9000`,
`AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY=minioadmin`. Artifacts land in `s3://mlflow/...`
(server flag `--default-artifact-root=s3://mlflow/`), the path KServe reads on Day 8.
