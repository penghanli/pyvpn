# pyvpn Linux Offline Client

This package includes Python, pyvpn, and all Python dependencies. Installation
does not contact GitHub, PyPI, or a Linux package repository.

## Requirements

- glibc 2.28+ and systemd.
- Use the `x86_64` or `arm64` archive matching the machine.
- The system must already provide `ip`, `sha256sum`, and `/dev/net/tun`.
- Install, connect, and disconnect as root or with `sudo`.
- The client must reach server TCP `8443` and UDP `8444`.

## Install

Extract the archive, enter its directory, and run:

```bash
sudo ./install-client.sh
```

A new installation prompts for the server host, shared token, and certificate
fingerprint. Token input is hidden. Upgrades reuse `/etc/pyvpn/client.env`.

For unattended installation:

```bash
sudo ./install-client.sh \
  --server-host <server-host> \
  --token '<shared-token>' \
  --cert-fingerprint 'sha256:<server-fingerprint>'
```

## Connect

```bash
sudo pyvpn-client-up
```

Disconnect and inspect status:

```bash
sudo pyvpn-client-down
sudo pyvpn-client-status
```

The installer verifies the complete archive before changing an existing
installation.
