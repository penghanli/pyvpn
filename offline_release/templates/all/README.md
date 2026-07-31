# pyvpn 全平台离线发行版

此压缩包集合用于无法访问 GitHub、PyPI 或下载速度较慢的环境。请只发送并
解压与目标机器匹配的单独压缩包。

## 文件选择

| 目标 | 文件名 |
|---|---|
| Windows 10/11 x64 客户端 | `pyvpn-offline-client-windows-x64-*.zip` |
| Linux x86_64 客户端 | `pyvpn-offline-client-linux-x86_64-*.tar.gz` |
| Linux x86_64 服务端 | `pyvpn-offline-server-linux-x86_64-*.tar.gz` |
| Linux ARM64 客户端 | `pyvpn-offline-client-linux-arm64-*.tar.gz` |
| Linux ARM64 服务端 | `pyvpn-offline-server-linux-arm64-*.tar.gz` |
| Intel Mac 客户端 | `pyvpn-offline-client-macos-x86_64-*.tar.gz` |
| Apple Silicon Mac 客户端 | `pyvpn-offline-client-macos-arm64-*.tar.gz` |

每个包都包含 Python、pyvpn、Python 依赖、安装脚本、中英文 README 和
SHA-256 校验文件。客户无需安装 Python 或 Git。

Linux 机器仍必须已有 systemd、TUN 和系统网络工具。macOS 客户端是需要
`sudo` 的 CLI 版本。Windows 客户端必须在管理员 PowerShell 中安装和运行。

`SHA256SUMS` 可用于确认集合中的每个文件没有损坏。
