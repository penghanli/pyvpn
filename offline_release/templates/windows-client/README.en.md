# pyvpn Windows x64 Offline Client

For Windows 10/11 x64. Python, pyvpn, all Python dependencies, and official
Wintun are included. Installation does not access GitHub or PyPI.

## Install

1. Extract the complete archive.
2. Open Windows PowerShell with Run as administrator.
3. Enter the directory containing `install-client.ps1` and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-client.ps1
```

The installer checks administrator access, Windows and CPU architecture,
package integrity, Wintun, and disk space before creating `pyvpn-client` under
the extracted package directory. Runtime files, logs, and server profiles stay
inside that directory. Older system-wide installations are not read, stopped,
or overwritten.

The first install asks for the server, shared token, and certificate
fingerprint. The initial `server_id` is `default`, and token input is hidden.

## Connect

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-up.ps1"
```

Disconnect and status:

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-down.ps1"
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-status.ps1"
```

## Servers

Add a server. Token input is hidden when `--token` is omitted:

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" add aliyun-sg --server-host <server-host> --cert-fingerprint "sha256:<server-fingerprint>"
```

Append `--replace` to that command when the address, token, or fingerprint for
the same `server_id` changes. Show the active server details:

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" show
```

List servers with TCP control-port latency:

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" list
```

Select a server for the next connection:

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" use aliyun-sg
```

Disconnect, select, and reconnect immediately:

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-switch.ps1" aliyun-sg
```

Profiles are stored in `pyvpn-client\config\servers.json`; tokens are masked in
normal output. Run installation and client commands as administrator. Do not
move or delete the installed `pyvpn-client` directory.
