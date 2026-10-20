$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
conda env create -f (Join-Path $Root "environment.yml")
