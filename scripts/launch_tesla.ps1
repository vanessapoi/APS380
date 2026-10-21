$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtimePath = Join-Path $projectRoot 'external\torcs-1.3.10\runtime'
$profilePath = Join-Path $projectRoot '.local\tesla-profile'
if (-not (Test-Path -LiteralPath $profilePath)) {
    throw 'Run scripts/configure_tesla.py first.'
}
$env:APS380_TORCS_PROFILE = $profilePath
Push-Location $runtimePath
try {
    # Launch directly in the user's terminal so startup errors remain visible.
    & .\wtorcs.exe
    if ($LASTEXITCODE -ne 0) { throw "TORCS exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
