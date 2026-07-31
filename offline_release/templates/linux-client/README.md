# pyvpn Linux 离线客户端

本压缩包已经包含 Python、pyvpn 和全部 Python 依赖，安装时不访问 GitHub、
PyPI 或 Linux 软件源。

## 系统要求

- glibc 2.28+、systemd。
- 使用与机器架构一致的 `x86_64` 或 `arm64` 压缩包。
- 系统已有 `ip`、`sha256sum` 和 `/dev/net/tun`。
- 安装、连接和断开均使用 root 或 `sudo`。
- 客户端能够访问服务器 TCP `8443` 和 UDP `8444`。

## 安装

解压后进入目录：

```bash
sudo ./install-client.sh
```

首次安装会询问服务器地址、共享 Token 和证书指纹。输入 Token 时不会显示
字符。升级已有 pyvpn 时默认保留 `/etc/pyvpn/client.env`。

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

安装脚本会先验证整个压缩包；校验、架构或系统要求不满足时，不会修改现有安装。
