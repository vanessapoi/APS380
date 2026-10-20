Param(
    [string]$BaseDir = (Join-Path $PSScriptRoot "base"),
    [string]$RuntimeDir = (Join-Path $PSScriptRoot "..\..\runtime"),
    [switch]$SkipRuntimeClean
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $BaseDir -PathType Container)) {
    throw "Base directory not found: $BaseDir"
}

if (-not $SkipRuntimeClean) {
    if (Test-Path -LiteralPath $RuntimeDir -PathType Container) {
        Write-Host "Removing runtime directory: $RuntimeDir"
        Remove-Item -LiteralPath $RuntimeDir -Recurse -Force
    }

    Write-Host "Creating runtime directory: $RuntimeDir"
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
} else {
    Write-Host "Skipping runtime clean as requested (-SkipRuntimeClean)."
}

$preserveNames = @(
    "stripe.exe",
    "trackeditor.bat",
    "trackeditor"
)

Write-Host "Cleaning installer base directory: $BaseDir"
Write-Host "Preserving:" ($preserveNames -join ", ")

$entries = Get-ChildItem -LiteralPath $BaseDir -Force
foreach ($entry in $entries) {
    if ($preserveNames -contains $entry.Name) {
        Write-Host "Keeping: $($entry.Name)"
        continue
    }

    Write-Host "Removing: $($entry.FullName)"
    Remove-Item -LiteralPath $entry.FullName -Recurse -Force
}

Write-Host "Base cleanup complete."
