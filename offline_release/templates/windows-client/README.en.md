# pyvpn Windows x64 Offline Client

This package supports Windows 10/11 x64 and includes Python, pyvpn, all Python
dependencies, and the official Wintun DLL. Installation does not contact
GitHub, PyPI, or any other package repository.

## Install

1. Extract the complete archive.
2. Open Windows PowerShell with **Run as administrator**.
3. Change to the extracted directory and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-client.ps1
```

For a new installation, the script prompts for the server host, shared token,
and certificate fingerprint. Token input is hidden. An existing pyvpn
configuration is reused by default during an upgrade.

For unattended installation:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-client.ps1 -ServerHost <server-host> -Token '<shared-token>' -CertFingerprint 'sha256:<server-fingerprint>'
```

## Connect

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-up.ps1"
```

Disconnect:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-down.ps1"
```

Status and logs:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-status.ps1"
```

## Requirements

- Run installation, connect, and disconnect commands as administrator.
- The client must reach server TCP `8443` and UDP `8444`.
- Package checksums are verified before system files are changed.

Upgrades retain the configuration under `C:\ProgramData\pyvpn` and keep the
previous runtime available for automatic recovery if installation fails.
