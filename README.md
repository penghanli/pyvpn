# pyvpn

`pyvpn` is a v1 layer-3 VPN implementation for a single self-owned client.
The Linux server creates a TUN interface, NATs the client subnet to the public
interface, and forwards encrypted UDP tunnel packets. The Linux client creates a
TUN interface, installs a server bypass route, moves the IPv4 default route and
DNS to the tunnel, and restores the machine on exit.

The Windows and macOS paths are intentionally explicit:

- Windows uses Wintun. See `docs/windows-client.md` for the elevated PowerShell
  install and test flow.
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
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
```

On a Linux client:

```bash
git clone <your-repo-url> pyvpn
cd pyvpn
sudo scripts/linux/install-client.sh \
  --server-host <vps-public-ip-or-domain> \
  --token '<token-from-server-installer>' \
  --cert-fingerprint 'sha256:<fingerprint-from-server-installer>'
sudo pyvpn-client-up
```

When installing over SSH, the client installer preserves the current SSH source
IP outside the VPN so the management connection can still return through the
normal gateway.
The Linux client also installs a temporary policy route for the VPS public
source IP, so inbound SSH replies keep using the original gateway while the
machine's ordinary outbound traffic goes through the VPN.

The Linux client installer creates a systemd service but does not enable it at
boot by default. Use `sudo pyvpn-client-up` to connect in the background and
`sudo pyvpn-client-down` to disconnect. For foreground debugging, use
`sudo pyvpn-client-start`.

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
- IPv4 forwarding only. Block IPv6 separately on the client firewall if leak
  prevention matters.
- Windows client support is experimental and depends on Wintun. Use elevated
  PowerShell and verify with `curl.exe -4 https://ifconfig.me`.
- macOS is still a NetworkExtension skeleton and is not yet runnable as a full
  system VPN client.
- This is suitable for self-owned infrastructure testing, not a commercial VPN
  service.
