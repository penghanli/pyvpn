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

如果 UFW 已启用且默认拦截转发，还需在安装后允许 VPN 子网经默认网卡出站
（以下为默认 `pyvpn0` 和 `10.8.0.0/24`，自定义配置需相应替换）：

```bash
WAN_IF=$(ip -4 route show default | awk '/default/ {for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')
sudo ufw route allow in on pyvpn0 out on "$WAN_IF" from 10.8.0.0/24
```

不要为安装 pyvpn 而执行 `ufw enable` 或 `ufw reset`，以免影响现有 SSH 规则。

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
证书和私钥；客户端无需重新输入这些值。升级会重启服务，现有连接短暂中断。

## 管理

```bash
sudo pyvpn-server-status
sudo pyvpn-server-logs
sudo pyvpn-server-restart
```

`pyvpn-server-status` 会同时打印 `server.env` 配置和运行中进程的 `token_id`；
两者必须一致，客户端 `show` 输出的 `token_id` 也应与它们一致。
若控制连接成功但无法上网，可在 `pyvpn-server-logs` 中查看
`UDP path established` 或 `UDP path inactive`，确认客户端 UDP `8444`
是否到达服务端。

安装器会在修改系统前验证完整压缩包、架构、TUN 和 NAT 工具。
