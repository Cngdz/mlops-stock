# Infra runbook

Everything runs on one Kubernetes cluster (docs chapter 2), split by namespace: `airflow` (scheduling), `pipeline`
(batch pods), `mlops` (Postgres, MinIO, MLflow, Redis, deployer), `argocd`, `serving` (KServe). Images come from the
cluster's Harbor registry. The workstation only builds/pushes images and opens port-forwards to look at UIs.

`harbor.local` below and in the manifests is a placeholder for your Harbor host: replace it in
`airflow-values.yaml`, `minio-values.yaml`, `deployer/k8s/deployer.yaml`, `pipeline/k8s/*.yaml` and the two
Dockerfiles (`grep -rn harbor.local infra pipeline deployer`).

## Images (Harbor)

```powershell
docker login harbor.local
docker build -f pipeline/Dockerfile --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) -t harbor.local/mlops/mlops-pipeline:v1 .
docker push harbor.local/mlops/mlops-pipeline:v1
docker build -f deployer/Dockerfile -t harbor.local/mlops/mlops-deployer:v1 .      # FROM the pipeline image
docker push harbor.local/mlops/mlops-deployer:v1
# MinIO no longer publishes images: mirror the cached copy once
docker tag minio/minio:RELEASE.2024-12-18T13-15-44Z harbor.local/mirror/minio:RELEASE.2024-12-18T13-15-44Z
docker push harbor.local/mirror/minio:RELEASE.2024-12-18T13-15-44Z
# pull secret (robot account) in every namespace that pulls from Harbor
foreach ($ns in "mlops", "pipeline") { kubectl create namespace $ns --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n $ns create secret docker-registry harbor-pull --docker-server=harbor.local --docker-username=<robot> --docker-password=<token> }
```

Tasks pull with `imagePullPolicy: Always`: pushing a new `:v1` is enough, the next pod runs it.

## Bring up

```powershell
kubectl config use-context <cluster>
# one-time secrets that are not in Git
kubectl -n mlops create secret generic deployer-github --from-literal=token=<fine-grained token, Contents: read and write>
kubectl create namespace airflow
kubectl -n airflow create secret generic airflow-git-credentials `
  --from-literal=GIT_SYNC_USERNAME=Cngdz --from-literal=GIT_SYNC_PASSWORD=<read-only token> `
  --from-literal=GITSYNC_USERNAME=Cngdz --from-literal=GITSYNC_PASSWORD=<read-only token>
.\infra\bootstrap.ps1          # namespaces, secrets/RBAC outside Helm, helmfile sync (waits for Ready), deployer
.\infra\port-forward.ps1       # workstation access only: MLflow 5050, MinIO 9000/9001, Postgres 5432, Airflow 8080
uv run python scripts/day1_verify.py         # end-to-end: log a model to MLflow + MinIO
```

Postgres databases: a fresh install creates `iceberg_catalog` and `airflow` (initdb script in
`postgres-values.yaml`). On an existing volume initdb does not run again; create the missing one by hand first:
`kubectl -n mlops exec postgres-postgresql-0 -- env PGPASSWORD=mlflowpassword psql -U postgres -c "CREATE DATABASE airflow"`.

## Check

```powershell
kubectl config current-context; kubectl get nodes   # which cluster kubectl talks to
helm list -A                                        # postgres, redis, minio, mlflow, argocd, metrics-server, airflow
kubectl get pods -A                                 # all Running
kubectl describe pod <pod> -n <ns>                  # Events at the bottom when a pod is stuck
```

## Airflow in the cluster

Release `airflow` (chart `apache-airflow/airflow` 1.16.0 = Airflow 2.10.5, `infra/helm-values/airflow-values.yaml`):
LocalExecutor, metadata in the `airflow` database of the mlops Postgres, DAGs pulled from `master/airflow/dags` by
git-sync every 60 s (push to master = new DAG code; nothing is copied into a pod). Tasks are
`KubernetesPodOperator` pods in namespace `pipeline`, created with the scheduler's in-cluster service account
(`pipeline/k8s/40-airflow-rbac.yaml`). The `<usecase>_predict` DAGs wait for the feature store with a `SqlSensor` on
connection `feature_store_db` (Secret `airflow-connections`, `infra/bootstrap/airflow-connections-secret.yaml`).

```powershell
kubectl -n airflow get pods
kubectl -n airflow exec deploy/airflow-scheduler -- airflow dags list
kubectl -n airflow exec deploy/airflow-scheduler -- airflow dags trigger feature_store_daily --conf '{\"report_date\":\"2026-01-30\"}'
kubectl -n airflow port-forward svc/airflow-webserver 8080:8080    # UI admin / admin (change it)
```

The docs write `deploy/airflow`: the chart names the deployments `airflow-scheduler` and `airflow-webserver`.

## Feature store: Gold -> fs_* (docs chapter 3)

Gold and fs_* live in the same Postgres catalog `iceberg_catalog` as the monitoring tables, data in
`s3://warehouse/`: namespaces `gold` (8 source tables, read-only), `features` (`fs_*` partitioned by `report_date`,
plus the internal carried state `fs_state`). Readiness is `control.fs_status` (plain Postgres table, schema
`control`, same database). Contract: `docs/feature_contract.md`.

One-time, from the workstation (port-forwards open):

```powershell
uv run python scripts/migrate_gold.py                                          # local SQLite Gold -> gold.* (about 30 s)
uv run python -m features.backfill --start 2025-02-01 --end 2026-01-30 --bootstrap   # 12 months, month by month
uv run python -m features.status --start 2026-01-25 --end 2026-01-30          # all COMPLETE
```

Daily (DAG `feature_store_daily`, 23:00 UTC = 06:00 VN, `report_date` = yesterday or the conf value):
`check_source -> compute_features -> write_partitions -> quality_gate -> publish_marker`. Each day reads Gold of
T-30..T plus `fs_state` of T-1, overwrites partition T of the six tables, checks only partition T, then marks T
`COMPLETE`. A re-run withdraws the marker first (WRITING) and replaces only partition T. A missing T-1 state stops
the run (`--bootstrap` starts a new history). Weekly `feature_store_maintenance`: partitions older than 12 months
(counted from the latest COMPLETE day), snapshots older than 7 days, orphan files older than 3 days, training runs
beyond the newest 12.

Training data (`features.build_training`, first task of every `<usecase>_train`): fs_* partitions of the split range
+ labels from Gold -> `data/features/day4_runs/<usecase>_<ts>/` on the PVC (same files training.train and
pipeline.evaluate always read), `current.json` moved to it on PASS.

Measured on the workstation against a local SQLite + file lakehouse (23/10/2026): Gold copy 30 s; backfill of 364
days 1 min 40 s; one daily run (compute 4 s + write + gate + publish) a few seconds, 4731 rows for 2026-01-30;
`build_training` 16 s. Content check against the last full-rebuild run (20261007T095923177784): fs_* identical on
1,722,576 rows except `days_since_last_campaign` / `has_campaign_history` (bug fixed, see the contract), and
training_dataset (1,284,182 rows), campaign_training_dataset (28,018) and class weights identical.

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

It runs as Deployment `mlops/deployer` (`deployer/k8s/deployer.yaml`, image `mlops-deployer` = pipeline image +
deployer + kubectl): `--loop --interval 60 --verify-every 600`, `GITHUB_TOKEN` from Secret `deployer-github`,
MLflow/MinIO through `mlflow.mlops.svc` / `minio.mlops.svc` (MinIO keys from the chart's Secret `minio`), and a
service account that may only read InferenceServices in `serving`.

```powershell
kubectl apply -f deployer\k8s\deployer.yaml                      # also done by bootstrap.ps1
kubectl -n mlops logs -f deploy/deployer                         # decisions: skip | unchanged | blocked | create | update
kubectl -n mlops rollout restart deploy/deployer                 # after pushing a new mlops-deployer:v1
# from the workstation, for a dry run only (never a second --loop next to the Deployment)
uv run --env-file .env python -m deployer --dry-run              # .env: GITHUB_TOKEN=..., port-forwards open
uv run python -m pytest tests/test_deployer.py                   # not `uv run pytest`: the global pytest is broken
```

`deployer/models.yaml` lists all six models; an entry without `@production` is skipped, so the RAM cost (about 1 GB
per InferenceService) only appears once a model is promoted. Comment entries out if the cluster cannot hold six.

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

## Pipeline in the cluster (Day 12, updated)

Batch work runs as pods from the `mlops-pipeline` image in namespace `pipeline`, started by Airflow (see "Airflow in
the cluster"). Until 23/10/2026 Airflow ran standalone in Docker with a kind kubeconfig (`airflow/start.ps1`, removed)
and images were side-loaded with `kind load`; both are gone. The feature runs no longer have to be copied into the
PVC either: `features.build_training` writes them there from the cluster. `20-data-loader.yaml` stays for inspecting
the PVC, `30-smoke-train.yaml` for a train without MLflow:

```powershell
kubectl apply -f pipeline\k8s\30-smoke-train.yaml; kubectl -n pipeline logs -f job/smoke-train; kubectl delete -f pipeline\k8s\30-smoke-train.yaml
```

Each `<usecase>_train` DAG is build_training -> train -> `training.promote` WITHOUT `--approve` (prints the gate;
exit 1 = REFUSED, no retry). Nothing in Airflow may set `@production`: that stays a human step.

Measured with the old standalone setup (21-22/10/2026): image 2.15 GB; smoke train about 1.3 GB RAM peak (limit 2 GB), 6 models in about 25 s;
Airflow container about 1.56 GiB while starting, about 0.57 GiB idle; DAG run train -> gate 1 min 38 s (train pod 71 s
including start, gate pod 9 s). The registered run carries `git_commit` of the image (28d9e2a) instead of `unknown`.

## Monitoring tables: Iceberg on MinIO (Day 13)

One Iceberg catalog for everything in the cluster: a PyIceberg `SqlCatalog` stored in the Postgres database
`iceberg_catalog` (the Postgres that already backs MLflow) with data in `s3://warehouse/` (MinIO), namespaces
`gold`, `features`, `monitoring`. Pods and the host read the same tables, and table locations are `s3://` URIs
instead of `C:\...`. The local SQLite catalog (`data/catalog_full`) is only the source of `scripts/migrate_gold.py`.
A production setup would use one REST catalog (Lakekeeper, Polaris, Nessie).

One-time setup (bucket `warehouse` is also in `minio-values.yaml` for a fresh install):

```powershell
kubectl -n mlops exec postgres-postgresql-0 -- env PGPASSWORD=mlflowpassword psql -U postgres -c "CREATE DATABASE iceberg_catalog"
kubectl -n mlops exec deploy/minio -- sh -c "mc alias set local http://localhost:9000 minioadmin minioadmin && mc mb --ignore-existing local/warehouse"
.\infra\port-forward.ps1                     # now also Postgres on 127.0.0.1:5432 (catalog access from the host)
```

| Table (namespace `monitoring`) | Written by | Partition | Re-run |
|---|---|---|---|
| `pred_<usecase>` | `pipeline.predict --usecase U --date D [--end E]` | `score_date` | replaces that day |
| `drift_<usecase>` | `pipeline.drift --usecase U --date D [--reference R]` | `current_date` | replaces (D, R) |
| `eval_<usecase>` | `pipeline.evaluate --usecase U --start S --end E` | `window_end` | replaces (S, E) |

`<usecase>` = `loan_propensity` (all accounts, segments nu/lu/au), `overdue_risk` (only `overdue_eligible = 1`,
segments lu/au), `campaign_response` (the DELIVERED sends of the day, one model `_all`, `pred_` rows carry
`campaign_event_id`). Thresholds live in `pipeline/monitoring.yaml`, one entry per use case (still [TODO] for mentor
confirmation in the design doc). Drift HTML reports: `s3://warehouse/reports/drift/<usecase>/<day>_vs_<reference>.html`
(MinIO console, port 9001). DAGs per use case: `<usecase>_predict` = wait_features (control.fs_status COMPLETE) ->
predict -> drift -> retrain_check (exit 99 = skip) -> trigger `<usecase>_train`; `<usecase>_evaluate` weekly. Dates are
DAG params because the synthetic data has no "today" (features end 2026-01-30, labels end 2025-12-31, the last
campaign is sent 2026-01-16: `campaign_response_predict` defaults to that day).

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
| MinIO `ImagePullBackOff`, `401 UNAUTHORIZED` | MinIO no longer serves public images (quay.io 401, Docker Hub denied) | the cached `minio/minio:RELEASE.2024-12-18T13-15-44Z` is mirrored into Harbor once (section "Images") and `minio-values.yaml` pulls it from there. Keep the local copy (`docker save`) until the mirror exists |
| A feature day fails with `no features.fs_state partition for <T-1>` | the daily job continues the state of the day before; a day was skipped or the store is new | run the missing day first (`features.backfill --start <gap> --end <T>`), or `--bootstrap` to start a new history |
| `<usecase>_predict` stuck in `wait_features` | `control.fs_status` has no COMPLETE row for `score_date` | look at `features.status --date <day>`: WRITTEN/QUALITY_FAILED means the feature DAG stopped there |
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
