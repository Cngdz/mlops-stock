<#
Full rebuild for generator 0.2.0 (data_generation_decisions.md).
Steps: 1 sync env | 2 unit tests | 3 calibration | 4 generate sources
       5 ingest to Iceberg | 6 Day 4 features + quality gate
       7 Feast apply + parity check | 8 summary

Usage (from the repo root, PowerShell):
  .\scripts\run_v3_pipeline.ps1                 # run everything
  .\scripts\run_v3_pipeline.ps1 -From 4         # resume from step 4
  .\scripts\run_v3_pipeline.ps1 -Tag v3b        # new output names (re-run without clobbering)
  .\scripts\run_v3_pipeline.ps1 -From 6 -Tag v3e # rebuild features + Feast on existing sources
If PowerShell blocks the script: Set-ExecutionPolicy -Scope Process Bypass
#>
param(
    [int]$From = 1,
    [string]$Tag = "v3",
    [int]$NumAccounts = 5000,
    [int]$FeastAccounts = 300
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$Calibration = "data/generation_calibration_$Tag.json"
$SourceDir   = "data/generated/day4_$Tag"
$Namespace   = "raw_day4_$Tag"

function Step($n, $title, [scriptblock]$body) {
    if ($n -lt $From) { Write-Host "[skip] $n. $title"; return }
    Write-Host ""; Write-Host "=== $n. $title ===" -ForegroundColor Cyan
    $t = Get-Date
    & $body
    if ($LASTEXITCODE -ne 0) { throw "Step $n failed (exit $LASTEXITCODE). Fix it, then rerun with -From $n" }
    Write-Host ("    done in {0:n0}s" -f ((Get-Date) - $t).TotalSeconds) -ForegroundColor Green
}

Step 1 "Sync environment (uv)" { uv sync --frozen }

Step 2 "Unit tests" { uv run python -m unittest discover -s tests -v }

Step 3 "Calibration (pilot 500 accounts, campaigns enabled)" {
    uv run python -m data_generation.calibrate --output $Calibration
}

Step 4 "Generate sources -> $SourceDir" {
    if (Test-Path $SourceDir) { throw "$SourceDir already exists. Use another -Tag or delete it." }
    uv run python -m data_generation.generate_all --num-accounts $NumAccounts --output $SourceDir --calibration $Calibration
}

Step 5 "Ingest to Iceberg namespace $Namespace" {
    uv run python scripts/day3_write_iceberg.py --input-dir $SourceDir --namespace $Namespace
}

Step 6 "Day 4 features, labels and quality gate" {
    uv run python scripts/day4_feature_engineering.py --source-namespace $Namespace
}

Step 7 "Feast apply + parity check (sample: -FeastAccounts, 0 = all)" {
    uv run python scripts/day5_feast_check.py --accounts $FeastAccounts
}

Step 8 "Summary" { uv run python scripts/summarize_run.py --source-dir $SourceDir }
