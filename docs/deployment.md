# Deployment

## Linux server: clone and run as a background service

On the VPS, run the installer and server management commands with `sudo` or as
root. Root access is required to create the TUN device, install NAT rules, and
manage the systemd service:

Open TCP `8443` and UDP `8444` on the VPS firewall and cloud security group.
Use the block that matches your Linux firewall:

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

```bash
git clone <your-repo-url> pyvpn
cd pyvpn
sudo scripts/linux/install-server.sh --public-host <vps-public-ip-or-domain>
```

The installer:

- creates `/opt/pyvpn/venv`;
- installs the current checkout into that virtualenv;
- generates `/etc/pyvpn/server.crt` and `/etc/pyvpn/server.key`;
- generates a shared token when `--token` is not supplied;
- writes `/etc/pyvpn/server.env`;
- creates and starts `pyvpn-server.service`.

The server keeps running after SSH disconnects because it is managed by systemd.
The shared token allows 3 simultaneous clients by default. Set a different
limit from 1 to 10 with `--max-clients`, for example:

```bash
sudo scripts/linux/install-server.sh \
  --public-host <vps-public-ip-or-domain> \
  --max-clients 5
```

Useful commands:

```bash
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
sudo systemctl stop pyvpn-server
```

## Linux client: install once, run in the background

On the Linux client machine, run the installer and `pyvpn-client-*` commands
with `sudo` or as root. Root access is required to create the TUN device, change
routes, and update DNS while connected:

```bash
git clone <your-repo-url> pyvpn
cd pyvpn
sudo scripts/linux/install-client.sh \
  --server-host <vps-public-ip-or-domain> \
  --token '<token-from-server-installer>' \
  --cert-fingerprint 'sha256:<fingerprint-from-server-installer>'
```

Connect in the background:

```bash
sudo pyvpn-client-up
```

Disconnect:

```bash
sudo pyvpn-client-down
```

Status:

```bash
sudo pyvpn-client-status
```

When testing on a remote VPS over SSH, the client installer records the current
SSH source IP and keeps that IP outside the VPN. You can add more protected
management IPs with repeated `--bypass-ip <ip>` arguments.
The client also adds a temporary policy route for the VPS public source IP, so
new inbound SSH connections can still return through the original gateway.

If the Linux client fails, check logs:

```bash
sudo journalctl -u pyvpn-client -n 80 --no-pager
```

## Windows and macOS clients

The protocol code is shared, but platform packaging differs:

- Windows: use the Wintun-based client path in `docs/windows-client.md`.
- macOS: use the experimental sudo-based `utun` CLI path in
  `docs/macos-client.md` for direct testing. For production packaging, build the
  `macos/` NetworkExtension target in Xcode and connect its packet flow to the
  shared pyvpn protocol.

Linux remains the most tested path. Windows and macOS CLI support are
experimental, so use the troubleshooting commands in their client docs if
traffic does not pass after connecting.
