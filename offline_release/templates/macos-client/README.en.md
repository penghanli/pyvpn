# pyvpn macOS Offline CLI Client

This package supports macOS 12+. Use the `x86_64` archive for Intel Macs or the
`arm64` archive for Apple Silicon. Python, pyvpn, and all Python dependencies
are included; installation does not contact GitHub, PyPI, or Homebrew.

This is the current sudo-based `utun` command-line client, not a graphical
NetworkExtension application.

The Apple Silicon package uses `cryptography 49.0.0`. Upstream removed Intel
Mac support in 49.0.0, so the Intel package uses the final x86_64-supported
release, `47.0.0`.

## Install

Extract the archive, open Terminal, enter the extracted directory, and run:

```bash
sudo ./install-client.sh
```

A new installation prompts for the server host, shared token, and certificate
fingerprint. Token input is hidden. Existing pyvpn settings are reused during
an upgrade.

If macOS reports that files are from an unidentified developer, run:

```bash
sudo xattr -dr com.apple.quarantine .
```

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

The client must reach server TCP `8443` and UDP `8444`. The package, CPU
architecture, and required macOS commands are checked before installation.
