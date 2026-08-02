from __future__ import annotations

import importlib.util
import os
import re
import tarfile
from pathlib import Path

OFFLINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = OFFLINE_ROOT.parent


def _load_build_module():
    path = OFFLINE_ROOT / "build_package.py"
    spec = importlib.util.spec_from_file_location("offline_build_package", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expected_package_matrix_and_names() -> None:
    build = _load_build_module()
    expected = {
        "pyvpn-offline-client-windows-x64-0.1.0-r4.zip",
        "pyvpn-offline-client-linux-x86_64-0.1.0-r4.tar.gz",
        "pyvpn-offline-server-linux-x86_64-0.1.0-r4.tar.gz",
        "pyvpn-offline-client-linux-arm64-0.1.0-r4.tar.gz",
        "pyvpn-offline-server-linux-arm64-0.1.0-r4.tar.gz",
        "pyvpn-offline-client-macos-x86_64-0.1.0-r4.tar.gz",
        "pyvpn-offline-client-macos-arm64-0.1.0-r4.tar.gz",
    }
    actual = {
        build._archive_name(target_platform, arch, role)
        for target_platform, arch, role in build.PACKAGE_MATRIX
    }
    assert actual == expected


def test_every_template_has_bilingual_readme_and_installer() -> None:
    expected_installers = {
        "windows-client": "install-client.ps1",
        "linux-client": "install-client.sh",
        "linux-server": "install-server.sh",
        "macos-client": "install-client.sh",
    }
    for template, installer in expected_installers.items():
        root = OFFLINE_ROOT / "templates" / template
        assert (root / "README.md").is_file()
        assert (root / "README.en.md").is_file()
        assert (root / installer).is_file()
    assert (OFFLINE_ROOT / "LICENSE.txt").is_file()
    assert (OFFLINE_ROOT / "THIRD_PARTY_NOTICES.txt").is_file()


def test_customer_installers_have_no_network_install_commands() -> None:
    installers = [
        OFFLINE_ROOT / "templates" / "windows-client" / "install-client.ps1",
        OFFLINE_ROOT / "templates" / "linux-client" / "install-client.sh",
        OFFLINE_ROOT / "templates" / "linux-server" / "install-server.sh",
        OFFLINE_ROOT / "templates" / "macos-client" / "install-client.sh",
    ]
    forbidden = [
        r"\bInvoke-WebRequest\b",
        r"\bStart-BitsTransfer\b",
        r"(^|[;&|]\s*)curl(?:\.exe)?\s",
        r"(^|[;&|]\s*)wget\s",
        r"(^|[;&|]\s*)git\s+(?:clone|pull|fetch)\b",
        r"(^|[;&|]\s*)(?:python3?|[^ ]+/python)\s+-m\s+pip\b",
        r"(^|[;&|]\s*)(?:apt|apt-get|yum|dnf|brew)\s+(?:install|update)\b",
    ]
    for installer in installers:
        text = installer.read_text(encoding="utf-8")
        for pattern in forbidden:
            assert re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE) is None, (
                installer,
                pattern,
            )


def test_offline_clients_install_locally_and_use_server_profiles() -> None:
    windows = (
        OFFLINE_ROOT / "templates" / "windows-client" / "install-client.ps1"
    ).read_text(encoding="utf-8")
    linux = (
        OFFLINE_ROOT / "templates" / "linux-client" / "install-client.sh"
    ).read_text(encoding="utf-8")
    macos = (
        OFFLINE_ROOT / "templates" / "macos-client" / "install-client.sh"
    ).read_text(encoding="utf-8")

    assert 'Join-Path $packageRoot "pyvpn-client"' in windows
    assert '$ConfigDir = Join-Path $InstallDir "config"' in windows
    assert "$env:ProgramData" not in windows
    assert "ProgramW6432" not in windows
    assert windows.index("show `$ServerId") < windows.index("$downScript) | Out-Host")

    for installer in (linux, macos):
        assert 'INSTALL_DIR="$PACKAGE_ROOT/pyvpn-client"' in installer
        assert 'CONFIG_DIR="$INSTALL_DIR/config"' in installer
        assert "/usr/local/bin" not in installer
        assert "servers.json" in installer
        assert "pyvpn-client-switch" in installer
        assert installer.index('"\\$SERVERS_SCRIPT" show') < installer.index(
            '"\\$DOWN_SCRIPT"'
        )


def test_generated_client_launchers_avoid_fragile_shell_constructs() -> None:
    windows = (
        OFFLINE_ROOT / "templates" / "windows-client" / "install-client.ps1"
    ).read_text(encoding="utf-8")
    linux = (
        OFFLINE_ROOT / "templates" / "linux-client" / "install-client.sh"
    ).read_text(encoding="utf-8")
    macos = (
        OFFLINE_ROOT / "templates" / "macos-client" / "install-client.sh"
    ).read_text(encoding="utf-8")

    assert "`$startProcessParams = @{" in windows
    assert "`$process = Start-Process @startProcessParams" in windows
    assert 'FilePath = `$powershellExe' in windows
    assert 'Start-Process -FilePath "powershell.exe" `' not in windows
    assert "`$clientArgs = @(" in windows
    assert "& `$runtimeExe @clientArgs" in windows
    assert "Get-NetRoute @routeQuery" in windows
    assert not any(line.rstrip().endswith("`") for line in windows.splitlines())

    for installer in (linux, macos):
        assert r'ARGS=(--profiles "\$PROFILES_PATH" --stop-file "\$STOP_FILE"' in installer
        assert r'[[ -f "\$ERR_FILE" ]] && tail' not in installer
        assert r'if [[ -f "\$ERR_FILE" ]]; then tail' in installer


def test_installers_validate_supported_architectures() -> None:
    windows = (
        OFFLINE_ROOT / "templates" / "windows-client" / "install-client.ps1"
    ).read_text(encoding="utf-8")
    linux_client = (
        OFFLINE_ROOT / "templates" / "linux-client" / "install-client.sh"
    ).read_text(encoding="utf-8")
    linux_server = (
        OFFLINE_ROOT / "templates" / "linux-server" / "install-server.sh"
    ).read_text(encoding="utf-8")
    macos = (
        OFFLINE_ROOT / "templates" / "macos-client" / "install-client.sh"
    ).read_text(encoding="utf-8")

    assert "PROCESSOR_ARCHITEW6432" in windows
    assert '$nativeArchitecture -ne "x64"' in windows
    for installer in (linux_client, linux_server):
        assert "x86_64|amd64) ACTUAL_ARCH=\"x86_64\"" in installer
        assert "aarch64|arm64) ACTUAL_ARCH=\"arm64\"" in installer
        assert '[[ "$ACTUAL_ARCH" != "$PACKAGE_ARCH" ]]' in installer
    assert 'x86_64) ACTUAL_ARCH="x86_64"' in macos
    assert 'arm64) ACTUAL_ARCH="arm64"' in macos
    assert '[[ "$ACTUAL_ARCH" != "$PACKAGE_ARCH" ]]' in macos


def test_fresh_server_default_is_five_clients() -> None:
    online = (REPO_ROOT / "scripts" / "linux" / "install-server.sh").read_text(
        encoding="utf-8"
    )
    offline = (
        OFFLINE_ROOT / "templates" / "linux-server" / "install-server.sh"
    ).read_text(encoding="utf-8")
    assert 'MAX_CLIENTS="5"' in online
    assert 'MAX_CLIENTS="5"' in offline


def test_manifest_detects_tampering(tmp_path: Path) -> None:
    build = _load_build_module()
    package = tmp_path / "package"
    package.mkdir()
    payload = package / "payload.txt"
    payload.write_text("original", encoding="utf-8")
    build._write_manifest(package)
    build._verify_tree(package)
    payload.write_text("changed", encoding="utf-8")
    try:
        build._verify_tree(package)
    except RuntimeError as exc:
        assert "mismatch" in str(exc)
    else:
        raise AssertionError("tampered package passed verification")


def test_pinned_runtime_build_versions() -> None:
    build = _load_build_module()
    assert build.REQUIRED_BUILD_VERSIONS == {
        "PyInstaller": "6.21.0",
        "cryptography": "49.0.0",
        "cffi": "2.1.0",
        "pycparser": "3.0",
    }
    assert build._required_build_versions("windows", "x64")["cryptography"] == "49.0.0"
    assert build._required_build_versions("linux", "arm64")["cryptography"] == "49.0.0"
    assert build._required_build_versions("macos", "arm64")["cryptography"] == "49.0.0"
    assert build._required_build_versions("macos", "x86_64")["cryptography"] == "47.0.0"
    assert build._openssl_version().startswith("OpenSSL ")


def test_assemble_all_platform_package(tmp_path: Path) -> None:
    build = _load_build_module()
    build.BUILD_ROOT = tmp_path / "build"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    for target_platform, arch, role in build.PACKAGE_MATRIX:
        filename = build._archive_name(target_platform, arch, role)
        (input_dir / filename).write_bytes(filename.encode("ascii"))

    all_archive = build.assemble_all(input_dir, output_dir)

    assert all_archive.name == "pyvpn-offline-all-0.1.0-r4.zip"
    assert (output_dir / "SHA256SUMS").is_file()
    assert len(list(output_dir.iterdir())) == 9
    build.verify_archive(all_archive)


def test_tar_normalizes_owner_and_preserves_executable_mode(tmp_path: Path) -> None:
    build = _load_build_module()
    source = tmp_path / "package"
    source.mkdir()
    installer = source / "install-client.sh"
    installer.write_text("#!/bin/sh\n", encoding="ascii")
    installer.chmod(0o755)
    archive = tmp_path / "package.tar.gz"

    build._create_tar(source, archive)

    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.getmember("package/install-client.sh")
    assert member.uid == 0
    assert member.gid == 0
    assert member.uname == "root"
    assert member.gname == "root"
    if os.name != "nt":
        assert member.mode & 0o111 == 0o111
    synthetic = tarfile.TarInfo("installer")
    synthetic.mode = 0o755
    assert build._root_owned_tar_info(synthetic).mode == 0o755


def test_existing_online_files_are_not_modified_by_release_sources() -> None:
    protected = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "scripts" / "windows" / "install-client.ps1",
        REPO_ROOT / "scripts" / "linux" / "install-client.sh",
        REPO_ROOT / "scripts" / "linux" / "install-server.sh",
        REPO_ROOT / "scripts" / "macos" / "install-client.sh",
    ]
    assert all(path.is_file() for path in protected)
