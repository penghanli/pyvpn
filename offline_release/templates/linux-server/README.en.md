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

If UFW is active and blocks forwarding, also allow the VPN subnet to leave
through the default interface after installation. Replace the interface and
subnet if your configuration differs from the defaults:

```bash
WAN_IF=$(ip -4 route show default | awk '/default/ {for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')
sudo ufw route allow in on pyvpn0 out on "$WAN_IF" from 10.8.0.0/24
```

Do not run `ufw enable` or `ufw reset` just for pyvpn; that can disrupt SSH.

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
sudo ./install-server.sh --public-host <server-ip-or-domain> --max-clients 10
```

Upgrades retain `/etc/pyvpn/server.env`, the shared token, certificate, private
key, and existing client limit. Pass `--max-clients 10` explicitly to raise an
older installation's limit to ten. Existing connections are briefly interrupted
during the restart.

## Management

```bash
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
```

`pyvpn-server-status` prints token IDs for both `server.env` and the running
process. They must match, and the client `show` token ID must match them too.
If control connects but data does not flow, check `pyvpn-server-logs` for
`UDP path established` or `UDP path inactive` to see whether UDP 8444 reaches
the server.

The complete package, architecture, TUN device, and NAT tools are verified
before system files are changed.
