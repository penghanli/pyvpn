# Windows Client

The Windows client uses Wintun as the system TUN adapter. Run everything from an
elevated PowerShell window.

## Before Install

Allow the client to reach the VPN server:

```text
Outbound TCP 8443 to <server-ip-or-domain>
Outbound UDP 8444 to <server-ip-or-domain>
```

If Windows Defender Firewall is locked down with restrictive outbound rules,
add explicit outbound allow rules. Use the server IPv4 address for
`<server-ip>`:

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

Install Git for Windows and Python 3.9+ first, then confirm both are available:

```powershell
git --version
py -3 --version
```

The installer creates the virtual environment, installs the Python package
dependencies, downloads the official Wintun ZIP, verifies its SHA-256, and
copies the matching `wintun.dll`.

Check the TCP control port before installing:

```powershell
Test-NetConnection <server-host> -Port 8443
```

This checks TCP `8443` only. If the client authenticates but tunnel traffic does
not pass, check UDP `8444` on the VPS firewall/cloud security group and any
Windows outbound firewall or security product.

## Install

```powershell
git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

powershell -ExecutionPolicy Bypass -File scripts\windows\install-client.ps1 `
  -ServerHost 51.79.147.199 `
  -Token '<token-from-server>' `
  -CertFingerprint 'sha256:<server-fingerprint>'
```

The installer downloads the official Wintun 0.14.1 ZIP, verifies its SHA-256,
copies the matching `wintun.dll` into the virtualenv, and creates:

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

The down script requests graceful shutdown first so the client can notify the
server and restore routes. If the process does not exit after a few seconds, it
falls back to force stop and route cleanup.

Status and logs:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Program Files\pyvpn-client\pyvpn-client-status.ps1"
Get-Content "C:\ProgramData\pyvpn\client.log" -Tail 80
Get-Content "C:\ProgramData\pyvpn\client.err.log" -Tail 80
```

Foreground debug mode:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Program Files\pyvpn-client\pyvpn-client-start.ps1"
```

In foreground mode, disconnect with `Ctrl-C`.

## Verify

```powershell
curl.exe -4 https://ifconfig.me
route print -4
Get-NetRoute -DestinationPrefix 0.0.0.0/1,128.0.0.0/1
```

The IPv4 curl result should be the server public IP.
