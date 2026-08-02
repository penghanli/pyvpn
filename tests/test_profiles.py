from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from pyvpn import client, profiles
from pyvpn.errors import AuthenticationError
from pyvpn.profiles import (
    ProfileError,
    ServerProfile,
    add_profile,
    load_profile_store,
    remove_profile,
    save_profile_store,
    select_profile,
    selected_profile,
    update_profile_token,
)


FINGERPRINT = "sha256:" + "a" * 64


def make_profile(server_id: str, host: str) -> ServerProfile:
    return ServerProfile(
        server_id=server_id,
        server_host=host,
        control_port=8443,
        token=f"token-{server_id}",
        cert_fingerprint=FINGERPRINT,
    )


def test_profile_store_add_select_and_remove(tmp_path: Path) -> None:
    path = tmp_path / "servers.json"
    add_profile(path, make_profile("hk", "hk.example.com"))
    add_profile(path, make_profile("sg", "sg.example.com"))

    assert selected_profile(path).server_id == "hk"
    select_profile(path, "sg")
    assert selected_profile(path).server_host == "sg.example.com"

    store = remove_profile(path, "sg")
    assert store.active_server_id == "hk"
    assert set(store.servers) == {"hk"}


def test_profile_store_is_valid_json_and_replaces_atomically(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "servers.json"
    profile = make_profile("default", "203.0.113.10")
    add_profile(path, profile)
    replacement = ServerProfile(
        **{**profile.__dict__, "server_host": "203.0.113.20"}
    )
    add_profile(path, replacement, replace=True, make_active=True)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["active_server_id"] == "default"
    assert raw["servers"]["default"]["server_host"] == "203.0.113.20"
    assert list(path.parent.glob("*.tmp")) == []


def test_profile_token_is_trimmed_and_can_be_updated_without_resetting_options(
    tmp_path: Path,
) -> None:
    path = tmp_path / "servers.json"
    profile = ServerProfile(
        server_id="default",
        server_host="203.0.113.10",
        control_port=9443,
        token="  old-token\r\n",
        cert_fingerprint=FINGERPRINT,
        tun_name="custom-tun",
        mtu=1400,
        no_dns=True,
        bypass_ips=("198.51.100.10",),
    )
    add_profile(path, profile, make_active=True)

    updated = update_profile_token(path, None, "  new-token  ")

    assert updated.token == "new-token"
    assert updated.server_host == profile.server_host
    assert updated.control_port == 9443
    assert updated.tun_name == "custom-tun"
    assert updated.mtu == 1400
    assert updated.no_dns is True
    assert updated.bypass_ips == ("198.51.100.10",)
    assert selected_profile(path).token == "new-token"


def test_profile_validation_rejects_unsafe_values(tmp_path: Path) -> None:
    with pytest.raises(ProfileError):
        make_profile("bad id", "vpn.example.com")
    with pytest.raises(ProfileError):
        ServerProfile(
            server_id="valid",
            server_host="vpn.example.com",
            control_port=8443,
            token="token",
            cert_fingerprint="sha256:bad",
        )
    unsafe_profile = ServerProfile(
        server_id="valid",
        server_host="vpn.example.com",
        control_port=8443,
        token="\x16",
        cert_fingerprint=FINGERPRINT,
    )
    with pytest.raises(ProfileError, match="printable"):
        add_profile(tmp_path / "servers.json", unsafe_profile)


def test_legacy_control_character_token_can_be_repaired(tmp_path: Path) -> None:
    path = tmp_path / "servers.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "active_server_id": "default",
                "servers": {
                    "default": {
                        "server_host": "vpn.example.com",
                        "control_port": 8443,
                        "token": "\x16",
                        "cert_fingerprint": FINGERPRINT,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert selected_profile(path).token == "\x16"
    updated = update_profile_token(path, "default", "replacement")

    assert updated.token == "replacement"
    assert selected_profile(path).token == "replacement"


def test_profile_store_rejects_unknown_active_server(tmp_path: Path) -> None:
    path = tmp_path / "servers.json"
    path.write_text(
        json.dumps({"version": 1, "active_server_id": "missing", "servers": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ProfileError):
        load_profile_store(path)


def test_save_rejects_unknown_active_server(tmp_path: Path) -> None:
    path = tmp_path / "servers.json"
    store = load_profile_store(path, allow_missing=True)
    with pytest.raises(ProfileError):
        save_profile_store(
            path,
            type(store)(active_server_id="missing", servers={}),
        )


def test_client_loads_the_active_profile(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "servers.json"
    profile = make_profile("sg", "203.0.113.12")
    add_profile(path, profile, make_active=True)
    captured = []

    class FakeClient:
        def __init__(self, config):
            captured.append(config)

        async def run(self):
            return None

    monkeypatch.setattr(client, "VpnClient", FakeClient)
    asyncio.run(client.async_main(["--profiles", str(path)]))

    assert captured[0].server_host == "203.0.113.12"
    assert captured[0].token == "token-sg"
    assert captured[0].control_port == 8443


def test_client_can_select_a_saved_server_id(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "servers.json"
    add_profile(path, make_profile("hk", "203.0.113.11"), make_active=True)
    add_profile(path, make_profile("sg", "203.0.113.12"))
    captured = []

    class FakeClient:
        def __init__(self, config):
            captured.append(config)

        async def run(self):
            return None

    monkeypatch.setattr(client, "VpnClient", FakeClient)
    asyncio.run(client.async_main(["--profiles", str(path), "--server-id", "sg"]))

    assert captured[0].server_host == "203.0.113.12"
    assert captured[0].token == "token-sg"


def test_legacy_direct_client_arguments_still_work(monkeypatch) -> None:
    captured = []

    class FakeClient:
        def __init__(self, config):
            captured.append(config)

        async def run(self):
            return None

    monkeypatch.setattr(client, "VpnClient", FakeClient)
    asyncio.run(
        client.async_main(
            [
                "--server-host",
                "203.0.113.20",
                "--token",
                "legacy-token",
                "--cert-fingerprint",
                FINGERPRINT,
            ]
        )
    )

    config = captured[0]
    assert config.server_host == "203.0.113.20"
    assert config.token == "legacy-token"
    assert config.control_port == 8443
    assert config.tun_name == "pyvpn0"
    assert config.mtu == 1280
    assert config.manage_dns is True


def test_client_main_prints_authentication_errors_without_a_traceback(
    monkeypatch,
) -> None:
    async def fail_authentication():
        raise AuthenticationError("authentication failed (client token_id=abc123)")

    monkeypatch.setattr(client, "async_main", fail_authentication)
    monkeypatch.setattr(client.sys, "argv", ["pyvpn-client"])

    with pytest.raises(SystemExit, match="client token_id=abc123"):
        client.main()


def test_profile_cli_lists_latency_and_masks_token(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    path = tmp_path / "servers.json"
    add_profile(path, make_profile("hk", "hk.example.com"), make_active=True)
    monkeypatch.setattr(profiles, "probe_latency_ms", lambda host, port, timeout: 12.34)

    profiles.main(["--file", str(path), "list"])
    listed = capsys.readouterr().out
    assert "hk.example.com:8443" in listed
    assert "12.3 ms" in listed
    assert "*" in listed

    profiles.main(["--file", str(path), "show", "hk"])
    shown = capsys.readouterr().out
    assert "server_id: hk" in shown
    assert "token-hk" not in shown
    assert "token:" in shown
    assert "token_id:" in shown


def test_profile_cli_set_token_prompts_and_preserves_profile(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    path = tmp_path / "servers.json"
    add_profile(path, make_profile("default", "vpn.example.com"), make_active=True)
    monkeypatch.setattr(profiles.getpass, "getpass", lambda prompt: "  replacement  ")

    profiles.main(["--file", str(path), "set-token"])

    assert selected_profile(path).token == "replacement"
    output = capsys.readouterr().out
    assert "Updated token for server: default" in output
    assert "Token id:" in output


def test_profile_cli_set_token_accepts_environment_token(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "servers.json"
    add_profile(path, make_profile("default", "vpn.example.com"), make_active=True)
    monkeypatch.setenv("PYVPN_TOKEN", "  environment-token  ")
    monkeypatch.setattr(
        profiles.getpass,
        "getpass",
        lambda prompt: pytest.fail("set-token unexpectedly prompted"),
    )

    profiles.main(["--file", str(path), "set-token", "default"])

    assert selected_profile(path).token == "environment-token"
