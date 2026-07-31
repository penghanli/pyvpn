# pyvpn Linux 离线客户端

本包包含 Python、pyvpn 和全部 Python 依赖，安装时不访问 GitHub、PyPI 或
Linux 软件源。支持 glibc 2.28+ 的 `x86_64` 和 `arm64` Linux。

## 安装

系统需已有 `ip`、`sha256sum` 和 `/dev/net/tun`。解压后以 root 安装：

```bash
sudo ./install-client.sh
```

安装器先检查 root、架构、压缩包、TUN、系统命令和磁盘空间，再在当前解压目录
下创建 `pyvpn-client`。它不会修改旧版的 `/opt`、`/etc`、systemd 服务或
`/usr/local/bin`。

首次安装会询问服务器、Token 和证书指纹，初始 `server_id` 为 `default`。

## 使用

```bash
sudo ./pyvpn-client/pyvpn-client-up
sudo ./pyvpn-client/pyvpn-client-down
sudo ./pyvpn-client/pyvpn-client-status
```

添加节点；省略 `--token` 时会隐藏输入：

```bash
sudo ./pyvpn-client/pyvpn-client-servers add aliyun-sg \
  --server-host <server-host> \
  --cert-fingerprint 'sha256:<server-fingerprint>'
```

同一个 `server_id` 的信息有变化时，在上述命令末尾加 `--replace`。打印当前节点
详情使用：

```bash
sudo ./pyvpn-client/pyvpn-client-servers show
```

列出节点和延迟、选择下次连接节点、立即切换并重连：

```bash
sudo ./pyvpn-client/pyvpn-client-servers list
sudo ./pyvpn-client/pyvpn-client-servers use aliyun-sg
sudo ./pyvpn-client/pyvpn-client-switch aliyun-sg
```

节点保存在 `pyvpn-client/config/servers.json`，Token 默认遮盖显示。客户端只需
出站访问服务端 TCP `8443` 和 UDP `8444`。不要移动或删除安装后的目录。
