param(
    [string]$Version = "",
    [string]$Repository = "penghanli/pyvpn",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
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
$expectedNames = @(
    "pyvpn-offline-client-windows-x64-$Version.zip",
    "pyvpn-offline-client-linux-x86_64-$Version.tar.gz",
    "pyvpn-offline-server-linux-x86_64-$Version.tar.gz",
    "pyvpn-offline-client-linux-arm64-$Version.tar.gz",
    "pyvpn-offline-server-linux-arm64-$Version.tar.gz",
    "pyvpn-offline-client-macos-x86_64-$Version.tar.gz",
    "pyvpn-offline-client-macos-arm64-$Version.tar.gz",
    "pyvpn-offline-all-$Version.zip",
    "SHA256SUMS"
)

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
foreach ($name in $expectedNames) {
    $asset = $release.assets | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $asset) {
        throw "Release $tag is missing asset: $name"
    }
    $destination = Join-Path $OutputDir $name
    Write-Host "Downloading $name"
    Invoke-WebRequest -Uri $asset.browser_download_url -Headers $headers -OutFile $destination
}

$manifestPath = Join-Path $OutputDir "SHA256SUMS"
foreach ($line in Get-Content -LiteralPath $manifestPath) {
    if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
        throw "Invalid release SHA256SUMS line: $line"
    }
    $path = Join-Path $OutputDir $Matches[2]
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actual -ne $Matches[1]) {
        throw "Release checksum failed: $($Matches[2])"
    }
}

Write-Host "Downloaded and verified pyvpn offline release $Version in $OutputDir"
