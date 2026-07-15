param(
    [Parameter(Mandatory = $true)]
    [string]$ServerHost,

    [Parameter(Mandatory = $true)]
    [string]$Token,

    [Parameter(Mandatory = $true)]
    [string]$CertFingerprint,

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
        throw "Run this installer from an elevated PowerShell window."
    }
}

function Quote-PowerShellString([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Resolve-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }
    throw "Python 3.9+ is required. Install Python from python.org first."
}

function Resolve-DefaultInstallDir {
    $root = [Environment]::GetEnvironmentVariable("ProgramW6432")
    if ([string]::IsNullOrWhiteSpace($root)) {
        $root = [Environment]::GetEnvironmentVariable("ProgramFiles")
    }
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "Could not determine Program Files directory. Pass -InstallDir explicitly."
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

function Get-PythonWintunArch([string]$PythonExe) {
    $archScript = "import platform,struct; m=(platform.machine() or '').lower(); b=struct.calcsize('P')*8; print('arm64' if b==64 and m in ('arm64','aarch64') else 'arm' if b==32 and m.startswith('arm') else 'amd64' if b==64 else 'x86' if b==32 else 'unsupported')"
    $output = & $PythonExe -c $archScript 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not determine Wintun architecture from Python: $output"
    }
    $arch = (($output | Select-Object -Last 1).ToString()).Trim()
    switch ($arch) {
        "amd64" { return "amd64" }
        "x86" { return "x86" }
        "arm64" { return "arm64" }
        "arm" { return "arm" }
        default { throw "Unsupported Python Wintun architecture: $arch" }
    }
}

function Write-ForwardingScript([string]$Path, [string]$TargetScript) {
@"
`$ErrorActionPreference = "Stop"
& $(Quote-PowerShellString $TargetScript) @args
exit `$LASTEXITCODE
"@ | Set-Content -Encoding UTF8 -Path $Path
}

Assert-Admin

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Resolve-DefaultInstallDir
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
if (-not (Test-Path (Join-Path $repoRoot "pyproject.toml"))) {
    throw "Could not find pyproject.toml. Run this from a pyvpn git checkout."
}

New-Item -ItemType Directory -Force -Path $InstallDir, $ConfigDir | Out-Null
$InstallDir = (Resolve-Path $InstallDir).Path
$ConfigDir = (Resolve-Path $ConfigDir).Path

$pythonCmd = @(Resolve-Python)
$pythonExe = $pythonCmd[0]
$pythonArgs = @()
if ($pythonCmd.Count -gt 1) {
    $pythonArgs = $pythonCmd[1..($pythonCmd.Count - 1)]
}
& $pythonExe @pythonArgs -m venv (Join-Path $InstallDir "venv")
$venvPython = Join-Path $InstallDir "venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install "$repoRoot"

$wintunUrl = "https://www.wintun.net/builds/wintun-0.14.1.zip"
$wintunSha256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51"
$wintunZip = Join-Path $ConfigDir "wintun-0.14.1.zip"
$wintunExtract = Join-Path $ConfigDir "wintun"
$wintunDllTarget = Join-Path $InstallDir "venv\Scripts\wintun.dll"

if (-not (Test-Path $wintunZip)) {
    Invoke-WebRequest -Uri $wintunUrl -OutFile $wintunZip
}

$actualHash = (Get-FileHash -Path $wintunZip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $wintunSha256) {
    Remove-Item -Force $wintunZip -ErrorAction SilentlyContinue
    Invoke-WebRequest -Uri $wintunUrl -OutFile $wintunZip
    $actualHash = (Get-FileHash -Path $wintunZip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $wintunSha256) {
        throw "Wintun SHA-256 mismatch. Expected $wintunSha256, got $actualHash"
    }
}

if (Test-Path $wintunExtract) {
    Remove-Item -Recurse -Force $wintunExtract
}
Expand-Archive -Path $wintunZip -DestinationPath $wintunExtract -Force

$arch = Get-PythonWintunArch $venvPython
$candidate = Get-ChildItem -Path $wintunExtract -Recurse -Filter wintun.dll |
    Where-Object { $_.FullName -match "\\bin\\$arch\\wintun\.dll$" } |
    Select-Object -First 1
if (-not $candidate) {
    throw "Could not find Wintun DLL for Python architecture '$arch' in $wintunZip"
}
Copy-Item -Force $candidate.FullName $wintunDllTarget

$envPath = Join-Path $ConfigDir "client.env.ps1"
$pidPath = Join-Path $ConfigDir "client.pid"
$logPath = Join-Path $ConfigDir "client.log"
$errLogPath = Join-Path $ConfigDir "client.err.log"
$stopPath = Join-Path $ConfigDir "client.stop"
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

$startScript = Join-Path $InstallDir "pyvpn-client-start.ps1"
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
& $(Quote-PowerShellString (Join-Path $InstallDir "venv\Scripts\pyvpn-client.exe")) @argsList
"@ | Set-Content -Encoding UTF8 -Path $startScript

$upScript = Join-Path $InstallDir "pyvpn-client-up.ps1"
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
`$started = Get-Process -Id `$process.Id -ErrorAction SilentlyContinue
if (-not `$started) {
  if (Test-Path `$logPath) { Get-Content `$logPath -Tail 80 }
  if (Test-Path `$errLogPath) { Get-Content `$errLogPath -Tail 80 }
  throw "pyvpn client failed to start"
}
Write-Host "pyvpn client started in the background with PID `$(`$process.Id)"
Write-Host "Log: `$logPath"
Write-Host "Error log: `$errLogPath"
"@ | Set-Content -Encoding UTF8 -Path $upScript

$downScript = Join-Path $InstallDir "pyvpn-client-down.ps1"
@"
`$ErrorActionPreference = "Continue"
`$pidPath = $(Quote-PowerShellString $pidPath)
`$logPath = $(Quote-PowerShellString $logPath)
`$errLogPath = $(Quote-PowerShellString $errLogPath)
`$stopPath = $(Quote-PowerShellString $stopPath)
`$envPath = $(Quote-PowerShellString $envPath)
if (Test-Path `$envPath) { . `$envPath }
if (-not (Test-Path `$pidPath)) {
  Write-Host "pyvpn client is not running"
} else {
  `$pidValue = [int](Get-Content -Raw `$pidPath)
  `$process = Get-Process -Id `$pidValue -ErrorAction SilentlyContinue
  if (`$process) {
    Set-Content -Encoding ASCII -Path `$stopPath -Value "stop"
    Start-Sleep -Seconds 5
    `$process = Get-Process -Id `$pidValue -ErrorAction SilentlyContinue
    if (`$process) {
      Stop-Process -Id `$pidValue -Force -ErrorAction SilentlyContinue
    }
    Write-Host "pyvpn client stopped"
  } else {
    Write-Host "pyvpn client process was not found"
  }
  Remove-Item -Force `$pidPath -ErrorAction SilentlyContinue
  Remove-Item -Force `$stopPath -ErrorAction SilentlyContinue
}

if (`$PyVpnTun) {
  `$tun = Get-NetAdapter -Name `$PyVpnTun -ErrorAction SilentlyContinue
  if (`$tun) {
    foreach (`$prefix in @('0.0.0.0/1', '128.0.0.0/1')) {
      `$routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix `$prefix -InterfaceIndex `$tun.ifIndex -ErrorAction SilentlyContinue
      `$routes | Remove-NetRoute -Confirm:`$false -ErrorAction SilentlyContinue
    }
    Set-DnsClientServerAddress -InterfaceAlias `$PyVpnTun -ResetServerAddresses -ErrorAction SilentlyContinue
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
Write-Host "Log: `$logPath"
Write-Host "Error log: `$errLogPath"
"@ | Set-Content -Encoding UTF8 -Path $downScript

$statusScript = Join-Path $InstallDir "pyvpn-client-status.ps1"
@"
`$pidPath = $(Quote-PowerShellString $pidPath)
`$logPath = $(Quote-PowerShellString $logPath)
`$errLogPath = $(Quote-PowerShellString $errLogPath)
if (Test-Path `$pidPath) {
  `$pidValue = [int](Get-Content -Raw `$pidPath)
  `$process = Get-Process -Id `$pidValue -ErrorAction SilentlyContinue
  if (`$process) {
    Write-Host "pyvpn client is running with PID `$pidValue"
  } else {
    Write-Host "pyvpn client PID file exists, but the process is not running"
  }
} else {
  Write-Host "pyvpn client is not running"
}
Write-Host "Log: `$logPath"
if (Test-Path `$logPath) {
  Get-Content `$logPath -Tail 40
}
Write-Host "Error log: `$errLogPath"
if (Test-Path `$errLogPath) {
  Get-Content `$errLogPath -Tail 40
}
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
$installFull = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd("\")
foreach ($candidateDir in Get-StandardInstallDirs) {
    $candidateFull = [System.IO.Path]::GetFullPath($candidateDir).TrimEnd("\")
    if ($candidateFull -eq $installFull) {
        continue
    }
    New-Item -ItemType Directory -Force -Path $candidateDir | Out-Null
    foreach ($scriptName in $scriptTargets.Keys) {
        Write-ForwardingScript (Join-Path $candidateDir $scriptName) $scriptTargets[$scriptName]
    }
}

Write-Host ""
Write-Host "pyvpn Windows client installed."
Write-Host "Install directory: $InstallDir"
Write-Host "Wintun architecture: $arch"
Write-Host ""
Write-Host "Connect in the background from an elevated PowerShell window:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$ConfigDir\pyvpn-client-up.ps1`""
Write-Host ""
Write-Host "Disconnect:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$ConfigDir\pyvpn-client-down.ps1`""
Write-Host ""
Write-Host "Status:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$ConfigDir\pyvpn-client-status.ps1`""
Write-Host ""
Write-Host "Foreground debug mode:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$ConfigDir\pyvpn-client-start.ps1`""
Write-Host ""
