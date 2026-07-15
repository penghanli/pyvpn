# pyvpn

`pyvpn` is a v1 layer-3 VPN for a small self-owned client set.

The Linux server creates a TUN interface, NATs the client subnet to the public
interface, and forwards encrypted UDP tunnel packets. Clients create a system
TUN adapter, install a bypass route for the server IP, move IPv4 traffic and DNS
to the tunnel, and restore local networking when disconnected.

## Current Scope

- Server: Linux VPS only.
- Clients: Linux, Windows, and experimental macOS CLI.
- Tunnel: IPv4 over encrypted UDP.
- Control channel: TLS with token authentication and certificate fingerprint
  pinning.
- Default ports: TCP `8443` for control, UDP `8444` for tunnel data.

## Requirements

Ports:

```text
Server inbound: TCP 8443, UDP 8444
Client outbound: TCP 8443, UDP 8444 to the server
```

Linux server and Linux clients must run install/connect commands with `sudo` or
as root. Windows clients must run from PowerShell opened with
`Run as administrator`.

Linux dependencies:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git iproute2 nftables python3 python3-pip python3-venv
```

Windows dependencies:

- Git for Windows
- Python 3.9+ through the `py` launcher or `PATH`
- outbound access to PyPI and `www.wintun.net`

The Windows installer handles the virtualenv, Python package dependencies, and
Wintun download.

## Server Setup

### Linux VPS

Open TCP `8443` and UDP `8444` on the VPS firewall and cloud security group.
Use the command block that matches your Linux firewall:

```bash
# UFW
sudo ufw allow 8443/tcp
sudo ufw allow 8444/udp
sudo ufw reload
```

```bash
# firewalld
sudo firewall-cmd --permanent --add-port=8443/tcp
sudo firewall-cmd --permanent --add-port=8444/udp
sudo firewall-cmd --reload
```

Install the server:

```bash
git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

sudo scripts/linux/install-server.sh \
  --public-host <vps-public-ip-or-domain> \
  --max-clients 3
```

The installer creates a `systemd` service and prints the values needed by every
client:

```text
Client settings:
  server host: <vps-public-ip-or-domain>
  control port: 8443
  max clients: 3
  token: <shared-token>
  cert fingerprint: sha256:<server-fingerprint>
```

Server commands:

```bash
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
sudo systemctl stop pyvpn-server
```

## Client Setup

Use the `server host`, `token`, and `cert fingerprint` printed by the server
installer. If a checkout already exists, run `git pull` inside it instead of
cloning again.

### Linux Client

Run these commands with `sudo` where shown:

```bash
sudo apt update
sudo apt install -y ca-certificates git iproute2 python3 python3-pip python3-venv

git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

sudo scripts/linux/install-client.sh \
  --server-host <server-host> \
  --token '<shared-token>' \
  --cert-fingerprint 'sha256:<server-fingerprint>'
```

Connect and disconnect:

```bash
sudo pyvpn-client-up
sudo pyvpn-client-down
sudo pyvpn-client-status
```

When installing over SSH, the Linux installer preserves the current SSH source
IP outside the VPN so the management connection can still return through the
normal gateway. The client service is installed but not enabled at boot by
default.

### Windows Client

Open PowerShell with `Run as administrator`.

If outbound firewall rules are restricted, allow the client to reach the server:

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

Install the client:

```powershell
if (Test-Path .\scripts\windows\install-client.ps1) {
  git pull
} else {
  git clone https://github.com/penghanli/pyvpn.git
  cd pyvpn
}

git log -1 --oneline

powershell -ExecutionPolicy Bypass -File .\scripts\windows\install-client.ps1 `
  -ServerHost <server-host> `
  -Token '<shared-token>' `
  -CertFingerprint 'sha256:<server-fingerprint>'
```

The installer downloads and verifies Wintun, creates a virtual environment, and
prints the exact helper script paths. New installs default to
`C:\Program Files\pyvpn-client`; older or explicitly overridden installs may use
`C:\Program Files (x86)\pyvpn-client`. Reinstalling with the current installer
also updates helper scripts in the alternate Program Files path so old commands
continue to forward to the current install. The simplest commands use the fixed
launchers under `C:\ProgramData\pyvpn`.

Connect and disconnect:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-up.ps1"
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-down.ps1"
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-status.ps1"
```

### macOS Client

The macOS CLI client is experimental. It uses the native `utun` kernel control
from Python and must run with `sudo`. A production macOS app should use the
signed NetworkExtension path under `macos/`.

```bash
brew install python

git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

sudo scripts/macos/install-client.sh \
  --server-host <server-host> \
  --token '<shared-token>' \
  --cert-fingerprint 'sha256:<server-fingerprint>' \
  --tun auto
```

Connect and disconnect:

```bash
sudo pyvpn-client-up
sudo pyvpn-client-down
sudo pyvpn-client-status
```

## If Something Does Not Work

Run these checks only when installation or traffic fails.

Server:

```bash
sudo ss -lntup | grep -E '8443|8444'
sudo pyvpn-server-status
sudo pyvpn-server-logs
```

Linux client:

```bash
ls -l /dev/net/tun || sudo modprobe tun
journalctl -u pyvpn-client -n 80 --no-pager
curl -4 https://ifconfig.me
```

Windows client:

```powershell
Test-NetConnection <server-host> -Port 8443
Get-Content "C:\ProgramData\pyvpn\client.log" -Tail 80
Get-Content "C:\ProgramData\pyvpn\client.err.log" -Tail 80
curl.exe -4 https://ifconfig.me
```

If TCP `8443` works but the client connects without passing traffic, check UDP
`8444` on the VPS firewall/cloud security group and the client outbound
firewall.

If Windows reports `WinError 193` or says `wintun.dll` does not match the Python
architecture, pull the latest code and rerun `scripts\windows\install-client.ps1`.
The installer will replace the wrong-architecture Wintun DLL.

## Development Install

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Linux:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev,linux]"
```

## Manual Server Command

The installer is the recommended server path. For manual testing, generate a
certificate and run the server directly:

```bash
pyvpn-cert --cert server.crt --key server.key --common-name pyvpn.local
```

Save the printed SHA-256 fingerprint, then run:

```bash
sudo PYVPN_TOKEN='replace-with-a-long-random-token' pyvpn-server \
  --cert server.crt \
  --key server.key \
  --public-host vpn.example.com \
  --max-clients 3
```

## Important v1 Limits

- One shared token supports up to `--max-clients` simultaneous clients, from 1
  to 10. The default is 3.
- IPv4 forwarding only. Block IPv6 separately on the client firewall if leak
  prevention matters.
- Windows client support is experimental and depends on Wintun.
- macOS CLI support is experimental and uses `utun` with `sudo`.
- The Python data plane is suitable for self-owned infrastructure testing, not
  a high-performance commercial VPN service.
