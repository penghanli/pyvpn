# Windows Client

The Windows client uses Wintun as the system TUN adapter. Open PowerShell with
`Run as administrator`; Wintun adapter, route, and DNS changes require
administrator access.

## Before Install

Install:

- Git for Windows
- Python 3.9+ through the `py` launcher or `PATH`

If outbound firewall rules are restricted, allow the client to reach the VPN
server:

```powershell
New-NetFirewallRule `
  -DisplayName "pyvpn control TCP 8443 out" `
  -Direction Outbound `
  -Action Allow `
  -Protocol TCP `
  -RemoteAddress <server-ip> `
  -RemotePort 8443

New-NetFirewallRule `
  -DisplayName "pyvpn tunnel UDP 8444 out" `
  -Direction Outbound `
  -Action Allow `
  -Protocol UDP `
  -RemoteAddress <server-ip> `
  -RemotePort 8444
```

The installer creates the virtual environment, installs the Python package
dependencies, downloads the official Wintun ZIP, verifies its SHA-256, and
copies the matching `wintun.dll`.

## Install

```powershell
git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

powershell -ExecutionPolicy Bypass -File scripts\windows\install-client.ps1 `
  -ServerHost <server-host> `
  -Token '<token-from-server>' `
  -CertFingerprint 'sha256:<server-fingerprint>'
```

The installer creates:

```text
C:\Program Files\pyvpn-client\pyvpn-client-start.ps1
C:\Program Files\pyvpn-client\pyvpn-client-up.ps1
C:\Program Files\pyvpn-client\pyvpn-client-down.ps1
C:\Program Files\pyvpn-client\pyvpn-client-status.ps1
```

## Connect

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Program Files\pyvpn-client\pyvpn-client-up.ps1"
```

Disconnect:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Program Files\pyvpn-client\pyvpn-client-down.ps1"
```

Status:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Program Files\pyvpn-client\pyvpn-client-status.ps1"
```

Foreground debug mode:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Program Files\pyvpn-client\pyvpn-client-start.ps1"
```

In foreground mode, disconnect with `Ctrl-C`.

## If Something Does Not Work

Run these checks only when installation or traffic fails:

```powershell
Test-NetConnection <server-host> -Port 8443
Get-Content "C:\ProgramData\pyvpn\client.log" -Tail 80
Get-Content "C:\ProgramData\pyvpn\client.err.log" -Tail 80
curl.exe -4 https://ifconfig.me
```

`Test-NetConnection` checks TCP `8443` only. If the client authenticates but
tunnel traffic does not pass, check UDP `8444` on the VPS firewall/cloud
security group and any Windows outbound firewall or security product.
