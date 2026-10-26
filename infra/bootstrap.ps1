# Bring up the MLOps platform on the Kubernetes cluster of the current kubectl context.
#   .\infra\bootstrap.ps1                      # current context
#   .\infra\bootstrap.ps1 -Context lab-admin   # switch context first
# Idempotent: re-running only reconciles what changed. The cluster itself (and its Harbor registry) already exists;
# images are pulled from Harbor, never loaded into nodes by hand. See infra/README.md for the one-time secrets.
param([string]$Context)
$ErrorActionPreference = "Stop"

if ($Context) { kubectl config use-context $Context | Out-Null }
$current = kubectl config current-context
Write-Host "==> context $current"
kubectl get nodes
if ($LASTEXITCODE -ne 0) { throw "cluster not reachable with context '$current'" }

Write-Host "==> namespaces and pull secrets"
foreach ($ns in "mlops", "pipeline", "airflow", "serving") {
    kubectl create namespace $ns --dry-run=client -o yaml | kubectl apply -f - | Out-Null
}
foreach ($ns in "mlops", "pipeline") {
    kubectl -n $ns get secret harbor-pull *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "secret $ns/harbor-pull is missing: kubectl -n $ns create secret docker-registry harbor-pull --docker-server=<harbor> --docker-username=<robot> --docker-password=<token>"
    }
}

Write-Host "==> secrets and RBAC outside Helm"
kubectl apply -f "$PSScriptRoot\bootstrap\minio-s3-secret.yaml" -f "$PSScriptRoot\bootstrap\airflow-connections-secret.yaml"
kubectl apply -f "$PSScriptRoot\..\pipeline\k8s\10-pvc.yaml" -f "$PSScriptRoot\..\pipeline\k8s\40-airflow-rbac.yaml"
kubectl -n airflow get secret airflow-git-credentials *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "    airflow/airflow-git-credentials missing: git-sync can only read a public repo" -ForegroundColor Yellow }

Write-Host "==> helmfile sync (waits for Ready; first MLflow/Airflow image pulls can take 10+ minutes)"
helmfile --file "$PSScriptRoot\helmfile.yaml" sync
if ($LASTEXITCODE -ne 0) { throw "helmfile sync failed: kubectl get pods -A; kubectl describe pod <pod> -n <ns>" }

Write-Host "==> deployer (needs secret mlops/deployer-github and the deployer image in Harbor)"
kubectl apply -f "$PSScriptRoot\..\deployer\k8s\deployer.yaml"

kubectl get pods -n mlops
kubectl get pods -n airflow
Write-Host "==> done. From your machine: .\infra\port-forward.ps1"
