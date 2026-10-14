# Expose MLflow and MinIO on localhost (the defaults used by training/registry.py and day1_verify.py):
#   MLflow  http://127.0.0.1:5050  -> svc/mlflow:80   (chart 1.x; container port 5000)
#   MinIO   http://127.0.0.1:9000  -> svc/minio:9000
# Runs as background jobs of THIS PowerShell session; keep the window open.
# Stop: Get-Job pf-* | Stop-Job -PassThru | Remove-Job
$ErrorActionPreference = "Stop"
$forwards = @{ "pf-mlflow" = "svc/mlflow 5050:80"; "pf-minio" = "svc/minio 9000:9000" }

Get-Job pf-* -ErrorAction SilentlyContinue | Stop-Job -PassThru | Remove-Job
foreach ($name in $forwards.Keys) {
    $target, $ports = $forwards[$name].Split(" ")
    Start-Job -Name $name -ScriptBlock { param($t, $p) kubectl port-forward -n mlops $t $p } -ArgumentList $target, $ports | Out-Null
}

$checks = @{ "MLflow" = "http://127.0.0.1:5050/health"; "MinIO" = "http://127.0.0.1:9000/minio/health/live" }
foreach ($svc in $checks.Keys) {
    $ok = $false
    foreach ($i in 1..15) {
        try { Invoke-WebRequest $checks[$svc] -UseBasicParsing -TimeoutSec 2 | Out-Null; $ok = $true; break }
        catch { Start-Sleep -Seconds 1 }
    }
    if ($ok) { Write-Host "$svc OK  ($($checks[$svc]))" }
    else { Write-Host "$svc NOT reachable; see: Receive-Job pf-*" -ForegroundColor Red }
}
