# pyvpn Linux 离线服务端

本压缩包已经包含 Python、pyvpn 和全部 Python 依赖，安装时不访问 GitHub、
PyPI 或 Linux 软件源。

## 系统要求

- glibc 2.28+、systemd。
- 使用与服务器架构一致的 `x86_64` 或 `arm64` 压缩包。
- 系统已有 `ip`、`sha256sum`、`nft` 或 `iptables`。
- `/dev/net/tun` 可用，并使用 root 或 `sudo` 安装。
- 云安全组和服务器防火墙已开放 TCP `8443`、UDP `8444`。

使用 `iptables` 的服务器可执行：

```bash
sudo iptables -I INPUT -p tcp --dport 8443 -j ACCEPT
sudo iptables -I INPUT -p udp --dport 8444 -j ACCEPT
```

如果系统使用 UFW，则执行：

```bash
sudo ufw allow 8443/tcp
sudo ufw allow 8444/udp
```

云服务器还要在云厂商安全组中开放同样的两个端口。

## 安装

解压后进入目录：

```bash
sudo ./install-server.sh
```

首次安装会询问服务器公网 IP 或域名。共享 Token 可留空自动生成。安装完成
后会输出客户端所需的服务器地址、Token 和证书指纹。

无人值守安装：

```bash
sudo ./install-server.sh --public-host <server-ip-or-domain> --max-clients 5
```

升级已有 pyvpn 时，默认保留 `/etc/pyvpn/server.env`、共享 Token、服务器
证书和私钥。

## 管理

```bash
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
```

`pyvpn-server-status` 会同时打印 `server.env` 配置和运行中进程的 `token_id`；
两者必须一致，客户端 `show` 输出的 `token_id` 也应与它们一致。

安装器会在修改系统前验证完整压缩包、架构、TUN 和 NAT 工具。
