Param(
    [string]$RuntimeDir = (Join-Path $PSScriptRoot "..\..\runtime"),
    [string]$DocDir = (Join-Path $PSScriptRoot "..\..\doc"),
    [string]$BaseDir = (Join-Path $PSScriptRoot "base")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $RuntimeDir -PathType Container)) {
    throw "Runtime directory not found: $RuntimeDir"
}

if (-not (Test-Path -LiteralPath $DocDir -PathType Container)) {
    throw "Doc directory not found: $DocDir"
}

if (-not (Test-Path -LiteralPath $BaseDir -PathType Container)) {
    throw "Base directory not found: $BaseDir"
}

Write-Host "Copying runtime to installer base..."
Copy-Item -Path (Join-Path $RuntimeDir "*") -Destination $BaseDir -Recurse -Force

$baseDocDir = Join-Path $BaseDir "doc"
if (Test-Path -LiteralPath $baseDocDir) {
    Write-Host "Removing existing base doc directory: $baseDocDir"
    Remove-Item -LiteralPath $baseDocDir -Recurse -Force
}

Write-Host "Copying doc to installer base..."
Copy-Item -LiteralPath $DocDir -Destination $BaseDir -Recurse -Force

Write-Host "Base population complete."
