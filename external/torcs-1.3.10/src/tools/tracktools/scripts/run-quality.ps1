$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    if ($env:CONDA_DEFAULT_ENV -eq "torcs-tracktools") {
        python scripts\quality.py @args
    }
    elseif (Test-Path (Join-Path $Root ".venv\Scripts\python.exe")) {
        & (Join-Path $Root ".venv\Scripts\python.exe") scripts\quality.py @args
    }
    elseif (Get-Command conda -ErrorAction SilentlyContinue) {
        conda run --no-capture-output -n torcs-tracktools python scripts\quality.py @args
    }
    elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        uv run python scripts\quality.py @args
    }
    else {
        throw "No usable tracktools environment found. Run scripts/setup-conda.ps1, scripts/setup-venv.ps1, or scripts/setup-uv.ps1."
    }
}
finally {
    Pop-Location
}
