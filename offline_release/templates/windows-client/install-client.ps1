param(
    [string]$ServerId = "default",
    [string]$ServerHost = "",
    [string]$Token = "",
    [string]$CertFingerprint = "",
    [int]$ControlPort = 8443,
    [string]$InstallDir = "",
    [string]$ConfigDir = "",
    [string]$TunName = "pyvpn0",
    [int]$Mtu = 1280,
    [string[]]$BypassIp = @(),
    [switch]$NoDns
)

$ErrorActionPreference = "Stop"
$tokenInputSource = Join-Path $PSScriptRoot "token-input.ps1"
if (-not (Test-Path -LiteralPath $tokenInputSource -PathType Leaf)) {
    throw "The package is missing token-input.ps1."
}
. $tokenInputSource

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this installer from a PowerShell window opened with Run as administrator."
    }
}

function Get-NativeWindowsArchitecture {
    $architecture = $env:PROCESSOR_ARCHITEW6432
    if ([string]::IsNullOrWhiteSpace($architecture)) {
        $architecture = $env:PROCESSOR_ARCHITECTURE
    }
    if ([string]::IsNullOrWhiteSpace($architecture)) {
        return "unknown"
    }
    switch ($architecture.ToUpperInvariant()) {
        "AMD64" { return "x64" }
        "ARM64" { return "arm64" }
        "X86" { return "x86" }
        default { return $architecture.ToLowerInvariant() }
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

function Invoke-ClientHelper([string]$Path, [string[]]$Arguments = @()) {
    & (Join-Path $PSHOME "powershell.exe") -NoProfile -ExecutionPolicy Bypass -File $Path @Arguments
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

function Protect-LocalInstall([string]$Path) {
    $systemRule = "*S-1-5-18:(OI)(CI)F"
    $adminRule = "*S-1-5-32-544:(OI)(CI)F"
    & icacls.exe $Path /inheritance:r /grant:r $systemRule $adminRule | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not protect the local installation directory ACL: $Path"
    }
}

Assert-Admin
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "This package requires 64-bit Windows 10 or Windows 11."
}
$nativeArchitecture = Get-NativeWindowsArchitecture
if ($nativeArchitecture -ne "x64") {
    throw "This package requires an x64 (AMD64) Windows computer; detected $nativeArchitecture."
}
if ([Environment]::OSVersion.Version.Major -lt 10) {
    throw "This package requires Windows 10 or Windows 11."
}
if ($ControlPort -lt 1 -or $ControlPort -gt 65535) {
    throw "ControlPort must be from 1 to 65535."
}
if ($Mtu -lt 576 -or $Mtu -gt 9000) {
    throw "Mtu must be from 576 to 9000."
}

$packageRoot = Normalize-DirectoryPath (Split-Path -Parent $MyInvocation.MyCommand.Path)
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
    $InstallDir = Join-Path $packageRoot "pyvpn-client"
}
$InstallDir = Normalize-DirectoryPath $InstallDir
if ([string]::IsNullOrWhiteSpace($ConfigDir)) {
    $ConfigDir = Join-Path $InstallDir "config"
}
$ConfigDir = Normalize-DirectoryPath $ConfigDir
$payloadFull = Normalize-DirectoryPath $payloadDir
if ($InstallDir -eq $packageRoot -or $InstallDir -eq $payloadFull -or
    $InstallDir.StartsWith($payloadFull + "\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallDir must be a new directory outside the packaged payload."
}
$driveRoot = [System.IO.Path]::GetPathRoot($InstallDir)
if ([string]::IsNullOrWhiteSpace($driveRoot)) {
    throw "Could not determine the installation drive."
}
$drive = New-Object System.IO.DriveInfo($driveRoot)
$payloadBytes = (Get-ChildItem -LiteralPath $payloadDir -Recurse -File |
    Measure-Object -Property Length -Sum).Sum
$requiredBytes = [int64]($payloadBytes * 3 + 50MB)
if ($drive.IsReady -and $drive.AvailableFreeSpace -lt $requiredBytes) {
    throw "Not enough free disk space. At least $requiredBytes bytes are required."
}

$profilesPath = Join-Path $ConfigDir "servers.json"
$connectionOptions = @(
    "ServerHost", "Token", "CertFingerprint", "ControlPort", "TunName", "Mtu", "BypassIp", "NoDns"
)
$profileInputProvided = $false
foreach ($name in $connectionOptions) {
    if ($PSBoundParameters.ContainsKey($name)) {
        $profileInputProvided = $true
        break
    }
}
$profilesExist = Test-Path -LiteralPath $profilesPath -PathType Leaf
$writeProfile = (-not $profilesExist) -or $profileInputProvided
$selectExistingProfile = $profilesExist -and (-not $writeProfile) -and
    $PSBoundParameters.ContainsKey("ServerId")
if ($writeProfile) {
    $ServerHost = Read-RequiredValue "Server host or IP" $ServerHost
    $Token = Read-PyVpnSecretToken $Token
    $CertFingerprint = Read-RequiredValue "Certificate fingerprint (sha256:...)" $CertFingerprint
    if ($ServerId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
        throw "ServerId must contain only letters, digits, dots, underscores, or hyphens."
    }
    if ($CertFingerprint -notmatch '^sha256:[0-9a-fA-F]{64}$') {
        throw "Certificate fingerprint must be sha256 followed by 64 hexadecimal characters."
    }
}

$runtimeTarget = Join-Path $InstallDir "runtime"
$runtimeNew = Join-Path $InstallDir "runtime.new"
$runtimePrevious = Join-Path $InstallDir "runtime.previous"
$startScript = Join-Path $InstallDir "pyvpn-client-start.ps1"
$upScript = Join-Path $InstallDir "pyvpn-client-up.ps1"
$downScript = Join-Path $InstallDir "pyvpn-client-down.ps1"
$statusScript = Join-Path $InstallDir "pyvpn-client-status.ps1"
$serversScript = Join-Path $InstallDir "pyvpn-client-servers.ps1"
$switchScript = Join-Path $InstallDir "pyvpn-client-switch.ps1"
$tokenInputScript = Join-Path $InstallDir "pyvpn-client-token-input.ps1"
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

Write-Host "Environment check passed: Windows x64, administrator, package, runtime, and disk space."
$backupDir = Join-Path $env:TEMP ("pyvpn-offline-backup-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $backupDir | Out-Null
$backupEntries = New-Object System.Collections.ArrayList
foreach ($path in @(
    $profilesPath,
    $startScript,
    $upScript,
    $downScript,
    $statusScript,
    $serversScript,
    $switchScript,
    $tokenInputScript
)) {
    Backup-File $path $backupDir $backupEntries
}

$oldRuntimeMoved = $false
$newRuntimeInstalled = $false
try {
    if (Test-Path -LiteralPath $downScript -PathType Leaf) {
        Invoke-ClientHelper $downScript | Out-Null
    }
    if ($wasRunning -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        throw "The existing local pyvpn client did not stop."
    }

    New-Item -ItemType Directory -Force -Path $InstallDir, $ConfigDir | Out-Null
    Protect-LocalInstall $InstallDir
    Copy-Item -Force -LiteralPath $tokenInputSource -Destination $tokenInputScript
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

    if ($writeProfile) {
        $profileArgs = @(
            "servers", "--file", $profilesPath, "add", $ServerId,
            "--server-host", $ServerHost,
            "--control-port", [string]$ControlPort,
            "--cert-fingerprint", $CertFingerprint,
            "--tun", $TunName,
            "--mtu", [string]$Mtu,
            "--replace", "--use"
        )
        foreach ($ip in $BypassIp) {
            if ($ip) { $profileArgs += @("--bypass-ip", $ip) }
        }
        if ($NoDns) { $profileArgs += "--no-dns" }
        $oldToken = $env:PYVPN_TOKEN
        try {
            $env:PYVPN_TOKEN = $Token
            & $runtimeExe @profileArgs | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not save the initial server profile." }
        } finally {
            $env:PYVPN_TOKEN = $oldToken
        }
    } else {
        & $runtimeExe servers --file $profilesPath list --no-probe | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "The existing servers.json file is invalid." }
        if ($selectExistingProfile) {
            & $runtimeExe servers --file $profilesPath use $ServerId | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not select server_id: $ServerId" }
        }
    }

@"
`$ErrorActionPreference = "Stop"
`$runtimeExe = $(Quote-PowerShellString $runtimeExe)
`$clientArgs = @(
  "--profiles",
  $(Quote-PowerShellString $profilesPath),
  "--stop-file",
  $(Quote-PowerShellString $stopPath)
)
& `$runtimeExe @clientArgs
exit `$LASTEXITCODE
"@ | Set-Content -Encoding UTF8 -Path $startScript

@"
`$ErrorActionPreference = "Stop"
`$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
`$principal = New-Object Security.Principal.WindowsPrincipal(`$identity)
if (-not `$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Run this command from an administrator PowerShell window."
}
`$pidPath = $(Quote-PowerShellString $pidPath)
`$logPath = $(Quote-PowerShellString $logPath)
`$errLogPath = $(Quote-PowerShellString $errLogPath)
`$stopPath = $(Quote-PowerShellString $stopPath)
`$startScript = $(Quote-PowerShellString $startScript)
`$powershellExe = Join-Path `$PSHOME "powershell.exe"
Remove-Item -Force `$stopPath -ErrorAction SilentlyContinue
if (Test-Path `$pidPath) {
  `$oldPid = [int](Get-Content -Raw `$pidPath)
  if (Get-Process -Id `$oldPid -ErrorAction SilentlyContinue) {
    Write-Host "pyvpn client is already running with PID `$oldPid"
    exit 0
  }
  Remove-Item -Force `$pidPath
}
`$otherClients = @(Get-Process -Name "pyvpn-client" -ErrorAction SilentlyContinue)
if (`$otherClients.Count -gt 0) {
  throw "Another pyvpn client is running. Disconnect the old version before starting this one."
}
`$quotedStartScript = '"' + `$startScript + '"'
`$startProcessParams = @{
  FilePath = `$powershellExe
  ArgumentList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", `$quotedStartScript)
  WindowStyle = "Hidden"
  RedirectStandardOutput = `$logPath
  RedirectStandardError = `$errLogPath
  PassThru = `$true
}
`$process = Start-Process @startProcessParams
Set-Content -Encoding ASCII -Path `$pidPath -Value ([string]`$process.Id)
Start-Sleep -Seconds 2
if (-not (Get-Process -Id `$process.Id -ErrorAction SilentlyContinue)) {
  if (Test-Path `$logPath) { Get-Content `$logPath -Tail 80 }
  if (Test-Path `$errLogPath) { Get-Content `$errLogPath -Tail 80 }
  Remove-Item -Force `$pidPath -ErrorAction SilentlyContinue
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
`$profilesPath = $(Quote-PowerShellString $profilesPath)
if (Test-Path `$pidPath) {
  `$pidValue = [int](Get-Content -Raw `$pidPath)
  `$process = Get-Process -Id `$pidValue -ErrorAction SilentlyContinue
  if (`$process) {
    Set-Content -Encoding ASCII -Path `$stopPath -Value "stop"
    Start-Sleep -Seconds 5
    `$process = Get-Process -Id `$pidValue -ErrorAction SilentlyContinue
    if (`$process) { Stop-Process -Id `$pidValue -Force -ErrorAction SilentlyContinue }
  }
}
Remove-Item -Force `$pidPath, `$stopPath -ErrorAction SilentlyContinue
if (Test-Path `$profilesPath) {
  try {
    `$store = Get-Content -Raw `$profilesPath | ConvertFrom-Json
    `$profiles = @(`$store.servers.PSObject.Properties | ForEach-Object { `$_.Value })
  } catch {
    `$profiles = @()
  }
  foreach (`$tunName in @(`$profiles | ForEach-Object { `$_.tun_name } | Where-Object { `$_ } | Sort-Object -Unique)) {
    `$tun = Get-NetAdapter -Name `$tunName -ErrorAction SilentlyContinue
    if (`$tun) {
      foreach (`$prefix in @('0.0.0.0/1', '128.0.0.0/1')) {
        `$routeQuery = @{
          AddressFamily = "IPv4"
          DestinationPrefix = `$prefix
          InterfaceIndex = `$tun.ifIndex
          ErrorAction = "SilentlyContinue"
        }
        foreach (`$route in @(Get-NetRoute @routeQuery)) {
          `$route | Remove-NetRoute -Confirm:`$false -ErrorAction SilentlyContinue
        }
      }
      Set-DnsClientServerAddress -InterfaceAlias `$tunName -ResetServerAddresses -ErrorAction SilentlyContinue
    }
  }
  foreach (`$profile in `$profiles) {
    try {
      `$serverIps = @()
      foreach (`$address in [System.Net.Dns]::GetHostAddresses([string]`$profile.server_host)) {
        if (`$address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
          `$serverIps += `$address.ToString()
        }
      }
    } catch { `$serverIps = @() }
    foreach (`$ip in @(`$serverIps + @(`$profile.bypass_ips) | Where-Object { `$_ } | Sort-Object -Unique)) {
      `$routeQuery = @{
        AddressFamily = "IPv4"
        DestinationPrefix = "`$ip/32"
        ErrorAction = "SilentlyContinue"
      }
      foreach (`$route in @(Get-NetRoute @routeQuery)) {
        `$route | Remove-NetRoute -Confirm:`$false -ErrorAction SilentlyContinue
      }
    }
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
`$runtimeExe = $(Quote-PowerShellString $runtimeExe)
`$profilesPath = $(Quote-PowerShellString $profilesPath)
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
& `$runtimeExe servers --file `$profilesPath show
Write-Host "Log: `$logPath"
if (Test-Path `$logPath) { Get-Content `$logPath -Tail 40 }
Write-Host "Error log: `$errLogPath"
if (Test-Path `$errLogPath) { Get-Content `$errLogPath -Tail 40 }
"@ | Set-Content -Encoding UTF8 -Path $statusScript

@"
`$ErrorActionPreference = "Stop"
. $(Quote-PowerShellString $tokenInputScript)
`$runtimeExe = $(Quote-PowerShellString $runtimeExe)
`$profilesPath = $(Quote-PowerShellString $profilesPath)
`$serverArgs = @(`$args)
`$needsToken = `$serverArgs.Count -gt 0 -and
  `$serverArgs[0] -in @("add", "set-token") -and
  `$serverArgs -notcontains "--token" -and
  [string]::IsNullOrWhiteSpace(`$env:PYVPN_TOKEN)
`$oldToken = `$env:PYVPN_TOKEN
`$injectedToken = `$false
try {
  if (`$needsToken) {
    `$env:PYVPN_TOKEN = Read-PyVpnSecretToken
    `$injectedToken = `$true
  }
  & `$runtimeExe servers --file `$profilesPath @serverArgs
  `$exitCode = `$LASTEXITCODE
} finally {
  if (`$injectedToken) {
    if (`$null -eq `$oldToken) {
      Remove-Item Env:PYVPN_TOKEN -ErrorAction SilentlyContinue
    } else {
      `$env:PYVPN_TOKEN = `$oldToken
    }
  }
}
exit `$exitCode
"@ | Set-Content -Encoding UTF8 -Path $serversScript

@"
param([Parameter(Mandatory = `$true, Position = 0)][string]`$ServerId)
`$ErrorActionPreference = "Stop"
& $(Quote-PowerShellString $runtimeExe) servers --file $(Quote-PowerShellString $profilesPath) show `$ServerId | Out-Null
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
& $(Quote-PowerShellString $downScript) | Out-Host
& $(Quote-PowerShellString $runtimeExe) servers --file $(Quote-PowerShellString $profilesPath) use `$ServerId
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
& $(Quote-PowerShellString $upScript)
exit `$LASTEXITCODE
"@ | Set-Content -Encoding UTF8 -Path $switchScript

    Protect-LocalInstall $InstallDir
    if ($wasRunning) {
        Invoke-ClientHelper $upScript
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
    if ($wasRunning -and (Test-Path -LiteralPath $upScript -PathType Leaf)) {
        try { Invoke-ClientHelper $upScript } catch {
            Write-Warning "The previous local client was restored but could not be restarted."
        }
    }
    throw $failure
} finally {
    Remove-Item -Recurse -Force -LiteralPath $backupDir -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "pyvpn offline Windows client $($metadata.VERSION) installed."
Write-Host "Install directory: $InstallDir"
Write-Host "Server profiles: $profilesPath"
Write-Host "Older system-wide installations were left unchanged."
Write-Host ""
Write-Host "Connect:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$upScript`""
Write-Host "Disconnect:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$downScript`""
Write-Host "Servers and latency:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$serversScript`" list"
Write-Host "Switch server:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$switchScript`" <server_id>"
Write-Host "Status:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$statusScript`""
