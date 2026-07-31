param(
    [string]$ServerHost = "",
    [string]$Token = "",
    [string]$CertFingerprint = "",
    [int]$ControlPort = 8443,
    [string]$InstallDir = "",
    [string]$ConfigDir = "$env:ProgramData\pyvpn",
    [string]$TunName = "pyvpn0",
    [int]$Mtu = 1280,
    [string[]]$BypassIp = @(),
    [switch]$NoDns
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this installer from a PowerShell window opened with Run as administrator."
    }
}

function Quote-PowerShellString([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Normalize-DirectoryPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full.Length -gt $root.Length) {
        return $full.TrimEnd("\")
    }
    return $full
}

function Resolve-DefaultInstallDir {
    $root = [Environment]::GetEnvironmentVariable("ProgramW6432")
    if ([string]::IsNullOrWhiteSpace($root)) {
        $root = [Environment]::GetEnvironmentVariable("ProgramFiles")
    }
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "Could not determine Program Files. Pass -InstallDir explicitly."
    }
    return Join-Path $root "pyvpn-client"
}

function Get-StandardInstallDirs {
    $dirs = @()
    foreach ($root in @(
        [Environment]::GetEnvironmentVariable("ProgramW6432"),
        [Environment]::GetEnvironmentVariable("ProgramFiles"),
        [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    )) {
        if ([string]::IsNullOrWhiteSpace($root)) {
            continue
        }
        $dir = Join-Path $root "pyvpn-client"
        if ($dirs -notcontains $dir) {
            $dirs += $dir
        }
    }
    return $dirs
}

function Read-RequiredValue([string]$Label, [string]$CurrentValue) {
    if (-not [string]::IsNullOrWhiteSpace($CurrentValue)) {
        return $CurrentValue
    }
    $value = Read-Host $Label
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$Label is required."
    }
    return $value.Trim()
}

function Read-SecretValue([string]$CurrentValue) {
    if (-not [string]::IsNullOrWhiteSpace($CurrentValue)) {
        return $CurrentValue
    }
    $secure = Read-Host "Shared token" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Shared token is required."
    }
    return $value
}

function Write-ForwardingScript([string]$Path, [string]$TargetScript) {
@"
`$ErrorActionPreference = "Stop"
& $(Quote-PowerShellString $TargetScript) @args
exit `$LASTEXITCODE
"@ | Set-Content -Encoding UTF8 -Path $Path
}

function Invoke-ClientHelper([string]$Path) {
    & (Join-Path $PSHOME "powershell.exe") -NoProfile -ExecutionPolicy Bypass -File $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Client helper failed with exit code $LASTEXITCODE`: $Path"
    }
}

function Verify-Package([string]$PackageRoot) {
    $manifest = Join-Path $PackageRoot "SHA256SUMS"
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
        throw "SHA256SUMS is missing. Extract the complete offline package again."
    }
    foreach ($line in Get-Content -LiteralPath $manifest) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        if ($line -notmatch '^([0-9a-f]{64})  (.+)$') {
            throw "Invalid SHA256SUMS line: $line"
        }
        $expected = $Matches[1]
        $relative = $Matches[2].Replace("/", "\")
        $path = Join-Path $PackageRoot $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Offline package file is missing: $relative"
        }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            throw "Offline package checksum failed: $relative"
        }
    }
}

function Get-PeMachine([string]$Path) {
    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    $reader = New-Object System.IO.BinaryReader($stream)
    try {
        if ($reader.ReadUInt16() -ne 0x5A4D) {
            throw "Not a valid PE file: $Path"
        }
        $stream.Position = 0x3C
        $peOffset = $reader.ReadInt32()
        if ($peOffset -lt 0 -or $peOffset -gt ($stream.Length - 6)) {
            throw "Invalid PE header offset: $Path"
        }
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550) {
            throw "Invalid PE signature: $Path"
        }
        return $reader.ReadUInt16()
    } finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

function Backup-File([string]$Path, [string]$BackupDir, [System.Collections.ArrayList]$Entries) {
    $entry = [PSCustomObject]@{
        Path = $Path
        Existed = (Test-Path -LiteralPath $Path -PathType Leaf)
        Backup = ""
    }
    if ($entry.Existed) {
        $backup = Join-Path $BackupDir ([Guid]::NewGuid().ToString("N"))
        Copy-Item -LiteralPath $Path -Destination $backup
        $entry.Backup = $backup
    }
    [void]$Entries.Add($entry)
}

function Restore-Files([System.Collections.ArrayList]$Entries) {
    foreach ($entry in $Entries) {
        if ($entry.Existed) {
            $parent = Split-Path -Parent $entry.Path
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
            Copy-Item -Force -LiteralPath $entry.Backup -Destination $entry.Path
        } else {
            Remove-Item -Force -LiteralPath $entry.Path -ErrorAction SilentlyContinue
        }
    }
}

Assert-Admin
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "This offline package requires 64-bit Windows 10 or Windows 11."
}
if ([Environment]::OSVersion.Version.Major -lt 10) {
    throw "This offline package requires Windows 10 or Windows 11."
}
if ($ControlPort -lt 1 -or $ControlPort -gt 65535) {
    throw "ControlPort must be from 1 to 65535."
}
if ($Mtu -lt 576 -or $Mtu -gt 9000) {
    throw "Mtu must be from 576 to 9000."
}

$packageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$metadataPath = Join-Path $packageRoot "PACKAGE-METADATA"
if (-not (Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
    throw "PACKAGE-METADATA is missing. Extract the complete offline package again."
}
$metadata = ConvertFrom-StringData (Get-Content -Raw -LiteralPath $metadataPath)
if ($metadata.PLATFORM -ne "windows" -or $metadata.ARCH -ne "x64" -or $metadata.ROLE -ne "client") {
    throw "This is not the Windows x64 client package."
}

Verify-Package $packageRoot
$payloadDir = Join-Path $packageRoot "payload\pyvpn-client"
$payloadExe = Join-Path $payloadDir "pyvpn-client.exe"
$payloadWintun = Join-Path $payloadDir "wintun.dll"
if (-not (Test-Path -LiteralPath $payloadExe -PathType Leaf) -or
    -not (Test-Path -LiteralPath $payloadWintun -PathType Leaf)) {
    throw "The Windows client runtime or wintun.dll is missing."
}
if ((Get-PeMachine $payloadExe) -ne 0x8664) {
    throw "The bundled pyvpn client is not an AMD64 executable."
}
if ((Get-PeMachine $payloadWintun) -ne 0x8664) {
    throw "The bundled wintun.dll is not the AMD64 build."
}

Get-ChildItem -LiteralPath $packageRoot -Recurse -File |
    ForEach-Object { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue }
& $payloadExe --help | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The bundled pyvpn-client.exe failed its startup check."
}

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Resolve-DefaultInstallDir
}
$InstallDir = Normalize-DirectoryPath $InstallDir
$ConfigDir = Normalize-DirectoryPath $ConfigDir
$envPath = Join-Path $ConfigDir "client.env.ps1"

$existing = @{}
if (Test-Path -LiteralPath $envPath -PathType Leaf) {
    . $envPath
    foreach ($pair in @{
        ServerHost = "PyVpnServerHost"
        Token = "PyVpnToken"
        CertFingerprint = "PyVpnCertFingerprint"
        TunName = "PyVpnTun"
        Mtu = "PyVpnMtu"
        NoDns = "PyVpnNoDns"
        BypassIp = "PyVpnBypassIps"
        ControlPort = "PyVpnControlPort"
    }.GetEnumerator()) {
        $variable = Get-Variable -Name $pair.Value -ErrorAction SilentlyContinue
        if ($variable) {
            $existing[$pair.Key] = $variable.Value
        }
    }
}

if ([string]::IsNullOrWhiteSpace($ServerHost) -and $existing.ContainsKey("ServerHost")) {
    $ServerHost = [string]$existing.ServerHost
}
if ([string]::IsNullOrWhiteSpace($Token) -and $existing.ContainsKey("Token")) {
    $Token = [string]$existing.Token
}
if ([string]::IsNullOrWhiteSpace($CertFingerprint) -and $existing.ContainsKey("CertFingerprint")) {
    $CertFingerprint = [string]$existing.CertFingerprint
}
if (-not $PSBoundParameters.ContainsKey("ControlPort") -and $existing.ContainsKey("ControlPort")) {
    $ControlPort = [int]$existing.ControlPort
}
if (-not $PSBoundParameters.ContainsKey("TunName") -and $existing.ContainsKey("TunName")) {
    $TunName = [string]$existing.TunName
}
if (-not $PSBoundParameters.ContainsKey("Mtu") -and $existing.ContainsKey("Mtu")) {
    $Mtu = [int]$existing.Mtu
}
if (-not $PSBoundParameters.ContainsKey("NoDns") -and $existing.ContainsKey("NoDns")) {
    $NoDns = [bool]$existing.NoDns
}
if (-not $PSBoundParameters.ContainsKey("BypassIp") -and $existing.ContainsKey("BypassIp")) {
    $BypassIp = @($existing.BypassIp)
}

$ServerHost = Read-RequiredValue "Server host or IP" $ServerHost
$Token = Read-SecretValue $Token
$CertFingerprint = Read-RequiredValue "Certificate fingerprint (sha256:...)" $CertFingerprint
if ($CertFingerprint -notmatch '^sha256:[0-9a-fA-F]{64}$') {
    throw "Certificate fingerprint must be sha256 followed by 64 hexadecimal characters."
}

$runtimeTarget = Join-Path $InstallDir "runtime"
$runtimeNew = Join-Path $InstallDir "runtime.new"
$runtimePrevious = Join-Path $InstallDir "runtime.previous"
$startScript = Join-Path $InstallDir "pyvpn-client-start.ps1"
$upScript = Join-Path $InstallDir "pyvpn-client-up.ps1"
$downScript = Join-Path $InstallDir "pyvpn-client-down.ps1"
$statusScript = Join-Path $InstallDir "pyvpn-client-status.ps1"
$pidPath = Join-Path $ConfigDir "client.pid"
$logPath = Join-Path $ConfigDir "client.log"
$errLogPath = Join-Path $ConfigDir "client.err.log"
$stopPath = Join-Path $ConfigDir "client.stop"

$wasRunning = $false
if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $existingPid = [int](Get-Content -Raw -LiteralPath $pidPath)
    if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
        $wasRunning = $true
    }
}

$backupDir = Join-Path $env:TEMP ("pyvpn-offline-backup-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $backupDir | Out-Null
$backupEntries = New-Object System.Collections.ArrayList
$pathsToBackup = @(
    $envPath,
    $startScript,
    $upScript,
    $downScript,
    $statusScript,
    (Join-Path $ConfigDir "pyvpn-client-start.ps1"),
    (Join-Path $ConfigDir "pyvpn-client-up.ps1"),
    (Join-Path $ConfigDir "pyvpn-client-down.ps1"),
    (Join-Path $ConfigDir "pyvpn-client-status.ps1")
)
foreach ($candidateDir in Get-StandardInstallDirs) {
    foreach ($scriptName in @(
        "pyvpn-client-start.ps1",
        "pyvpn-client-up.ps1",
        "pyvpn-client-down.ps1",
        "pyvpn-client-status.ps1"
    )) {
        $pathsToBackup += Join-Path $candidateDir $scriptName
    }
}
foreach ($path in ($pathsToBackup | Select-Object -Unique)) {
    Backup-File $path $backupDir $backupEntries
}

$oldRuntimeMoved = $false
$newRuntimeInstalled = $false
try {
    $stopCandidates = @(
        (Join-Path $ConfigDir "pyvpn-client-down.ps1"),
        (Join-Path $InstallDir "pyvpn-client-down.ps1")
    )
    foreach ($candidateDir in Get-StandardInstallDirs) {
        $stopCandidates += Join-Path $candidateDir "pyvpn-client-down.ps1"
    }
    foreach ($stopCandidate in ($stopCandidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $stopCandidate -PathType Leaf) {
            Invoke-ClientHelper $stopCandidate
            break
        }
    }
    if ($wasRunning -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        throw "The existing pyvpn client did not stop."
    }

    New-Item -ItemType Directory -Force -Path $InstallDir, $ConfigDir | Out-Null
    Remove-Item -Recurse -Force -LiteralPath $runtimeNew -ErrorAction SilentlyContinue
    Copy-Item -Recurse -LiteralPath $payloadDir -Destination $runtimeNew
    $newExe = Join-Path $runtimeNew "pyvpn-client.exe"
    & $newExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "The copied pyvpn-client runtime failed its startup check."
    }

    Remove-Item -Recurse -Force -LiteralPath $runtimePrevious -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $runtimeTarget -PathType Container) {
        Move-Item -LiteralPath $runtimeTarget -Destination $runtimePrevious
        $oldRuntimeMoved = $true
    }
    Move-Item -LiteralPath $runtimeNew -Destination $runtimeTarget
    $newRuntimeInstalled = $true
    $runtimeExe = Join-Path $runtimeTarget "pyvpn-client.exe"

    $bypassLiteral = "@(" + (($BypassIp | ForEach-Object { Quote-PowerShellString $_ }) -join ",") + ")"
    $noDnsLiteral = if ($NoDns) { '$true' } else { '$false' }
@"
`$PyVpnServerHost = $(Quote-PowerShellString $ServerHost)
`$PyVpnControlPort = $ControlPort
`$PyVpnToken = $(Quote-PowerShellString $Token)
`$PyVpnCertFingerprint = $(Quote-PowerShellString $CertFingerprint)
`$PyVpnTun = $(Quote-PowerShellString $TunName)
`$PyVpnMtu = $Mtu
`$PyVpnNoDns = $noDnsLiteral
`$PyVpnBypassIps = $bypassLiteral
"@ | Set-Content -Encoding UTF8 -Path $envPath

@"
`$ErrorActionPreference = "Stop"
. $(Quote-PowerShellString $envPath)
`$env:PYVPN_TOKEN = `$PyVpnToken
`$argsList = @(
  "--server-host", `$PyVpnServerHost,
  "--control-port", [string]`$PyVpnControlPort,
  "--cert-fingerprint", `$PyVpnCertFingerprint,
  "--tun", `$PyVpnTun,
  "--mtu", [string]`$PyVpnMtu,
  "--stop-file", $(Quote-PowerShellString $stopPath)
)
foreach (`$ip in `$PyVpnBypassIps) {
  if (`$ip) { `$argsList += @("--bypass-ip", `$ip) }
}
if (`$PyVpnNoDns) { `$argsList += "--no-dns" }
& $(Quote-PowerShellString $runtimeExe) @argsList
"@ | Set-Content -Encoding UTF8 -Path $startScript

@"
`$ErrorActionPreference = "Stop"
`$pidPath = $(Quote-PowerShellString $pidPath)
`$logPath = $(Quote-PowerShellString $logPath)
`$errLogPath = $(Quote-PowerShellString $errLogPath)
`$stopPath = $(Quote-PowerShellString $stopPath)
`$startScript = $(Quote-PowerShellString $startScript)
`$quotedStartScript = '"' + `$startScript + '"'
Remove-Item -Force `$stopPath -ErrorAction SilentlyContinue
if (Test-Path `$pidPath) {
  `$oldPid = [int](Get-Content -Raw `$pidPath)
  `$oldProcess = Get-Process -Id `$oldPid -ErrorAction SilentlyContinue
  if (`$oldProcess) {
    Write-Host "pyvpn client is already running with PID `$oldPid"
    exit 0
  }
  Remove-Item -Force `$pidPath
}
`$startOptions = @{
  FilePath = "powershell.exe"
  ArgumentList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", `$quotedStartScript)
  WindowStyle = "Hidden"
  RedirectStandardOutput = `$logPath
  RedirectStandardError = `$errLogPath
  PassThru = `$true
}
`$process = Start-Process @startOptions
Set-Content -Encoding ASCII -Path `$pidPath -Value ([string]`$process.Id)
Start-Sleep -Seconds 2
if (-not (Get-Process -Id `$process.Id -ErrorAction SilentlyContinue)) {
  if (Test-Path `$logPath) { Get-Content `$logPath -Tail 80 }
  if (Test-Path `$errLogPath) { Get-Content `$errLogPath -Tail 80 }
  throw "pyvpn client failed to start"
}
Write-Host "pyvpn client started in the background with PID `$(`$process.Id)"
Write-Host "Log: `$logPath"
Write-Host "Error log: `$errLogPath"
"@ | Set-Content -Encoding UTF8 -Path $upScript

@"
`$ErrorActionPreference = "Continue"
`$pidPath = $(Quote-PowerShellString $pidPath)
`$logPath = $(Quote-PowerShellString $logPath)
`$errLogPath = $(Quote-PowerShellString $errLogPath)
`$stopPath = $(Quote-PowerShellString $stopPath)
`$envPath = $(Quote-PowerShellString $envPath)
if (Test-Path `$envPath) { . `$envPath }
if (Test-Path `$pidPath) {
  `$pidValue = [int](Get-Content -Raw `$pidPath)
  `$process = Get-Process -Id `$pidValue -ErrorAction SilentlyContinue
  if (`$process) {
    Set-Content -Encoding ASCII -Path `$stopPath -Value "stop"
    Start-Sleep -Seconds 5
    `$process = Get-Process -Id `$pidValue -ErrorAction SilentlyContinue
    if (`$process) { Stop-Process -Id `$pidValue -Force -ErrorAction SilentlyContinue }
    Write-Host "pyvpn client stopped"
  }
}
Remove-Item -Force `$pidPath, `$stopPath -ErrorAction SilentlyContinue
if (`$PyVpnTun) {
  `$tun = Get-NetAdapter -Name `$PyVpnTun -ErrorAction SilentlyContinue
  if (`$tun) {
    foreach (`$prefix in @('0.0.0.0/1', '128.0.0.0/1')) {
      Get-NetRoute -AddressFamily IPv4 -DestinationPrefix `$prefix -InterfaceIndex `$tun.ifIndex `
        -ErrorAction SilentlyContinue |
        Remove-NetRoute -Confirm:`$false -ErrorAction SilentlyContinue
    }
    Set-DnsClientServerAddress -InterfaceAlias `$PyVpnTun -ResetServerAddresses `
      -ErrorAction SilentlyContinue
  }
}
if (`$PyVpnServerHost) {
  try {
    `$serverIps = @([System.Net.Dns]::GetHostAddresses(`$PyVpnServerHost) |
      Where-Object { `$_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
      ForEach-Object { `$_.ToString() })
  } catch {
    `$serverIps = @()
  }
  foreach (`$ip in (`$serverIps + `$PyVpnBypassIps | Where-Object { `$_ } | Sort-Object -Unique)) {
    Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "`$ip/32" -ErrorAction SilentlyContinue |
      Remove-NetRoute -Confirm:`$false -ErrorAction SilentlyContinue
  }
}
Write-Host "pyvpn client is stopped"
Write-Host "Log: `$logPath"
Write-Host "Error log: `$errLogPath"
"@ | Set-Content -Encoding UTF8 -Path $downScript

@"
`$pidPath = $(Quote-PowerShellString $pidPath)
`$logPath = $(Quote-PowerShellString $logPath)
`$errLogPath = $(Quote-PowerShellString $errLogPath)
if (Test-Path `$pidPath) {
  `$pidValue = [int](Get-Content -Raw `$pidPath)
  if (Get-Process -Id `$pidValue -ErrorAction SilentlyContinue) {
    Write-Host "pyvpn client is running with PID `$pidValue"
  } else {
    Write-Host "pyvpn client PID file exists, but the process is not running"
  }
} else {
  Write-Host "pyvpn client is not running"
}
Write-Host "Log: `$logPath"
if (Test-Path `$logPath) { Get-Content `$logPath -Tail 40 }
Write-Host "Error log: `$errLogPath"
if (Test-Path `$errLogPath) { Get-Content `$errLogPath -Tail 40 }
"@ | Set-Content -Encoding UTF8 -Path $statusScript

    $scriptTargets = @{
        "pyvpn-client-start.ps1" = $startScript
        "pyvpn-client-up.ps1" = $upScript
        "pyvpn-client-down.ps1" = $downScript
        "pyvpn-client-status.ps1" = $statusScript
    }
    foreach ($scriptName in $scriptTargets.Keys) {
        Write-ForwardingScript (Join-Path $ConfigDir $scriptName) $scriptTargets[$scriptName]
    }
    $installFull = Normalize-DirectoryPath $InstallDir
    foreach ($candidateDir in Get-StandardInstallDirs) {
        $candidateFull = Normalize-DirectoryPath $candidateDir
        if ($candidateFull -eq $installFull) {
            continue
        }
        New-Item -ItemType Directory -Force -Path $candidateDir | Out-Null
        foreach ($scriptName in $scriptTargets.Keys) {
            Write-ForwardingScript (Join-Path $candidateDir $scriptName) $scriptTargets[$scriptName]
        }
    }
    if ($wasRunning) {
        Invoke-ClientHelper (Join-Path $ConfigDir "pyvpn-client-up.ps1")
    }
} catch {
    $failure = $_
    Restore-Files $backupEntries
    Remove-Item -Recurse -Force -LiteralPath $runtimeNew -ErrorAction SilentlyContinue
    if ($newRuntimeInstalled) {
        Remove-Item -Recurse -Force -LiteralPath $runtimeTarget -ErrorAction SilentlyContinue
    }
    if ($oldRuntimeMoved -and (Test-Path -LiteralPath $runtimePrevious -PathType Container)) {
        Remove-Item -Recurse -Force -LiteralPath $runtimeTarget -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $runtimePrevious -Destination $runtimeTarget
    }
    if ($wasRunning) {
        $restoredUp = Join-Path $ConfigDir "pyvpn-client-up.ps1"
        if (Test-Path -LiteralPath $restoredUp -PathType Leaf) {
            try {
                Invoke-ClientHelper $restoredUp
            } catch {
                Write-Warning "The previous client was restored but could not be restarted."
            }
        }
    }
    throw $failure
} finally {
    Remove-Item -Recurse -Force -LiteralPath $backupDir -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "pyvpn offline Windows client $($metadata.VERSION) installed."
Write-Host "Install directory: $InstallDir"
Write-Host "Configuration: $envPath"
Write-Host ""
Write-Host "Connect:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$ConfigDir\pyvpn-client-up.ps1`""
Write-Host "Disconnect:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$ConfigDir\pyvpn-client-down.ps1`""
Write-Host "Status:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$ConfigDir\pyvpn-client-status.ps1`""
