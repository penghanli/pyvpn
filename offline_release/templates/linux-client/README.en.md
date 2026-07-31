# pyvpn Linux Offline Client

Python, pyvpn, and all Python dependencies are included. Installation does not
access GitHub, PyPI, or Linux package repositories. The package supports
glibc 2.28+ Linux on `x86_64` and `arm64`.

## Install

The system must provide `ip`, `sha256sum`, and `/dev/net/tun`. Extract the
archive and install as root:

```bash
sudo ./install-client.sh
```

The installer checks root access, architecture, package integrity, TUN, system
commands, and disk space before creating `pyvpn-client` under the extracted
package directory. It does not change an older `/opt`, `/etc`, systemd, or
`/usr/local/bin` installation.

The first install asks for the server, token, and certificate fingerprint. The
initial `server_id` is `default`.

## Use

```bash
sudo ./pyvpn-client/pyvpn-client-up
sudo ./pyvpn-client/pyvpn-client-down
sudo ./pyvpn-client/pyvpn-client-status
```

Add a server; token input is hidden when `--token` is omitted:

```bash
sudo ./pyvpn-client/pyvpn-client-servers add aliyun-sg \
  --server-host <server-host> \
  --cert-fingerprint 'sha256:<server-fingerprint>'
```

Append `--replace` when the address, token, or fingerprint for the same
`server_id` changes. Print the active server details with:

```bash
sudo ./pyvpn-client/pyvpn-client-servers show
```

List servers and latency, select for the next connection, or switch now:

```bash
sudo ./pyvpn-client/pyvpn-client-servers list
sudo ./pyvpn-client/pyvpn-client-servers use aliyun-sg
sudo ./pyvpn-client/pyvpn-client-switch aliyun-sg
```

Profiles are stored in `pyvpn-client/config/servers.json`; tokens are masked in
normal output. The client only needs outbound access to server TCP `8443` and
UDP `8444`. Do not move or delete the installed directory.
