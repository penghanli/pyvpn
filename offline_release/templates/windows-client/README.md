# pyvpn Windows x64 离线客户端

适用于 Windows 10/11 x64。本压缩包已经包含 Python、pyvpn、Python
依赖和官方 Wintun，无需安装 Python、Git，也不会访问 GitHub 或 PyPI。

## 安装

1. 解压整个压缩包。
2. 右键 Windows PowerShell，选择“以管理员身份运行”。
3. 进入解压后的目录，运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install-client.ps1
```

首次安装会依次询问服务器地址、共享 Token 和证书指纹。输入 Token 时屏幕
不会显示字符。升级已有 pyvpn 时，默认保留现有配置。

无人值守安装仍可使用参数：

```powershell
powershell -ExecutionPolicy Bypass -File .\install-client.ps1 -ServerHost <server-host> -Token '<shared-token>' -CertFingerprint 'sha256:<server-fingerprint>'
```

## 连接

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-up.ps1"
```

断开：

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-down.ps1"
```

状态和日志：

```powershell
powershell -ExecutionPolicy Bypass -File "C:\ProgramData\pyvpn\pyvpn-client-status.ps1"
```

## 系统要求

- 必须在管理员 PowerShell 中安装、连接和断开。
- 客户端需要能够访问服务器 TCP `8443` 和 UDP `8444`。
- 安装脚本会在修改系统前验证压缩包内容；校验失败时请重新获取完整压缩包。

升级过程会保留 `C:\ProgramData\pyvpn` 下的配置，并在安装目录中保留上一版
运行时用于失败恢复。
