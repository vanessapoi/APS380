$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$profilePath = Join-Path $projectRoot '.local\tesla-ai-profile'
$runtimePath = Join-Path $projectRoot 'external\torcs-1.3.10\runtime'
if (-not (Test-Path -LiteralPath (Join-Path $profilePath 'race.xml'))) {
    throw 'Run scripts/run_tesla_ai.py first to build and configure the autonomous driver.'
}
$env:APS380_TORCS_PROFILE = $profilePath
$env:APS380_AI_LOG = Join-Path $runtimePath ('telemetry\aps380_ai_visible_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.csv')
Push-Location $runtimePath
try {
    & .\wtorcs.exe
    if ($LASTEXITCODE -ne 0) { throw "TORCS exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
