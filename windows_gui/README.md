# pyvpn Windows 图形客户端

`pyvpn.exe` 是 Windows 10/11 x64 单文件客户端，内置 Python、pyvpn、依赖和
官方 AMD64 Wintun。目标电脑不需要安装 Python，也不需要联网下载安装组件。

## 使用

1. 双击 `pyvpn.exe`，在 UAC 窗口中允许管理员权限。
2. 点击“添加节点”，填写节点 ID、服务器地址、控制端口、共享 Token 和服务端
   证书 SHA-256 指纹。
3. 选择节点后点击“切换到此节点”，再点击“连接”。
4. “全部测速”测试各节点 TCP 控制端口的连接延迟；该数值不是下载带宽。

“已连接”表示已收到服务端加密 UDP 回包。网络中断或 Windows 路由/DNS 变化后程序会持续尝试重连，
界面会显示“正在重连”；此时可点击“取消连接”。短暂的路由检查失败不会立刻断开现有连接。
本版将 UDP 数据按顺序批量写入虚拟网卡，并在 Wintun 写入持续失败时重连。

节点、客户端 ID 和日志默认保存在 EXE 同目录的 `pyvpn-data`。如果 EXE 放在已安装的
Windows 离线包根目录，程序会优先复用
`pyvpn-client\config\servers.json`，因此原命令行脚本和 GUI 可以使用同一组
节点。也可通过 `PYVPN_GUI_DATA_DIR` 指定数据目录，或通过
`PYVPN_PROFILE_FILE` 指定现有 `servers.json`。

关闭界面时，如果 VPN 仍在运行，程序会先询问并正常断开。Token 不会显示在
节点列表中，但会以明文保存在本机 `servers.json`；不要转发 `pyvpn-data` 或
节点文件。程序会尽量把新建数据目录的权限限制给 Windows 管理员和 SYSTEM。
连接始终校验节点配置中的证书指纹。重装或更新 EXE 时保留 `pyvpn-data`，
即可沿用节点和客户端 ID。

点击“查看日志”可打开数据目录。`client.log` 记录连接尝试，
`client.err.log` 记录重连原因和错误；日志按会话追加，达到 5 MiB 后在下次连接时
轮转为 `.1` 备份。排查故障时保留日志并记录出现问题的时间，转发前检查其中的
服务器地址和本机网络信息，勿转发 `servers.json` 或 Token。

## 连接故障

如果显示“已连接”但网页打不开，在管理员 PowerShell 中检查：

```powershell
Find-NetRoute -RemoteIPAddress 1.1.1.1
Test-NetConnection 1.1.1.1 -Port 443
Resolve-DnsName www.microsoft.com
```

同时查看 EXE 旁 `pyvpn-data\client.err.log`；如果复用了离线客户端配置，
日志位于 `pyvpn-client\config\client.err.log`。请勿发送 `servers.json` 或 Token。
“测速”只测试节点的 TCP 控制端口，不能判断 UDP 数据通道是否畅通。
若某个应用提示 `ECONNRESET`，还应检查该应用是否单独设置了 HTTP/HTTPS 代理。

## 构建

在 Windows x64、Python 3.12 环境中运行：

```powershell
python -m pip install -r offline_release\build-requirements.txt
python windows_gui\build.py
```

输出位于 `windows_gui\dist`：

- `pyvpn.exe`
- `pyvpn.exe.sha256`
- `pyvpn-windows-x64-0.1.0-r6.zip`

构建脚本固定并校验 Wintun 0.14.1 官方压缩包，使用 PyInstaller
`--onefile --windowed --uac-admin`。当前构建没有 Authenticode 商业代码签名；
向客户分发前应使用公司的代码签名证书签名，并重新生成 SHA-256。
