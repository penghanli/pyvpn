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
```

## Connect

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Program Files\pyvpn-client\pyvpn-client-start.ps1"
```

Disconnect with `Ctrl-C`. The client removes the split default routes and resets
the Wintun DNS settings during shutdown.

## Verify

```powershell
curl.exe -4 https://ifconfig.me
route print -4
Get-NetRoute -DestinationPrefix 0.0.0.0/1,128.0.0.0/1
```

The IPv4 curl result should be the server public IP.
