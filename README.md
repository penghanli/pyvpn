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

## Required Network Access and Dependencies

### Ports

`pyvpn` uses two ports:

```text
TCP 8443: TLS control channel
UDP 8444: encrypted tunnel packets
```

Open inbound TCP `8443` and UDP `8444` on the Linux VPS firewall and cloud
security group. On client systems such as Windows, allow outbound TCP `8443`
and UDP `8444` to the server. The client code opens an outbound TLS connection
and an outbound UDP socket; it does not listen for inbound VPN connections.

### Dependencies

Server and Linux clients need root access, Python 3.9+, venv support, Git,
Linux routing tools, and a usable TUN device. On Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y \
  ca-certificates \
  curl \
  git \
  iproute2 \
  nftables \
  python3 \
  python3-pip \
  python3-venv
```

Check TUN support on Linux:

```bash
ls -l /dev/net/tun || sudo modprobe tun
```

Windows clients need an elevated PowerShell window, Git for Windows, Python
3.9+ available through the `py` launcher or `PATH`, and outbound access to PyPI
and `www.wintun.net`. The Windows installer creates the virtual environment,
installs the Python package dependencies, downloads the official Wintun ZIP,
verifies its SHA-256, and copies the matching `wintun.dll`.

macOS CLI clients need Python 3.9+, `sudo`, and outbound access to PyPI unless
you use a local wheelhouse.

## Server Setup

### Linux VPS

Open both ports in the VPS firewall and cloud security group first:

```text
TCP 8443
UDP 8444
```

Then clone and install the server:

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

Server management:

```bash
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
sudo systemctl stop pyvpn-server
```

Check that the server is listening:

```bash
sudo ss -lntup | grep -E '8443|8444'
```

Expected listeners:

```text
0.0.0.0:8443/tcp
0.0.0.0:8444/udp
```

## Client Setup

Use the `server host`, `token`, and `cert fingerprint` printed by the Linux
server installer.

If a checkout already exists, run `git pull` inside it instead of cloning again.

### Linux Client

Install prerequisites on Debian/Ubuntu clients:

```bash
sudo apt update
sudo apt install -y ca-certificates git iproute2 python3 python3-pip python3-venv
ls -l /dev/net/tun || sudo modprobe tun
```

Install:

```bash
git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

sudo scripts/linux/install-client.sh \
  --server-host <server-host> \
  --token '<shared-token>' \
  --cert-fingerprint 'sha256:<server-fingerprint>'
```

Connect:

```bash
sudo pyvpn-client-up
```

Disconnect:

```bash
sudo pyvpn-client-down
```

Status and logs:

```bash
sudo pyvpn-client-status
journalctl -u pyvpn-client -n 80 --no-pager
```

Verify:

```bash
curl -4 https://ifconfig.me
ip route get 1.1.1.1
ip route
```

The IPv4 curl result should be the server public IP.

When installing over SSH, the Linux installer preserves the current SSH source
IP outside the VPN so the management connection can still return through the
normal gateway. The client service is installed but not enabled at boot by
default.

### Windows Client

Run everything from an elevated PowerShell window.

Step 1: allow the client to reach the server ports.

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

Step 2: install and verify the local tools.

```powershell
git --version
py -3 --version
```

If either command fails, install Git for Windows and Python 3.9+ first, then
open a new elevated PowerShell window.

Step 3: verify the TCP control port before installing:

```powershell
Test-NetConnection <server-host> -Port 8443
```

`Test-NetConnection` only checks TCP `8443`. If login succeeds but traffic does
not pass through the tunnel, check UDP `8444` on the VPS firewall/cloud security
group and the Windows outbound firewall/security product.

Step 4: install the client:

```powershell
git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

powershell -ExecutionPolicy Bypass -File .\scripts\windows\install-client.ps1 `
  -ServerHost <server-host> `
  -Token '<shared-token>' `
  -CertFingerprint 'sha256:<server-fingerprint>'
```

The installer downloads and verifies Wintun, creates a virtual environment, and
writes helper scripts under `C:\Program Files\pyvpn-client`.

Connect:

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

Verify:

```powershell
Test-NetConnection <server-host> -Port 8443

curl.exe -4 https://ifconfig.me
echo ""

Get-NetRoute -AddressFamily IPv4 |
  Where-Object {
    $_.DestinationPrefix -in @(
      "0.0.0.0/1",
      "128.0.0.0/1",
      "<server-ip>/32",
      "0.0.0.0/0"
    )
  } |
  Sort-Object DestinationPrefix, RouteMetric |
  Format-Table DestinationPrefix, NextHop, InterfaceAlias, RouteMetric -AutoSize

tracert -4 1.1.1.1
```

The IPv4 curl result should be the server public IP, and the first traceroute
hop should be `10.8.0.1`.

Foreground debug mode:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Program Files\pyvpn-client\pyvpn-client-start.ps1"
```

### macOS Client

The macOS CLI client is experimental. It uses the native `utun` kernel control
from Python and must run with `sudo`. A production macOS app should use the
signed NetworkExtension path under `macos/`.

Install Python 3.9+ first if `python3` is missing:

```bash
brew install python
```

Install:

```bash
git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

sudo scripts/macos/install-client.sh \
  --server-host <server-host> \
  --token '<shared-token>' \
  --cert-fingerprint 'sha256:<server-fingerprint>' \
  --tun auto
```

If PyPI is slow or blocked, use a mirror:

```bash
sudo scripts/macos/install-client.sh \
  --server-host <server-host> \
  --token '<shared-token>' \
  --cert-fingerprint 'sha256:<server-fingerprint>' \
  --pip-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  --tun auto
```

For offline or repeatable installs, build a local wheelhouse on the target Mac:

```bash
rm -rf wheelhouse
mkdir -p wheelhouse

python3 -m pip download \
  --only-binary=:all: \
  -d wheelhouse \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  'cryptography>=42.0.0'

sudo scripts/macos/install-client.sh \
  --server-host <server-host> \
  --token '<shared-token>' \
  --cert-fingerprint 'sha256:<server-fingerprint>' \
  --wheel-dir ./wheelhouse \
  --tun auto
```

Connect:

```bash
sudo pyvpn-client-up
```

Disconnect:

```bash
sudo pyvpn-client-down
```

Status and logs:

```bash
sudo pyvpn-client-status
sudo tail -f /var/log/pyvpn/client.log /var/log/pyvpn/client.err.log
```

Verify:

```bash
curl -4 https://ifconfig.me
echo

route -n get 1.1.1.1
netstat -rn -f inet | grep -E '(^default|^0/1|^128\.0/1|10\.8\.)'
```

The IPv4 curl result should be the server public IP, and `route -n get 1.1.1.1`
should show a `utun` interface.

Foreground debug mode:

```bash
sudo pyvpn-client-start
```

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
