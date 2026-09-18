from __future__ import annotations

from pathlib import Path

from pyvpn import tun
from pyvpn.client import ClientConfig, VpnClient
from pyvpn.windows_app import (
    WINDOWS_APP_VERSION,
    native_windows_architecture,
    resolve_app_paths,
)


FINGERPRINT = "sha256:" + "a" * 64


def test_windows_gui_version_matches_release_file() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    version = (repo_root / "windows_gui" / "VERSION").read_text(encoding="ascii").strip()
    assert WINDOWS_APP_VERSION == version


def test_windows_gui_uses_portable_data_directory_by_default(tmp_path: Path) -> None:
    paths = resolve_app_paths(tmp_path, environment={})

    assert paths.data_dir == tmp_path / "pyvpn-data"
    assert paths.profiles == tmp_path / "pyvpn-data" / "servers.json"
    assert paths.stop.parent == paths.data_dir
    assert paths.ready.parent == paths.data_dir


def test_windows_gui_reuses_adjacent_offline_profiles(tmp_path: Path) -> None:
    profile_path = tmp_path / "pyvpn-client" / "config" / "servers.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("{}", encoding="utf-8")

    paths = resolve_app_paths(tmp_path, environment={})

    assert paths.profiles == profile_path
    assert paths.data_dir == profile_path.parent


def test_windows_gui_profile_override_takes_priority(tmp_path: Path) -> None:
    override = tmp_path / "shared" / "nodes.json"
    paths = resolve_app_paths(
        tmp_path / "application",
        environment={"PYVPN_PROFILE_FILE": str(override)},
    )

    assert paths.profiles == override
    assert paths.data_dir == override.parent


def test_native_windows_architecture_prefers_native_environment_value() -> None:
    assert native_windows_architecture(
        {
            "PROCESSOR_ARCHITECTURE": "x86",
            "PROCESSOR_ARCHITEW6432": "AMD64",
        }
    ) == "amd64"


def test_client_ready_marker_is_created_and_removed(tmp_path: Path) -> None:
    ready_path = tmp_path / "client.ready"
    config = ClientConfig(
        server_host="vpn.example.com",
        control_port=8443,
        token="token",
        cert_fingerprint=FINGERPRINT,
        client_id="test-client",
        tun_name="pyvpn0",
        mtu=1280,
        manage_dns=True,
        bypass_ips=[],
        stop_file=None,
        ready_file=str(ready_path),
    )
    vpn = VpnClient(config)

    vpn._write_ready_file()
    assert ready_path.read_text(encoding="ascii") == "ready\n"

    vpn._clear_ready_file()
    assert not ready_path.exists()


def test_wintun_lookup_supports_pyinstaller_onefile_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    bundled_dll = tmp_path / "wintun.dll"
    bundled_dll.write_bytes(b"test")
    monkeypatch.delenv("PYVPN_WINTUN_DLL", raising=False)
    monkeypatch.setattr(tun.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert tun._find_wintun_dll() == bundled_dll


def test_windows_build_requests_single_file_uac_executable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "windows_gui" / "build.py").read_text(encoding="utf-8")

    assert '"--onefile"' in source
    assert '"--windowed"' in source
    assert '"--uac-admin"' in source
    assert '"--add-binary"' in source
