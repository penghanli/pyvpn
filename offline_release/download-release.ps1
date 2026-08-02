param(
    [string]$Version = "",
    [string]$Repository = "penghanli/pyvpn",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$offlineRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = (Get-Content -Raw -LiteralPath (Join-Path $offlineRoot "VERSION")).Trim()
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $offlineRoot "dist"
}

$tag = "offline-v$Version"
$apiUrl = "https://api.github.com/repos/$Repository/releases/tags/$tag"
$headers = @{
    Accept = "application/vnd.github+json"
    "User-Agent" = "pyvpn-offline-release-downloader"
}
$release = Invoke-RestMethod -Uri $apiUrl -Headers $headers

function Invoke-ReleaseDownload([string]$Uri, [string]$Destination) {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        $resume = (Test-Path -LiteralPath $Destination -PathType Leaf) -and
            (Get-Item -LiteralPath $Destination).Length -gt 0
        $curlArguments = @(
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry", "3",
            "--retry-all-errors",
            "--retry-delay", "2",
            "--user-agent", $headers["User-Agent"],
            "--output", $Destination
        )
        if ($resume) {
            $curlArguments += @("--continue-at", "-")
        }
        $curlArguments += $Uri
        & $curl.Source @curlArguments
        $curlExit = $LASTEXITCODE
        if ($curlExit -in @(33, 36) -and $resume) {
            Remove-Item -Force -LiteralPath $Destination -ErrorAction SilentlyContinue
            $curlArguments = $curlArguments |
                Where-Object { $_ -notin @("--continue-at", "-") }
            & $curl.Source @curlArguments
            $curlExit = $LASTEXITCODE
        }
        if ($curlExit -ne 0) {
            throw "curl.exe failed with exit code $curlExit while downloading $Uri"
        }
        return
    }
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -Headers $headers -OutFile $Destination
}
$archiveNames = @(
    "pyvpn-offline-client-windows-x64-$Version.zip",
    "pyvpn-offline-client-linux-x86_64-$Version.tar.gz",
    "pyvpn-offline-server-linux-x86_64-$Version.tar.gz",
    "pyvpn-offline-client-linux-arm64-$Version.tar.gz",
    "pyvpn-offline-server-linux-arm64-$Version.tar.gz",
    "pyvpn-offline-client-macos-x86_64-$Version.tar.gz",
    "pyvpn-offline-client-macos-arm64-$Version.tar.gz",
    "pyvpn-offline-all-$Version.zip"
)

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$manifestName = "SHA256SUMS"
$manifestAsset = $release.assets |
    Where-Object { $_.name -eq $manifestName } |
    Select-Object -First 1
if (-not $manifestAsset) {
    throw "Release $tag is missing asset: $manifestName"
}
$manifestPath = Join-Path $OutputDir $manifestName
$manifestPartial = "$manifestPath.partial"
Remove-Item -Force -LiteralPath $manifestPartial -ErrorAction SilentlyContinue
Invoke-ReleaseDownload $manifestAsset.browser_download_url $manifestPartial
Move-Item -Force -LiteralPath $manifestPartial -Destination $manifestPath

$expectedHashes = @{}
foreach ($line in Get-Content -LiteralPath $manifestPath) {
    if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
        throw "Invalid release SHA256SUMS line: $line"
    }
    $expectedHashes[$Matches[2]] = $Matches[1]
}

foreach ($name in $archiveNames) {
    $asset = $release.assets | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $asset) {
        throw "Release $tag is missing asset: $name"
    }
    if (-not $expectedHashes.ContainsKey($name)) {
        throw "Release SHA256SUMS is missing: $name"
    }
    $destination = Join-Path $OutputDir $name
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
        if ($existingHash -eq $expectedHashes[$name]) {
            Write-Host "Using verified $name"
            continue
        }
    }
    $partial = "$destination.partial"
    Write-Host "Downloading $name"
    Invoke-ReleaseDownload $asset.browser_download_url $partial
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash.ToLowerInvariant()
    if ($actual -ne $expectedHashes[$name]) {
        Remove-Item -Force -LiteralPath $partial -ErrorAction SilentlyContinue
        throw "Release checksum failed: $name"
    }
    Move-Item -Force -LiteralPath $partial -Destination $destination
}

Write-Host "Downloaded and verified pyvpn offline release $Version in $OutputDir"
