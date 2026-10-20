$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    uv python install 3.12
    uv sync --dev
}
finally {
    Pop-Location
}
