$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RepoPath = Join-Path $ProjectRoot "external/ACN-Data-Static"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required. Install Git for Windows and reopen PowerShell."
}

if (-not (Test-Path $RepoPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RepoPath) | Out-Null
    git clone --filter=blob:none --depth 1 --sparse https://github.com/tongxin-li/ACN-Data-Static.git $RepoPath
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}

git -C $RepoPath sparse-checkout set "time series data/jpl/Arroyo_Garage_01"
if ($LASTEXITCODE -ne 0) { throw "git sparse-checkout failed" }

$DataPath = Join-Path $RepoPath "time series data/jpl/Arroyo_Garage_01"
$Count = (Get-ChildItem -Path $DataPath -Filter *.csv.gz -File | Measure-Object).Count
Write-Host "JPL Static files available: $Count"
Write-Host "Static source: $DataPath"
Write-Host "Next: set ACN_API_TOKEN in .env, then run python run_pipeline.py --stage extract"