# pyvpn macOS 离线 CLI 客户端

适用于 macOS 12+。Intel Mac 使用 `x86_64` 包，Apple Silicon 使用 `arm64`
包。本包包含 Python、pyvpn 和全部 Python 依赖，不访问 GitHub、PyPI 或
Homebrew。

## 安装

解压后进入目录，以 root 安装：

```bash
sudo ./install-client.sh
```

如果 macOS 阻止运行，先执行：

```bash
sudo xattr -dr com.apple.quarantine .
```

安装器先检查 macOS 版本、root、架构、压缩包、系统命令和磁盘空间，再在当前
目录下创建 `pyvpn-client`。旧版 `/opt`、`/Library` 和 `/usr/local/bin`
安装不会被读取、停止或覆盖。首次节点 ID 为 `default`。

## 使用

```bash
sudo ./pyvpn-client/pyvpn-client-up
sudo ./pyvpn-client/pyvpn-client-down
sudo ./pyvpn-client/pyvpn-client-status
```

添加节点、列出延迟、选择节点和立即切换：

```bash
sudo ./pyvpn-client/pyvpn-client-servers add aliyun-sg \
  --server-host <server-host> \
  --cert-fingerprint 'sha256:<server-fingerprint>'
sudo ./pyvpn-client/pyvpn-client-servers show
sudo ./pyvpn-client/pyvpn-client-servers list
sudo ./pyvpn-client/pyvpn-client-servers use aliyun-sg
sudo ./pyvpn-client/pyvpn-client-switch aliyun-sg
```

省略 `--token` 时 Token 会隐藏输入，正常输出也只显示遮盖值。节点文件是
`pyvpn-client/config/servers.json`。这是需要 `sudo` 的 utun 命令行客户端，
不是 NetworkExtension 图形 App。同一个 `server_id` 的信息有变化时，在添加命令
末尾加 `--replace`。
