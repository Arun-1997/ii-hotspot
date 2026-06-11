# Full production run: gate -> pipeline -> deliverables (Windows).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\run_pipeline.ps1 configs\<municipality>.toml
param(
    [Parameter(Mandatory = $true)][string]$Config
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $env:KNMI_API_KEY) {
    Write-Error "KNMI_API_KEY is not set (free key: developer.dataplatform.knmi.nl)"
}
if (Test-Path ".venv") { & .\.venv\Scripts\Activate.ps1 }

python -m ii_hotspot --selftest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ii_hotspot --run --config $Config
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
