# Access from YOUR machine only: everything inside the cluster talks to service DNS names, never to these ports.
#   MLflow         http://127.0.0.1:5050  -> mlops/svc/mlflow:80 (chart 1.x; container port 5000)
#   MinIO S3       http://127.0.0.1:9000  -> mlops/svc/minio:9000
#   MinIO console  http://127.0.0.1:9001  -> mlops/svc/minio-console:9001
#   Postgres       127.0.0.1:5432         -> mlops/svc/postgres-postgresql (Iceberg catalog + control.fs_status)
#   Airflow        http://127.0.0.1:8080  -> airflow/svc/airflow-webserver:8080
# Defaults of training/registry.py and pipeline/catalog.py point at these, so `uv run python -m ...` works from
# the host. Runs as background jobs of THIS PowerShell session; keep the window open.
# Stop: Get-Job pf-* | Stop-Job -PassThru | Remove-Job
$ErrorActionPreference = "Stop"
$forwards = @{
    "pf-mlflow"   = "mlops svc/mlflow 5050:80"
    "pf-minio"    = "mlops svc/minio 9000:9000"
    "pf-console"  = "mlops svc/minio-console 9001:9001"
    "pf-postgres" = "mlops svc/postgres-postgresql 5432:5432"
    "pf-airflow"  = "airflow svc/airflow-webserver 8080:8080"
}

Get-Job pf-* -ErrorAction SilentlyContinue | Stop-Job -PassThru | Remove-Job
foreach ($name in $forwards.Keys) {
    $ns, $target, $ports = $forwards[$name].Split(" ")
    Start-Job -Name $name -ScriptBlock { param($n, $t, $p) kubectl port-forward -n $n $t $p } -ArgumentList $ns, $target, $ports | Out-Null
}

$checks = @{ "MLflow" = "http://127.0.0.1:5050/health"; "MinIO" = "http://127.0.0.1:9000/minio/health/live";
             "Airflow" = "http://127.0.0.1:8080/health" }
foreach ($svc in $checks.Keys) {
    $ok = $false
    foreach ($i in 1..15) {
        try { Invoke-WebRequest $checks[$svc] -UseBasicParsing -TimeoutSec 2 | Out-Null; $ok = $true; break }
        catch { Start-Sleep -Seconds 1 }
    }
    if ($ok) { Write-Host "$svc OK  ($($checks[$svc]))" }
    else { Write-Host "$svc NOT reachable; see: Receive-Job pf-*" -ForegroundColor Red }
}
