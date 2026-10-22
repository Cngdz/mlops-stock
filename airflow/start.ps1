# Start (or restart) Airflow standalone in Docker, orchestrating pods in the kind cluster.
#   .\airflow\start.ps1          # create the container, or start it if it already exists
#   docker stop airflow          # free the RAM when not demoing (history stays)
#   docker rm -f airflow         # throw it away (run history is lost)
# UI: http://localhost:8080  user: admin  password: docker logs airflow | Select-String password
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$Cluster = "lab"
$Image = "apache/airflow:2.10.5-python3.11"

if ((docker ps -a --format '{{.Names}}') -contains "airflow") {
    docker start airflow | Out-Null
    Write-Host "airflow started. UI: http://localhost:8080"
    exit 0
}

if ((kind get clusters) -notcontains $Cluster) { throw "kind cluster '$Cluster' not found" }
New-Item -ItemType Directory -Force airflow\dags | Out-Null

# --internal: the API server address as seen from the `kind` Docker network (https://<node>:6443),
# not 127.0.0.1:<port>, which inside this container would be the container itself.
# The file holds cluster-admin credentials: it is git-ignored, never commit it.
kind get kubeconfig --name $Cluster --internal | Set-Content -Encoding ascii airflow\kubeconfig

docker run -d --name airflow --network kind -p 8080:8080 `
    -e AIRFLOW__CORE__LOAD_EXAMPLES=False `
    -e AIRFLOW__WEBSERVER__WORKERS=1 `
    -e AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL=30 `
    -v "${PWD}\airflow\dags:/opt/airflow/dags" `
    -v "${PWD}\airflow\kubeconfig:/opt/airflow/kubeconfig:ro" `
    $Image standalone
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }
Write-Host "airflow starting (1-2 min). UI: http://localhost:8080  password: docker logs airflow | Select-String password"
