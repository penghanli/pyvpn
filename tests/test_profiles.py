from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from pyvpn import client, profiles
from pyvpn.profiles import (
    ProfileError,
    ServerProfile,
    add_profile,
    load_profile_store,
    remove_profile,
    save_profile_store,
    select_profile,
    selected_profile,
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


def test_profile_validation_rejects_unsafe_values() -> None:
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
