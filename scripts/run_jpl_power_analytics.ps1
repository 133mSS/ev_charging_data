[CmdletBinding()]
param(
    [int]$ChunkSize = 500000,
    [switch]$SkipTests,
    [switch]$LaunchDashboard
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ($ChunkSize -lt 10000) {
    throw "ChunkSize must be at least 10000."
}

Push-Location $ProjectRoot
try {
    if (-not $SkipTests) {
        Write-Host "===== 1/3: UNIT TESTS =====" -ForegroundColor Cyan
        & python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) {
            throw "Unit tests failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "===== 2/3: FULL-STATIC TEMPORAL AUDIT =====" -ForegroundColor Cyan
    & python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11 --all-stations --chunksize $ChunkSize
    if ($LASTEXITCODE -ne 0) {
        throw "Temporal audit failed with exit code $LASTEXITCODE."
    }

    Write-Host "===== 3/3: API-STATIC HOURLY ALIGNMENT =====" -ForegroundColor Cyan
    & python scripts/audit_jpl_api_static_hourly_alignment.py --start-month 2020-07 --end-month 2020-11 --chunksize $ChunkSize
    if ($LASTEXITCODE -ne 0) {
        throw "API-Static alignment failed with exit code $LASTEXITCODE."
    }

    Write-Host "===== POWER ANALYTICS OUTPUTS READY =====" -ForegroundColor Green
    Write-Host "Temporal outputs: data\analytics\jpl_power_temporal"
    Write-Host "API-Static outputs: data\analytics\jpl_api_static_alignment"
    Write-Host "Dashboard command: streamlit run dashboard\power_analytics.py"

    if ($LaunchDashboard) {
        Write-Host "Launching Power dashboard..." -ForegroundColor Cyan
        & streamlit run dashboard/power_analytics.py
        if ($LASTEXITCODE -ne 0) {
            throw "Streamlit exited with code $LASTEXITCODE."
        }
    }
}
finally {
    Pop-Location
}
