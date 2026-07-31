# pyvpn macOS Offline CLI Client

For macOS 12+. Use `x86_64` on Intel Macs and `arm64` on Apple Silicon. Python,
pyvpn, and all Python dependencies are included, with no GitHub, PyPI, or
Homebrew access during installation.

## Install

Extract the archive, enter its directory, and install as root:

```bash
sudo ./install-client.sh
```

If macOS blocks the files, first run:

```bash
sudo xattr -dr com.apple.quarantine .
```

The installer checks macOS version, root access, architecture, package
integrity, system commands, and disk space before creating `pyvpn-client` under
the current package directory. Older `/opt`, `/Library`, and `/usr/local/bin`
installations are not read, stopped, or overwritten. The first server ID is
`default`.

## Use

```bash
sudo ./pyvpn-client/pyvpn-client-up
sudo ./pyvpn-client/pyvpn-client-down
sudo ./pyvpn-client/pyvpn-client-status
```

Add a server, list latency, select a server, or switch immediately:

```bash
sudo ./pyvpn-client/pyvpn-client-servers add aliyun-sg \
  --server-host <server-host> \
  --cert-fingerprint 'sha256:<server-fingerprint>'
sudo ./pyvpn-client/pyvpn-client-servers show
sudo ./pyvpn-client/pyvpn-client-servers list
sudo ./pyvpn-client/pyvpn-client-servers use aliyun-sg
sudo ./pyvpn-client/pyvpn-client-switch aliyun-sg
```

Token input is hidden when `--token` is omitted and normal output masks it.
Profiles are stored in `pyvpn-client/config/servers.json`. This is a sudo utun
CLI client, not a native NetworkExtension app. Append `--replace` to the add
command when details for the same `server_id` change.
