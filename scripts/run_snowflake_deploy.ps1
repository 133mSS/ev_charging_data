[CmdletBinding()]
param(
    [switch]$IncludeStatic,
    [switch]$SkipCoreLoad,
    [switch]$AppOnly,
    [switch]$WarehouseOnly
)

$ErrorActionPreference = "Stop"
if ($WarehouseOnly -and ($IncludeStatic -or $SkipCoreLoad -or $AppOnly)) {
    throw "-WarehouseOnly cannot be combined with -IncludeStatic, -SkipCoreLoad, or -AppOnly."
}
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $env:LOCALAPPDATA) {
    throw "LOCALAPPDATA is not defined. Create a Python environment on a drive with free space."
}

$ClientRoot = Join-Path $env:LOCALAPPDATA "JPL-Snowflake-Client"
$VenvPath = Join-Path $ClientRoot "venv"
$TempPath = Join-Path $ClientRoot "temp"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

New-Item -ItemType Directory -Path $ClientRoot -Force | Out-Null
New-Item -ItemType Directory -Path $TempPath -Force | Out-Null

# Keep pip and Snowflake PUT temporary files away from the nearly-full project drive.
$env:TEMP = $TempPath
$env:TMP = $TempPath
$env:TMPDIR = $TempPath

if (-not (Test-Path $PythonExe)) {
    $BootstrapPython = (Get-Command python -ErrorAction Stop).Source
    $Version = & $BootstrapPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect the selected Python interpreter."
    }
    $Parts = $Version.Split(".")
    $Major = [int]$Parts[0]
    $Minor = [int]$Parts[1]
    if ($Major -ne 3 -or $Minor -lt 11) {
        throw "Snowflake deploy client requires Python 3.11 or later. Current: $Version"
    }

    Write-Host "Creating Snowflake client environment at $VenvPath using Python $Version" -ForegroundColor Cyan
    & $BootstrapPython -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the client virtual environment."
    }
}

Write-Host "Installing Snowflake client requirements on the system drive..." -ForegroundColor Cyan
& $PythonExe -m pip install --disable-pip-version-check --no-cache-dir -r (Join-Path $ProjectRoot "requirements-snowflake.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install Snowflake connector requirements."
}

$PythonArgs = @()
if ($IncludeStatic) {
    $PythonArgs += "--include-static"
}
if ($SkipCoreLoad) {
    $PythonArgs += "--skip-core-load"
}
if ($AppOnly) {
    $PythonArgs += "--app-only"
}
if ($WarehouseOnly) {
    $PythonArgs += "--warehouse-only"
}

Push-Location $ProjectRoot
try {
    Write-Host "Using Python: $PythonExe"
    Write-Host "Temporary files: $TempPath"
    & $PythonExe (Join-Path $ProjectRoot "scripts\deploy_snowflake.py") @PythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Snowflake deployment failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
