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
sudo systemctl status pyvpn-server
sudo journalctl -u pyvpn-server -f
sudo systemctl restart pyvpn-server
sudo systemctl stop pyvpn-server
```

Open the VPS firewall for TCP `8443` and UDP `8444`.

## Linux client: install once, run from CLI

On the Linux client machine:

```bash
git clone <your-repo-url> pyvpn
cd pyvpn
sudo scripts/linux/install-client.sh \
  --server-host <vps-public-ip-or-domain> \
  --token '<token-from-server-installer>' \
  --cert-fingerprint 'sha256:<fingerprint-from-server-installer>'
```

Connect:

```bash
sudo pyvpn-client-start
```

Disconnect with `Ctrl-C`. The client restores routes and DNS in its shutdown
handler.

When testing on a remote VPS over SSH, the client installer records the current
SSH source IP and keeps that IP outside the VPN. You can add more protected
management IPs with repeated `--bypass-ip <ip>` arguments.

## Windows and macOS clients

The protocol code is shared, but system-wide VPN support still needs platform
wrapping:

- Windows: add a Wintun adapter binding, then package a Windows client wrapper.
- macOS: build the `macos/` NetworkExtension target in Xcode and connect its
  packet flow to the shared pyvpn protocol.

Until those wrappers are implemented, Linux is the only one-command runnable
server/client path.
