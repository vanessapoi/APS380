param([switch]$SkipBuild, [switch]$NoDesktop, [switch]$MockInstruments, [switch]$MockArm,
      [ValidateSet('5s','3s','8s')][string]$KeyboardProfile = '5s')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $projectRoot 'aps380_torcs_starter\.venv\Scripts\python.exe'
$runnerArgs = @((Join-Path $projectRoot 'scripts\run_tesla_live.py'), '--mode', 'keyboard', '--duration', '3600')
$runnerArgs += @('--keyboard-profile', $KeyboardProfile)
if ($SkipBuild) { $runnerArgs += '--skip-build' }
if ($NoDesktop) { $runnerArgs += '--no-ui' }
if ($MockInstruments) { $runnerArgs += '--mock-instruments' }
if ($MockArm) { $runnerArgs += '--mock-arm' }
& $pythonPath @runnerArgs
if ($LASTEXITCODE -ne 0) { throw 'Keyboard trial failed; inspect its saved report.' }
