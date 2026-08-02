# pyvpn Windows x64 离线客户端

适用于 Windows 10/11 x64。本包包含 Python、pyvpn、全部 Python 依赖和官方
Wintun，安装时不访问 GitHub 或 PyPI。

## 安装

1. 完整解压压缩包。
2. 右键 Windows PowerShell，选择“以管理员身份运行”。
3. 进入包含 `install-client.ps1` 的目录并运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install-client.ps1
```

安装器先检查管理员权限、Windows/CPU 架构、压缩包、Wintun 和磁盘空间，然后
在当前解压目录下创建 `pyvpn-client`。运行时、日志和节点配置都保存在该目录，
不会读取、停止或覆盖旧版系统目录中的安装。

首次安装会询问服务器地址、共享 Token 和证书指纹，初始 `server_id` 为
`default`。Token 输入时不会显示字符。

## 连接

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-up.ps1"
```

断开和状态：

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-down.ps1"
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-status.ps1"
```

## 管理节点

添加节点；未通过 `--token` 传入时会隐藏输入 Token：

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" add aliyun-sg --server-host <server-host> --cert-fingerprint "sha256:<server-fingerprint>"
```

同一个 `server_id` 的地址、Token 或指纹有变化时，在上述命令末尾加
`--replace`。只更新当前节点 Token，不改变地址、指纹或其他选项：

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" set-token
```

查看当前节点详情：

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" show
```

列出全部节点和 TCP 控制端口延迟：

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" list
```

选择下次连接使用的节点：

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-servers.ps1" use aliyun-sg
```

立即断开、切换并重连：

```powershell
powershell -ExecutionPolicy Bypass -File ".\pyvpn-client\pyvpn-client-switch.ps1" aliyun-sg
```

节点保存在 `pyvpn-client\config\servers.json`，Token 默认只以遮盖形式打印；
`token_id` 是用于和服务端状态对比的短标识，不是 Token。安装、
连接、断开和节点管理均应在管理员 PowerShell 中运行。不要移动或删除安装后的
`pyvpn-client` 目录。
