# pyvpn

`pyvpn` is a v1 layer-3 VPN implementation for a single self-owned client.
The Linux server creates a TUN interface, NATs the client subnet to the public
interface, and forwards encrypted UDP tunnel packets. The Linux client creates a
TUN interface, installs a server bypass route, moves the IPv4 default route and
DNS to the tunnel, and restores the machine on exit.

The Windows and macOS paths are intentionally explicit:

- Windows needs a Wintun binding before the Python client can create a system
  TUN adapter.
- macOS system-wide VPN needs a signed NetworkExtension packet tunnel. A Swift
  skeleton is included under `macos/` and uses the same protocol contract.

## One-command Linux deployment

For the simple VPS flow, clone the repo on the server and install a systemd
service:

```bash
git clone <your-repo-url> pyvpn
cd pyvpn
sudo scripts/linux/install-server.sh --public-host <vps-public-ip-or-domain>
```

The server continues running after SSH disconnects. Use:

```bash
sudo systemctl status pyvpn-server
sudo journalctl -u pyvpn-server -f
```

On a Linux client:

```bash
git clone <your-repo-url> pyvpn
cd pyvpn
sudo scripts/linux/install-client.sh \
  --server-host <vps-public-ip-or-domain> \
  --token '<token-from-server-installer>' \
  --cert-fingerprint 'sha256:<fingerprint-from-server-installer>'
sudo pyvpn-client-start
```

When installing over SSH, the client installer preserves the current SSH source
IP outside the VPN so the management connection can still return through the
normal gateway.
The Linux client also installs a temporary policy route for the VPS public
source IP, so inbound SSH replies keep using the original gateway while the
machine's ordinary outbound traffic goes through the VPN.

For the first remote test, prefer `sudo timeout 60 pyvpn-client-start` so routes
are restored automatically after one minute.

See `docs/deployment.md` for the full deployment flow.

## Development install

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

On Linux:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev,linux]"
```

## Generate a server certificate

```bash
pyvpn-cert --cert server.crt --key server.key --common-name pyvpn.local
```

Save the printed SHA-256 fingerprint. The client pins this value.

## Run the server on a Linux VPS

Open both ports in the VPS firewall first: TCP `8443` and UDP `8444`.

```bash
sudo PYVPN_TOKEN='replace-with-a-long-random-token' pyvpn-server \
  --cert server.crt \
  --key server.key \
  --public-host vpn.example.com
```

The server creates `pyvpn0`, enables IPv4 forwarding, and installs NAT through
`nftables` when available, otherwise `iptables`.

## Run a Linux client

```bash
sudo PYVPN_TOKEN='replace-with-a-long-random-token' pyvpn-client \
  --server-host vpn.example.com \
  --cert-fingerprint 'sha256:<fingerprint-from-pyvpn-cert>'
```

The client configures `pyvpn0`, protects the server IP with a host route, changes
the IPv4 default route to the tunnel, sets DNS to `1.1.1.1`, and restores these
settings on shutdown.

## Important v1 limits

- Single active client only.
- IPv4 forwarding only. Block IPv6 separately on the client firewall if the host
  has native IPv6 connectivity and leak prevention matters.
- Windows and macOS are not fully runnable from Python alone yet because they
  require Wintun and NetworkExtension integration.
- This is suitable for self-owned infrastructure testing, not a commercial VPN
  service.
