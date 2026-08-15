# pyvpn Android

这是与现有 pyvpn Linux 服务端协议兼容的原生 Android 客户端。

## 使用要求

- Android 9（API 28）或更高版本。
- 服务端继续开放 TCP `8443` 和 UDP `8444`。
- 每个节点需要服务器 IP/域名、Token 和 `sha256:` 证书指纹。

## 安装和使用

1. 将 `pyvpn-android-0.1.0.apk` 复制到手机并安装。
2. 打开 `pyvpn`，点击“添加节点”。
3. 填写服务器 IP、控制端口、Token 和证书指纹并保存。
4. 选择节点并点击“连接”，首次连接时允许 Android 创建 VPN。
5. 在节点下拉框中选择其他节点。未连接时点击“连接”；已连接时点击“切换并连接”。

下拉框当前选中的节点会保存为默认节点。应用重新打开后仍会选中该节点，但不会自行连接。

Token 和节点配置使用 Android Keystore 加密保存在应用私有目录中，不写入日志，也不会进入 Android 备份。

## 构建 APK

需要 JDK 17 和 Android SDK 35。Windows PowerShell：

```powershell
cd android
powershell -ExecutionPolicy Bypass -File .\build-apk.ps1
```

生成的正式签名 APK 位于：

```text
android/dist/pyvpn-android-0.1.0.apk
```

首次构建会生成 `android/.signing/pyvpn-release.jks` 和密码配置。它们不会提交到 Git，但后续 APK 升级必须使用同一个签名，因此需要单独备份整个 `android/.signing/` 目录。

也可以只构建测试 APK：

```powershell
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

测试 APK 位于 `app/build/outputs/apk/debug/`。

## 当前范围

- 支持多个节点、默认节点、添加、编辑、删除、连接、断开和切换重连。
- 支持 IPv4 全流量 VPN、DNS、TLS 证书指纹固定和 ChaCha20-Poly1305 数据加密。
- 不支持 IPv6 隧道和 Android 8 或更早系统。
