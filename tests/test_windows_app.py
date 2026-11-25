from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from pyvpn import tun
from pyvpn import routes
from pyvpn import system
from pyvpn.client import ClientConfig, VpnClient
from pyvpn.errors import PlatformError
from pyvpn.windows_app import (
    WINDOWS_APP_VERSION,
    begin_log_session,
    native_windows_architecture,
    resolve_app_paths,
    tail_text,
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


def test_closing_gui_cancels_pending_node_switch(monkeypatch) -> None:
    from pyvpn import windows_gui

    app = windows_gui.PyVpnWindowsApp.__new__(windows_gui.PyVpnWindowsApp)
    app.root = object()
    app.pending_reconnect = True
    app.close_after_stop = False
    requested: list[bool] = []
    app._running_pid = lambda: 1234
    app._request_disconnect = lambda: requested.append(True)
    monkeypatch.setattr(windows_gui.messagebox, "askyesno", lambda *_args, **_kwargs: True)

    app._on_close()

    assert app.pending_reconnect is False
    assert app.close_after_stop is True
    assert requested == [True]


def test_powershell_failure_does_not_repeat_the_full_script(monkeypatch) -> None:
    script = "$privateValue = 'not-for-logs'; throw 'route unavailable'"

    def failed_run(args, *, check, timeout):
        assert check is False
        assert timeout == 30
        return subprocess.CompletedProcess(args, 1, "", "Find-NetRoute: System Error 1232")

    monkeypatch.setattr(system, "run", failed_run)
    with pytest.raises(PlatformError, match="System Error 1232") as error:
        system.run_powershell(script)
    assert "not-for-logs" not in str(error.value)


def test_powershell_timeout_is_bounded_and_retryable(monkeypatch) -> None:
    def timed_out(args, *, check, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    monkeypatch.setattr(system, "run", timed_out)
    with pytest.raises(PlatformError, match="timed out after 10s"):
        system.run_powershell("Find-NetRoute", timeout=10)
    result = system.run_powershell("Remove-NetRoute", check=False, timeout=20)
    assert result.returncode == 124


def test_system_commands_do_not_open_a_windows_console(monkeypatch) -> None:
    observed = {}

    def fake_run(args, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "ok\n", "")

    monkeypatch.setattr(system.subprocess, "run", fake_run)
    result = system.run(["powershell.exe", "-Command", "Write-Output ok"])

    expected = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    assert observed["creationflags"] == expected
    assert result.stdout == "ok\n"


def test_gui_logs_keep_prior_sessions_without_stale_errors(tmp_path: Path) -> None:
    log = tmp_path / "client.err.log"
    first_offset = begin_log_session(log, "first")
    with log.open("a", encoding="utf-8") as stream:
        stream.write("connection interrupted: old error\n")

    second_offset = begin_log_session(log, "second")
    assert second_offset > first_offset
    assert tail_text(log, start_offset=second_offset) == ""
    assert "old error" in log.read_text(encoding="utf-8")

    with log.open("a", encoding="utf-8") as stream:
        stream.write("connection interrupted: new error\n")
    assert tail_text(log, start_offset=second_offset) == "connection interrupted: new error"


def test_gui_logs_rotate_when_size_limit_is_reached(tmp_path: Path) -> None:
    log = tmp_path / "client.log"
    log.write_text("previous output", encoding="utf-8")

    offset = begin_log_session(log, "sg", max_bytes=10)

    assert (tmp_path / "client.log.1").read_text(encoding="utf-8") == "previous output"
    assert "session started: sg" in log.read_text(encoding="utf-8")
    assert tail_text(log, start_offset=offset) == ""


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell")
def test_windows_route_setup_script_parses(monkeypatch) -> None:
    scripts: list[str] = []
    monkeypatch.setattr(
        routes, "run_powershell", lambda script, **_kwargs: scripts.append(script)
    )
    network = routes.WindowsClientNetwork(
        tun_name="pyvpn0",
        server_ips=["203.0.113.10"],
        gateway="10.8.0.1",
        dns="1.1.1.1",
    )
    network.setup()
    network.verify()
    network.repair()

    assert len(scripts) == 3
    assert all(
        "Get-NetIPInterface -AddressFamily IPv4 -ConnectionState Connected" in script
        for script in scripts
    )
    assert all("$interfaceMetrics[[int]$_.InterfaceIndex]" in script for script in scripts)
    assert "Find-NetRoute -RemoteIPAddress $ip" not in scripts[0]
    assert "Find-NetRoute -RemoteIPAddress $ip" in scripts[1]
    assert "Server bypass route to $ip changed" in scripts[1]
    assert "Get-DnsClientServerAddress" in scripts[1]
    assert "Set-DnsClientServerAddress" in scripts[2]
    assert "-InterfaceIndex $tun.ifIndex -PolicyStore ActiveStore" in scripts[2]
    parser = (
        "$tokens=$null;$errors=$null;"
        "[System.Management.Automation.Language.Parser]::ParseInput("
        "[Console]::In.ReadToEnd(),[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count){$errors|ForEach-Object{$_.Message};exit 1}"
    )
    for script in scripts:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", parser],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
