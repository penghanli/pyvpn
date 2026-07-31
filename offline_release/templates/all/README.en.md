# pyvpn All-Platform Offline Release

This collection is intended for environments where GitHub or PyPI is
unreachable or slow. Send and extract only the archive matching the target
machine.

## Select A Package

| Target | File |
|---|---|
| Windows 10/11 x64 client | `pyvpn-offline-client-windows-x64-*.zip` |
| Linux x86_64 client | `pyvpn-offline-client-linux-x86_64-*.tar.gz` |
| Linux x86_64 server | `pyvpn-offline-server-linux-x86_64-*.tar.gz` |
| Linux ARM64 client | `pyvpn-offline-client-linux-arm64-*.tar.gz` |
| Linux ARM64 server | `pyvpn-offline-server-linux-arm64-*.tar.gz` |
| Intel Mac client | `pyvpn-offline-client-macos-x86_64-*.tar.gz` |
| Apple Silicon Mac client | `pyvpn-offline-client-macos-arm64-*.tar.gz` |

Every package includes Python, pyvpn, Python dependencies, an installer,
Chinese and English README files, and SHA-256 checksums. Customers do not need
to install Python or Git.

Linux still requires systemd, TUN, and operating-system network tools. The
macOS client is the sudo-based CLI version. The Windows client must be
installed and run from an administrator PowerShell window.

Use `SHA256SUMS` to verify every archive in this collection.
