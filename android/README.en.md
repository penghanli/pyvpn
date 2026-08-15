# pyvpn Android

This is a native Android client compatible with the existing pyvpn Linux server protocol.

## Requirements

- Android 9 (API 28) or newer.
- The server must allow inbound TCP `8443` and UDP `8444`.
- Each node needs a server IP/hostname, shared token, and `sha256:` certificate fingerprint.

## Install and use

1. Copy `pyvpn-android-0.1.0-r2.apk` to the phone and install it. It can upgrade v1 in place while preserving node profiles.
2. Open `pyvpn` and tap **Add node**.
3. Enter the server address, control port, token, and certificate fingerprint.
4. Select the node and tap **Connect**. Approve the Android VPN prompt on first use.
5. Select another node from the list. Tap **Connect** while disconnected or **Switch and connect** while connected.

The selected node is persisted as the default. Reopening the app keeps that selection but does not connect automatically.

Node data and tokens are encrypted with Android Keystore in app-private storage. They are not logged or included in Android backups.

## Build the APK

Install JDK 17 and Android SDK 35, then run from PowerShell:

```powershell
cd android
powershell -ExecutionPolicy Bypass -File .\build-apk.ps1
```

The signed APK is written to `android/dist/pyvpn-android-0.1.0-r2.apk`.

The first build creates `android/.signing/pyvpn-release.jks` and its local password file. Git ignores both files. Back up the complete `android/.signing/` directory because every future update must use the same signing key.

The version is defined once in `android/version.properties`; the local build script and GitHub Actions read it automatically.

## Changelog

- `0.1.0-r2`: Bind the control socket before `VpnService.protect()` for compatibility with Android vendor builds that allocate the socket file descriptor lazily.
- `0.1.0`: Initial Android release.
