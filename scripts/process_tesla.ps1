$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$pythonProject = Join-Path $projectRoot 'aps380_torcs_starter'
$telemetryDir = Join-Path $projectRoot 'external\torcs-1.3.10\runtime\telemetry'
$recording = Get-ChildItem -LiteralPath $telemetryDir -Filter 'aps380_ev_*.csv' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $recording) { throw 'No EV recording yet. Start a Practice session first.' }
$first = Import-Csv -LiteralPath $recording.FullName | Select-Object -First 1
if (-not $first) { throw 'EV recording has no data rows yet.' }
$profileId = $first.profile_id
if ($profileId -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid profile identifier in recording.' }
$profileFile = Join-Path $telemetryDir ($profileId + '.json')
$outputPath = Join-Path $pythonProject ('output\tesla_' + $recording.BaseName)
$rawPath = Join-Path $outputPath 'raw'
New-Item -ItemType Directory -Path $rawPath -Force | Out-Null
$sourceBefore = Get-Item -LiteralPath $recording.FullName
$sourceLength = $sourceBefore.Length
$sourceWriteTime = $sourceBefore.LastWriteTimeUtc
Copy-Item -LiteralPath $recording.FullName -Destination (Join-Path $rawPath 'drive.csv')
Copy-Item -LiteralPath ([IO.Path]::ChangeExtension($recording.FullName, '.xml')) -Destination (Join-Path $rawPath 'drive.xml')
Copy-Item -LiteralPath $profileFile -Destination (Join-Path $rawPath 'vehicle_profile.json')
$sourceAfter = Get-Item -LiteralPath $recording.FullName
if ($sourceAfter.Length -ne $sourceLength -or $sourceAfter.LastWriteTimeUtc -ne $sourceWriteTime) {
    throw 'Recording is still changing. Pause or finish the race, then process it again.'
}
$snapshotFile = Join-Path $rawPath 'drive.csv'
$snapshotProfile = Join-Path $rawPath 'vehicle_profile.json'
$env:MPLCONFIGDIR = Join-Path $projectRoot '.local\matplotlib'
& (Join-Path $pythonProject '.venv\Scripts\python.exe') (Join-Path $pythonProject 'run_ev.py') `
    --input $snapshotFile --profile $snapshotProfile --output-dir $outputPath
if ($LASTEXITCODE -ne 0) { throw 'EV validation failed; see the error above.' }
& (Join-Path $pythonProject '.venv\Scripts\python.exe') (Join-Path $pythonProject 'validate_ev_drive.py') `
    --input $snapshotFile --profile $snapshotProfile --output-dir (Join-Path $outputPath 'validation')
if ($LASTEXITCODE -ne 0) { throw 'EV drive audit failed; see the error above.' }
