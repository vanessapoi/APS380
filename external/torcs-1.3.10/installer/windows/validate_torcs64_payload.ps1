Param(
    [string]$NsiPath = (Join-Path $PSScriptRoot "torcs64.nsi"),
    [string]$BaseDir = (Join-Path $PSScriptRoot "base"),
    [string]$IgnoreListPath = (Join-Path $PSScriptRoot "payload-ignore.txt"),
    [switch]$IncludeDoc
)

$ErrorActionPreference = "Stop"

function Normalize-RelativePath {
    Param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return ""
    }

    $normalized = $Path.Trim().Trim('"').Replace('/', '\')

    while ($normalized.StartsWith(".\")) {
        $normalized = $normalized.Substring(2)
    }

    while ($normalized.StartsWith("\")) {
        $normalized = $normalized.Substring(1)
    }

    return $normalized
}

if (-not (Test-Path -LiteralPath $NsiPath -PathType Leaf)) {
    throw "NSI file not found: $NsiPath"
}

if (-not (Test-Path -LiteralPath $BaseDir -PathType Container)) {
    throw "Base directory not found: $BaseDir"
}

$baseRoot = (Resolve-Path -LiteralPath $BaseDir).Path.TrimEnd('\', '/')
$nsiFile = (Resolve-Path -LiteralPath $NsiPath).Path

$baseFiles = New-Object "System.Collections.Generic.HashSet[string]" ([System.StringComparer]::OrdinalIgnoreCase)
Get-ChildItem -LiteralPath $baseRoot -Recurse -File | ForEach-Object {
    $fullPath = $_.FullName
    $relativePath = Normalize-RelativePath ($fullPath.Substring($baseRoot.Length))

    if (-not $IncludeDoc -and $relativePath.StartsWith("doc\", [System.StringComparison]::OrdinalIgnoreCase)) {
        return
    }

    [void]$baseFiles.Add($relativePath)
}

$ignored = New-Object "System.Collections.Generic.HashSet[string]" ([System.StringComparer]::OrdinalIgnoreCase)
if (Test-Path -LiteralPath $IgnoreListPath -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $IgnoreListPath) {
        $trimmed = $line.Trim()
        if ($trimmed -eq "" -or $trimmed.StartsWith("#") -or $trimmed.StartsWith(";")) {
            continue
        }

        $normalizedIgnore = Normalize-RelativePath $trimmed
        if ($normalizedIgnore.StartsWith("base\", [System.StringComparison]::OrdinalIgnoreCase)) {
            $normalizedIgnore = Normalize-RelativePath ($normalizedIgnore.Substring(5))
        }

        [void]$ignored.Add($normalizedIgnore)
    }
}

$nsiBaseFiles = New-Object "System.Collections.Generic.HashSet[string]" ([System.StringComparer]::OrdinalIgnoreCase)
$lineNumber = 0
foreach ($line in Get-Content -LiteralPath $nsiFile) {
    $lineNumber++

    if ($line -match '^\s*;' -or -not ($line -match '^\s*File\b(?<rest>.*)$')) {
        continue
    }

    $rest = $Matches['rest'].Trim()
    if ($rest -eq "") {
        continue
    }

    while ($rest.StartsWith('/')) {
        $optionEnd = $rest.IndexOf(' ')
        if ($optionEnd -lt 0) {
            $rest = ""
            break
        }

        $rest = $rest.Substring($optionEnd + 1).TrimStart()
    }

    if ($rest -eq "") {
        continue
    }

    $sourceToken = $null
    if ($rest.StartsWith('"')) {
        $closingQuote = $rest.IndexOf('"', 1)
        if ($closingQuote -gt 1) {
            $sourceToken = $rest.Substring(1, $closingQuote - 1)
        }
    } else {
        $firstSpace = $rest.IndexOf(' ')
        if ($firstSpace -lt 0) {
            $sourceToken = $rest
        } else {
            $sourceToken = $rest.Substring(0, $firstSpace)
        }
    }

    if ($null -eq $sourceToken) {
        continue
    }

    $normalizedSource = Normalize-RelativePath $sourceToken
    if ($normalizedSource.StartsWith("base\", [System.StringComparison]::OrdinalIgnoreCase)) {
        $relativeFromBase = Normalize-RelativePath ($normalizedSource.Substring(5))
        if ($relativeFromBase -ne "") {
            [void]$nsiBaseFiles.Add($relativeFromBase)
        }
    }
}

$missingInNsi = New-Object System.Collections.Generic.List[string]
foreach ($item in $baseFiles) {
    if (-not $nsiBaseFiles.Contains($item) -and -not $ignored.Contains($item)) {
        $missingInNsi.Add($item)
    }
}

$staleInNsi = New-Object System.Collections.Generic.List[string]
foreach ($item in $nsiBaseFiles) {
    if (-not $IncludeDoc -and $item.StartsWith("doc\", [System.StringComparison]::OrdinalIgnoreCase)) {
        continue
    }

    if (-not $baseFiles.Contains($item) -and -not $ignored.Contains($item)) {
        $staleInNsi.Add($item)
    }
}

$missingSorted = $missingInNsi | Sort-Object
$staleSorted = $staleInNsi | Sort-Object

Write-Host "Payload validation summary"
Write-Host "- NSI file: $nsiFile"
Write-Host "- Base directory: $baseRoot"
Write-Host "- Base files: $($baseFiles.Count)"
Write-Host "- Doc coverage checked: $($IncludeDoc.IsPresent)"
Write-Host "- NSI base file entries: $($nsiBaseFiles.Count)"
Write-Host "- Ignored entries: $($ignored.Count)"
Write-Host "- Missing in NSI: $($missingSorted.Count)"
Write-Host "- Stale in NSI: $($staleSorted.Count)"

if ($missingSorted.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing in torcs64.nsi (present in base, absent in File lines):"
    foreach ($path in $missingSorted) {
        Write-Host "  $path"
    }
}

if ($staleSorted.Count -gt 0) {
    Write-Host ""
    Write-Host "Stale in torcs64.nsi (present in File lines, absent in base):"
    foreach ($path in $staleSorted) {
        Write-Host "  $path"
    }
}

if ($missingSorted.Count -gt 0 -or $staleSorted.Count -gt 0) {
    throw "Payload validation failed. Update torcs64.nsi or payload-ignore.txt."
}

Write-Host ""
Write-Host "Payload validation passed."
