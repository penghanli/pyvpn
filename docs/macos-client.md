# macOS Client

The macOS CLI client is experimental but runnable. It uses the native `utun`
kernel control from Python, so it must run with `sudo`. This is meant for direct
testing and self-owned machines. A production macOS app should still use the
signed NetworkExtension path under `macos/`.

## Install

Install Python 3.9+ first if `python3` is missing:

```bash
brew install python
```

Then install the pyvpn client:

```bash
git clone https://github.com/penghanli/pyvpn.git
cd pyvpn

sudo scripts/macos/install-client.sh \
  --server-host 51.79.147.199 \
  --token '<token-from-server>' \
  --cert-fingerprint 'sha256:<server-fingerprint>'
```

The installer copies `src/` directly and runs it with `PYTHONPATH`; it does not
build a pyvpn wheel, so it will not stop at `Preparing metadata (pyproject.toml)`.
Only the `cryptography` runtime dependency may need pip.

If PyPI is slow or blocked, use a mirror:

```bash
sudo scripts/macos/install-client.sh \
  --server-host 51.79.147.199 \
  --token '<token-from-server>' \
  --cert-fingerprint 'sha256:<server-fingerprint>' \
  --pip-index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

For fully offline installation, put compatible wheels under `wheelhouse/` in the
unzipped repo, or pass an explicit wheel directory:

```bash
python3 -m pip download --only-binary=:all: -d wheelhouse 'cryptography>=42.0.0'

sudo scripts/macos/install-client.sh \
  --server-host 51.79.147.199 \
  --token '<token-from-server>' \
  --cert-fingerprint 'sha256:<server-fingerprint>' \
  --wheel-dir ./wheelhouse
```

The installer creates:

```text
/opt/pyvpn-client/venv
/opt/pyvpn-client/app/src
/Library/Application Support/pyvpn/client.env
/usr/local/bin/pyvpn-client-start
/usr/local/bin/pyvpn-client-up
/usr/local/bin/pyvpn-client-down
/usr/local/bin/pyvpn-client-status
```

## Connect

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

Foreground debug mode:

```bash
sudo pyvpn-client-start
```

In foreground mode, disconnect with `Ctrl-C`.

## Verify

```bash
curl -4 https://ifconfig.me
route -n get default
netstat -rn -f inet | grep -E '^(default|0/1|128\\.0/1|51\\.79\\.147\\.199)'
scutil --dns | grep -A2 nameserver
```

The IPv4 curl result should be the server public IP. The route table should show
split default routes through the tunnel and a host route that keeps the VPN
server itself outside the tunnel.

## Notes

- The default requested interface is `utun7`. If that is already in use, rerun
  the installer with another name, for example `--tun utun8`.
- The client stores and restores the active network service DNS servers while it
  runs. If a forced kill leaves DNS changed, run `sudo pyvpn-client-down` again.
- IPv6 is not tunneled in v1. Disable IPv6 on the Mac network service if leak
  prevention matters for your test.
