# pyvpn macOS 离线 CLI 客户端

适用于 macOS 12+。请使用与 Mac 一致的 `x86_64`（Intel）或 `arm64`
（Apple Silicon）压缩包。本包包含 Python、pyvpn 和全部 Python 依赖，
安装时不访问 GitHub、PyPI 或 Homebrew。

当前是基于系统 `utun` 的命令行客户端，需要使用 `sudo`，不是
NetworkExtension 图形 App。

Apple Silicon 包使用 `cryptography 49.0.0`。由于上游已移除 49.0.0 对
Intel Mac 的支持，Intel 包使用最后仍支持 x86_64 的 `47.0.0`。

## 安装

解压后打开“终端”，进入解压目录并运行：

```bash
sudo ./install-client.sh
```

首次安装会询问服务器地址、共享 Token 和证书指纹。输入 Token 时不会显示
字符。升级已有 pyvpn 时默认保留现有配置。

如果 macOS 提示文件来自未知开发者，先在当前目录运行：

```bash
sudo xattr -dr com.apple.quarantine .
```

无人值守安装：

```bash
sudo ./install-client.sh \
  --server-host <server-host> \
  --token '<shared-token>' \
  --cert-fingerprint 'sha256:<server-fingerprint>'
```

## 连接

```bash
sudo pyvpn-client-up
```

断开和查看状态：

```bash
sudo pyvpn-client-down
sudo pyvpn-client-status
```

客户端需要能够访问服务器 TCP `8443` 和 UDP `8444`。安装器会在修改系统
前验证压缩包、CPU 架构和 macOS 系统命令。
