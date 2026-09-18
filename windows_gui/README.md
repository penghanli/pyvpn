# pyvpn Windows 图形客户端

`pyvpn.exe` 是 Windows 10/11 x64 单文件客户端，内置 Python、pyvpn、依赖和
官方 AMD64 Wintun。目标电脑不需要安装 Python，也不需要联网下载安装组件。

## 使用

1. 双击 `pyvpn.exe`，在 UAC 窗口中允许管理员权限。
2. 点击“添加节点”，填写节点 ID、服务器地址、控制端口、共享 Token 和服务端
   证书 SHA-256 指纹。
3. 选择节点后点击“切换到此节点”，再点击“连接”。
4. “全部测速”测试各节点 TCP 控制端口的连接延迟；该数值不是下载带宽。

节点和日志默认保存在 EXE 同目录的 `pyvpn-data`。如果 EXE 放在已安装的
Windows 离线包根目录，程序会优先复用
`pyvpn-client\config\servers.json`，因此原命令行脚本和 GUI 可以使用同一组
节点。也可通过 `PYVPN_GUI_DATA_DIR` 指定数据目录，或通过
`PYVPN_PROFILE_FILE` 指定现有 `servers.json`。

关闭界面时，如果 VPN 仍在运行，程序会先询问并正常断开。Token 不会显示在
节点列表中，但会以明文保存在本机 `servers.json`；不要转发 `pyvpn-data` 或
节点文件。程序会尽量把新建数据目录的权限限制给 Windows 管理员和 SYSTEM。
连接始终校验节点配置中的证书指纹。

## 构建

在 Windows x64、Python 3.12 环境中运行：

```powershell
python -m pip install -r offline_release\build-requirements.txt
python windows_gui\build.py
```

输出位于 `windows_gui\dist`：

- `pyvpn.exe`
- `pyvpn.exe.sha256`
- `pyvpn-windows-x64-0.1.0-r1.zip`

构建脚本固定并校验 Wintun 0.14.1 官方压缩包，使用 PyInstaller
`--onefile --windowed --uac-admin`。当前构建没有 Authenticode 商业代码签名；
向客户分发前应使用公司的代码签名证书签名，并重新生成 SHA-256。
