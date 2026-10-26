# Bring up the MLOps platform (namespace mlops) on the kind cluster of the current kubectl context.
#   .\infra\bootstrap.ps1                 # cluster = current context kind-<name>
#   .\infra\bootstrap.ps1 -Cluster lab
# Idempotent: re-running only reconciles what changed.
param([string]$Cluster)
$ErrorActionPreference = "Stop"

# MinIO stopped serving public images (quay.io -> 401, Docker Hub minio/* denied), so the chart
# runs a copy from the local Docker cache, loaded into the kind node (pullPolicy: Never).
$MinioImage = "minio/minio:RELEASE.2024-12-18T13-15-44Z"

$context = kubectl config current-context
if (-not $Cluster) {
    if ($context -notlike "kind-*") { throw "current context '$context' is not a kind cluster; pass -Cluster" }
    $Cluster = $context.Substring(5)
}
if ((kind get clusters) -notcontains $Cluster) {
    throw "kind cluster '$Cluster' does not exist (kind get clusters). Create it: kind create cluster --name $Cluster"
}
if ($context -ne "kind-$Cluster") { throw "kubectl context is '$context', expected 'kind-$Cluster' (kubectl config use-context kind-$Cluster)" }
Write-Host "==> cluster $Cluster"
kubectl get nodes

Write-Host "==> loading $MinioImage into kind"
docker image inspect $MinioImage *> $null
if ($LASTEXITCODE -ne 0) { throw "$MinioImage is not in the local Docker cache; it can no longer be pulled from quay.io/Docker Hub" }
kind load docker-image $MinioImage --name $Cluster

Write-Host "==> helmfile sync (waits for Ready; first MLflow image pull can take 10+ minutes)"
helmfile --file "$PSScriptRoot\helmfile.yaml" sync
if ($LASTEXITCODE -ne 0) { throw "helmfile sync failed: kubectl get pods -n mlops; kubectl describe pod <pod> -n mlops" }

kubectl get pods,svc -n mlops
Write-Host "==> done. Next: .\infra\port-forward.ps1"
