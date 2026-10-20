$ErrorActionPreference = "Stop"

if ($args.Count -lt 1) {
    throw "Usage: scripts/run-tool.ps1 <tool-name> [args...]"
}

$Root = Split-Path -Parent $PSScriptRoot
$ToolArgs = @($args)
$Tool = $ToolArgs[0]
$Rest = @($ToolArgs | Select-Object -Skip 1)

Push-Location $Root
try {
    if ($env:CONDA_DEFAULT_ENV -eq "torcs-tracktools") {
        & $Tool @Rest
    }
    elseif (Test-Path (Join-Path $Root ".venv\Scripts\python.exe")) {
        & (Join-Path $Root ".venv\Scripts\python.exe") -m torcs_track_tools.cli.$($Tool -replace '^torcs-', '' -replace '-', '_') @Rest
    }
    elseif (Get-Command conda -ErrorAction SilentlyContinue) {
        conda run -n torcs-tracktools $Tool @Rest
    }
    elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        uv run $Tool @Rest
    }
    else {
        throw "No usable tracktools environment found. Run scripts/setup-conda.ps1, scripts/setup-venv.ps1, or scripts/setup-uv.ps1."
    }
}
finally {
    Pop-Location
}
