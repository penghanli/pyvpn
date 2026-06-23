# Windows Client

The Windows client uses Wintun as the system TUN adapter. Run everything from an
elevated PowerShell window.

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
