param(
    [ValidateSet('g29', 'keyboard', 'ai', 'listen')][string]$Mode = 'g29',
    [double]$Duration = 500,
    [switch]$SkipBuild,
    [switch]$NoDesktop,
    [switch]$VisibleAi
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectRoot 'aps380_torcs_starter\.venv\Scripts\python.exe'
$runnerPath = Join-Path $projectRoot 'scripts\run_tesla_live.py'
$runnerArgs = @($runnerPath, '--mode', $Mode, '--duration', $Duration)
if ($SkipBuild) { $runnerArgs += '--skip-build' }
if ($NoDesktop) { $runnerArgs += '--no-desktop' }
if ($VisibleAi) { $runnerArgs += '--visible-ai' }
& $pythonPath @runnerArgs
if ($LASTEXITCODE -ne 0) { throw 'Live trial incomplete or a gate failed; inspect its saved report.' }
