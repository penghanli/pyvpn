# pyvpn Linux Offline Server

This package includes Python, pyvpn, and all Python dependencies. Installation
does not contact GitHub, PyPI, or a Linux package repository.

## Requirements

- glibc 2.28+ and systemd.
- Use the `x86_64` or `arm64` archive matching the server.
- The system must provide `ip`, `sha256sum`, and either `nft` or `iptables`.
- `/dev/net/tun` must be available. Install as root or with `sudo`.
- Allow inbound TCP `8443` and UDP `8444` in the cloud and host firewalls.

On a server using `iptables`, run:

```bash
sudo iptables -I INPUT -p tcp --dport 8443 -j ACCEPT
sudo iptables -I INPUT -p udp --dport 8444 -j ACCEPT
```

On a server using UFW, run:

```bash
sudo ufw allow 8443/tcp
sudo ufw allow 8444/udp
```

Cloud servers must also allow the same two ports in the provider security
group.

## Install

Extract the archive, enter its directory, and run:

```bash
sudo ./install-server.sh
```

A new installation prompts for the public IP or DNS name. Leave the shared
token empty to generate one. The installer prints all client settings when it
finishes.

For unattended installation:

```bash
sudo ./install-server.sh --public-host <server-ip-or-domain> --max-clients 5
```

Upgrades retain `/etc/pyvpn/server.env`, the shared token, certificate, and
private key.

## Management

```bash
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
```

`pyvpn-server-status` prints token IDs for both `server.env` and the running
process. They must match, and the client `show` token ID must match them too.

The complete package, architecture, TUN device, and NAT tools are verified
before system files are changed.
