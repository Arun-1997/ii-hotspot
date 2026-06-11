# One-time environment setup + verification gate (Windows).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 [-CoreOnly]
param([switch]$CoreOnly)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$extras = if ($CoreOnly) { "dev" } else { "dev,geo" }

if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e ".[$extras]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

ruff check src tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ii_hotspot --selftest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "bootstrap complete: environment verified."
