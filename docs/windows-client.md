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

If the prompt is already inside a `pyvpn` checkout, do not run `git clone`
again. Pull the latest code in that directory instead.

```powershell
if (Test-Path .\scripts\windows\install-client.ps1) {
  git pull
} else {
  git clone https://github.com/penghanli/pyvpn.git
  cd pyvpn
}

git log -1 --oneline

powershell -ExecutionPolicy Bypass -File scripts\windows\install-client.ps1 `
  -ServerHost <server-host> `
  -Token '<token-from-server>' `
  -CertFingerprint 'sha256:<server-fingerprint>'
```

The installer prints the exact helper script paths. New installs default to
`C:\Program Files\pyvpn-client`; older or explicitly overridden installs may use
`C:\Program Files (x86)\pyvpn-client`. Reinstalling with the current installer
also updates helper scripts in the alternate Program Files path so old commands
continue to forward to the current install. The simplest commands use the fixed
launchers under `C:\ProgramData\pyvpn`.

Helper scripts:

```text
pyvpn-client-start.ps1
pyvpn-client-up.ps1
pyvpn-client-down.ps1
pyvpn-client-status.ps1
```

## Connect

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-up.ps1"
```

Disconnect:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-down.ps1"
```

Status:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-status.ps1"
```

Foreground debug mode:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-start.ps1"
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

If Windows reports `WinError 193` or says `wintun.dll` does not match the Python
architecture, pull the latest code and rerun `scripts\windows\install-client.ps1`.
The installer will replace the wrong-architecture Wintun DLL.
