# Deployment

## Linux server: clone and run as a background service

On the VPS:

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

Useful commands:

```bash
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
sudo systemctl stop pyvpn-server
```

`pyvpn-server-restart` prints a success message and the current systemd status
after the restart completes.

Open the VPS firewall for TCP `8443` and UDP `8444`.

## Linux client: install once, run in the background

On the Linux client machine:

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

Check status and logs:

```bash
sudo pyvpn-client-status
sudo journalctl -u pyvpn-client -f
```

For foreground debugging, use `sudo pyvpn-client-start` and disconnect with
`Ctrl-C`.

When testing on a remote VPS over SSH, the client installer records the current
SSH source IP and keeps that IP outside the VPN. You can add more protected
management IPs with repeated `--bypass-ip <ip>` arguments.
The client also adds a temporary policy route for the VPS public source IP, so
new inbound SSH connections can still return through the original gateway.

For remote foreground tests, run the client with a timeout first so a bad route
cannot keep the VPS unreachable:

```bash
sudo timeout 60 pyvpn-client-start
```

## Windows and macOS clients

The protocol code is shared, but platform packaging differs:

- Windows: use the Wintun-based client path in `docs/windows-client.md`.
- macOS: build the `macos/` NetworkExtension target in Xcode and connect its
  packet flow to the shared pyvpn protocol.

Linux remains the most tested path. Windows is experimental and should be
verified with IPv4-only tests first.
