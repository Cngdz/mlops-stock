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
kubectl apply -f infra\bootstrap\minio-s3-secret.yaml          # S3 credentials for the storage-initializer (outside ArgoCD's path)
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

## Deployer (Day 10): @production in MLflow -> manifest commit in Git

`deployer/` keeps `serving/k8s/30-isvc-<model>.yaml` equal to what `@production` says (models listed in
`deployer/models.yaml`). It never touches the cluster: it commits the file to `master` through the GitHub API and
ArgoCD does the rest. That file is generated, do not edit it by hand.

```powershell
# .env (git-ignored): GITHUB_TOKEN=<fine-grained token, only this repo, Contents: read and write>
.\infra\port-forward.ps1                                         # MLflow on 127.0.0.1:5050
uv run --env-file .env python -m deployer --dry-run              # print the diff, commit nothing
uv run --env-file .env python -m deployer                        # one round
uv run --env-file .env python -m deployer --loop --interval 60   # poll every 60 s
uv run python -m pytest tests/test_deployer.py                   # not `uv run pytest`: the global pytest is broken
```

Day 11 additions: the decision lives in the pure `deployer/plan.py` (`skip | unchanged | blocked | create |
update`). Before committing a changed manifest the deployer checks that `<storageUri>/MLmodel` exists in MinIO
(needs the MinIO port-forward on 9000; steady-state rounds do not touch MinIO). If the artifact is missing the
round reports `blocked` and commits nothing; if MinIO itself cannot be read the round aborts, same rule as
MLflow. `--loop` syncs every 60 s and, every 600 s (`--verify-every`), compares the live InferenceService
(`kubectl get isvc`) with `@production`: `ok | lagging | not_ready | missing`. That check only reports; ArgoCD
is the one that repairs the cluster.

Promote = set alias `production` on the version (MLflow UI: Models -> model -> version -> Aliases, or
`training.promote --approve`). Rollback = set it back on the older version; there is no other path.
Always `git pull` before pushing: the deployer commits to the same branch.

Safety rules in the code (tested): a missing alias or model leaves everything alone; any other MLflow error
aborts the round without committing (a failed read must not look like an empty desired state); an unchanged
manifest produces no commit (so no pod roll). MLflow 3.15.2: `mv.model_id` is None, the S3 path comes from
`get_logged_model(mv.source.removeprefix("models:/")).artifact_location`; a model without the alias raises
`INVALID_PARAMETER_VALUE ... not found`, an unknown model `RESOURCE_DOES_NOT_EXIST`.

Measured (promote loan_propensity_au v2 -> v4 via the MLflow UI, 21/10/2026): deployer commit 15:58:52 ->
ArgoCD sync finished +23 s -> new pod Ready +17 s (40 s after the commit). The alias-change time was not
recorded, so alias -> commit (at most the 60 s poll) is unmeasured. These 40 s are a lucky poll: ArgoCD's
reconcile is 60 s + up to 60 s jitter, see the Day 9 section.

## Pipeline in the cluster + Airflow (Day 12)

Batch work (train, promote report, later batch predict) runs as pods from the `mlops-pipeline` image in namespace
`pipeline`; Airflow (standalone, in Docker, on the `kind` network) only schedules and orders them
(`KubernetesPodOperator`, `airflow/dags/mlops.py`). The feature pipeline (Days 2-4) still runs on the host: the
Iceberg metadata stores absolute `C:\...` paths, so the nodes cannot read it. The platform starts from an approved
feature run.

```powershell
docker build -f pipeline/Dockerfile --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) -t mlops-pipeline:v1 .
kind load docker-image mlops-pipeline:v1 --name lab           # kind has its own image store; pods use imagePullPolicy: Never
kubectl apply -f pipeline\k8s\00-namespace.yaml -f pipeline\k8s\10-pvc.yaml
kubectl apply -f pipeline\k8s\20-data-loader.yaml             # temporary pod that mounts the PVC
# copy the approved run (Git Bash needs MSYS_NO_PATHCONV=1, see pitfalls; `kubectl cp` failed on Windows, tar over exec works)
tar cf - -C data/features/day4_runs <RUN_ID> | kubectl -n pipeline exec -i data-loader -- tar xf - -C /app/data/features/day4_runs
tar cf - -C data/features current.json       | kubectl -n pipeline exec -i data-loader -- tar xf - -C /app/data/features
kubectl delete -f pipeline\k8s\20-data-loader.yaml
kubectl apply -f pipeline\k8s\30-smoke-train.yaml             # optional: train without MLflow, proves image + data + memory
.\airflow\start.ps1                                           # http://localhost:8080, admin / docker exec airflow cat /opt/airflow/standalone_admin_password.txt
docker stop airflow                                           # free the RAM when not in use; docker start airflow brings it back
```

`airflow/kubeconfig` holds cluster-admin credentials: git-ignored, never commit it. DAG `loan_propensity_train` is
train -> `training.promote` WITHOUT `--approve` (prints the gate; exit 1 = REFUSED, no retry). Nothing in Airflow may
set `@production`: that stays a human step.

Measured (21-22/10/2026): image 2.15 GB; smoke train about 1.3 GB RAM peak (limit 2 GB), 6 models in about 25 s;
Airflow container about 1.56 GiB while starting, about 0.57 GiB idle; DAG run train -> gate 1 min 38 s (train pod 71 s
including start, gate pod 9 s). The registered run carries `git_commit` of the image (28d9e2a) instead of `unknown`.

## Monitoring tables: Iceberg on MinIO (Day 13)

Two Iceberg catalogs by role. The Day 3-4 source/feature tables stay in the local SQLite catalog
(`data/catalog_full`, warehouse on the host disk). The in-cluster tables use a PyIceberg `SqlCatalog` stored in the
Postgres database `iceberg_catalog` (the Postgres that already backs MLflow) with data in `s3://warehouse/` (MinIO):
pods and the host read the same tables, and table locations are `s3://` URIs instead of `C:\...`. A production setup
would use one REST catalog (Lakekeeper, Polaris, Nessie) for everything.

One-time setup (bucket `warehouse` is also in `minio-values.yaml` for a fresh install):

```powershell
kubectl -n mlops exec postgres-postgresql-0 -- env PGPASSWORD=mlflowpassword psql -U postgres -c "CREATE DATABASE iceberg_catalog"
kubectl -n mlops exec deploy/minio -- sh -c "mc alias set local http://localhost:9000 minioadmin minioadmin && mc mb --ignore-existing local/warehouse"
.\infra\port-forward.ps1                     # now also Postgres on 127.0.0.1:5432 (catalog access from the host)
```

| Table (namespace `monitoring`) | Written by | Partition | Re-run |
|---|---|---|---|
| `pred_loan_propensity` | `pipeline.predict --date D [--end E]` | `score_date` | replaces that day |
| `drift_loan_propensity` | `pipeline.drift --date D [--reference R]` | `current_date` | replaces (D, R) |
| `eval_loan_propensity` | `pipeline.evaluate --start S --end E` | `window_end` | replaces (S, E) |

Thresholds live in `pipeline/monitoring.yaml` (still [TODO] for mentor confirmation in the design doc). Drift HTML
reports: `s3://warehouse/reports/drift/<usecase>/<day>_vs_<reference>.html` (MinIO console, port 9001).
DAGs: `loan_propensity_predict` = predict -> drift -> retrain_check (exit 99 = skip) -> trigger
`loan_propensity_train`; `loan_propensity_evaluate` weekly. Dates are DAG params because the synthetic data has no
"today" (features end 2026-01-30, labels end 2025-12-31).

Measured on the host (22/10/2026): predict 2026-01-30 = 4731 rows (au v4 2937, lu v4 851, nu v2 943), re-run still
4731. Drift 2026-01-30 vs 2025-06-30 = 18/24 features (75%) -> critical; vs 2026-01-29 = 1/24 (account_age_days,
which grows every day) -> medium. The generator has strong trends, so the training reference always reads critical:
`retrain_cooldown_days: 7` keeps a lasting drift from retraining every day on the same data. Evaluate 2025-12-25..31
(33117 rows): au 0.645 vs 0.636, lu 0.528 vs 0.563, nu 0.584 vs 0.577 -> all OK (largest drop 0.035, warn at 0.05).
Not an independent hold-out: Oct-Dec 2025 is the test split the gate used.

Same results in the cluster (Airflow -> pods from the rebuilt image, 2.68 GB, `GIT_COMMIT` 106b548): predict 2026-01-30
4731 rows, drift 18/24 critical, evaluate 33117 rows with the same AUCs; `monitoring.driftSeverity=critical` tags on
the three @production versions; `pred_*` holds 37848 rows = 8 days x 4731 after three runs of 2026-01-30 (idempotent
partition overwrite). `retrain_check` correctly exits 99 (critical, but the last training is within the 7-day
cooldown) and the `trigger_retrain` task is skipped, not failed. One unexplained flake: the first `retrain_check`
pod never got a scheduling event and hit the 300 s start timeout; the same pod ran fine by hand and on a clear +
re-run, so `retrain_check` now has `retries=1`. Rebuilding the image after a `uv.lock` change re-downloads every
package (about 10 min, needs network) and `kind load` of 2.6 GB takes several minutes: keep an eye on the host disk
(C: was down to 16 GB free).

## Pitfalls already hit

| Symptom | Cause | Fix in repo |
|---|---|---|
| MinIO `ImagePullBackOff`, `401 UNAUTHORIZED` | MinIO no longer serves public images (quay.io 401, Docker Hub denied) | `minio-values.yaml` uses `minio/minio:RELEASE.2024-12-18T13-15-44Z` with `pullPolicy: Never`; `bootstrap.ps1` runs `kind load docker-image`. The image exists only in the local Docker cache: keep it (`docker save` it for another machine) |
| MLflow `2.1.1` in the pod, aliases fail | chart `~0.7.0` shipped MLflow 2.1.1 | chart pinned to `1.11.6` (MLflow 3.15.2 = client version) |
| `port-forward svc/mlflow 5050:5000` fails | chart 1.x service port is 80 | `5050:80` |
| MLflow artifact upload fails, no bucket | bucket was never created by the chart | `buckets: [mlflow]` in `minio-values.yaml` |
| Application `OutOfSync` right after creating it | auto-sync not enabled (form saved Prune/Self Heal without the Automatic switch) | `spec.syncPolicy.automated` present, see `argocd/serving-app.yaml` |
| HPA `Degraded`, `kubectl top` says Metrics API not available | kind has no metrics-server; KServe creates an HPA per ISVC | `metrics-server` release in `helmfile.yaml` with `--kubelet-insecure-tls` |
| `kubectl exec ... mkdir /app/data/...` creates a stray `/app/C:` dir, `kubectl cp` says `Cannot open` | Git Bash rewrites `/app/...` arguments into `C:/Program Files/Git/app/...` before kubectl.exe sees them | `export MSYS_NO_PATHCONV=1` first (or run from PowerShell); same for `docker run -v` / `docker exec` |
| `kubectl apply` of a pod right after creating its namespace: `serviceaccount "default" not found` | the namespace's default ServiceAccount is created a moment later | wait for `kubectl -n <ns> get sa default`, then apply again |
| PVC `Pending` after apply | `WaitForFirstConsumer`: the volume is created when the first pod uses it | expected; it turns `Bound` once `data-loader` is scheduled |
| After a reboot: Docker API `Internal Server Error`, kubectl `connection refused`, pods `Unknown` | Docker Desktop and the kind node are still starting | wait until `kubectl get nodes` is Ready and `mlops`/`serving` pods are 1/1 (about 2 min) |
| MLflow starts before Postgres/MinIO | releases installed in parallel | `needs:` + `helmDefaults.wait` in `helmfile.yaml` |

## Client settings

`training/registry.py` defaults (override with env vars):
`MLFLOW_TRACKING_URI=http://127.0.0.1:5050`, `MLFLOW_S3_ENDPOINT_URL=http://127.0.0.1:9000`,
`AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY=minioadmin`. Artifacts land in `s3://mlflow/...`
(server flag `--default-artifact-root=s3://mlflow/`), the path KServe reads on Day 8.
