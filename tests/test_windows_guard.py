from __future__ import annotations

import ipaddress
import json
import subprocess
from pathlib import Path

import pytest

from pyvpn import windows_guard
from pyvpn.errors import PlatformError


def _matches(address: str, networks: list[str]) -> bool:
    ip = ipaddress.ip_address(address)
    return any(ip in ipaddress.ip_network(value) for value in networks)


def test_public_guard_blocks_public_destinations_but_keeps_server_and_lan() -> None:
    blocked_v4 = windows_guard._blocked_networks(
        4, [*windows_guard._LOCAL_V4, "203.0.113.10/32"]
    )
    blocked_v6 = windows_guard._blocked_networks(6, list(windows_guard._LOCAL_V6))

    assert _matches("8.8.8.8", blocked_v4)
    assert _matches("203.0.113.11", blocked_v4)
    assert not _matches("203.0.113.10", blocked_v4)
    assert not _matches("192.168.1.1", blocked_v4)
    assert not _matches("255.255.255.255", blocked_v4)
    assert _matches("2606:4700:4700::1111", blocked_v6)
    assert not _matches("fe80::1", blocked_v6)
    assert not _matches("ff02::1", blocked_v6)


def test_public_guard_local_address_filter_excludes_only_tunnel_vip() -> None:
    physical_sources = windows_guard._blocked_networks(4, ["10.8.0.2/32"])
    assert _matches("192.168.1.20", physical_sources)
    assert _matches("10.8.0.3", physical_sources)
    assert not _matches("10.8.0.2", physical_sources)


def test_public_guard_installs_new_rules_before_removing_old_ones(
    monkeypatch, tmp_path: Path
) -> None:
    scripts: list[str] = []

    def fake_run(script: str, *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        scripts.append(script)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(windows_guard, "run_powershell", fake_run)
    guard = windows_guard.WindowsPublicGuard(tmp_path)
    guard.enable(["203.0.113.10", "203.0.113.11"], "10.8.0.2")

    script = scripts[0]
    assert script.count("New-NetFirewallRule -Name") == 2
    assert script.index("New-NetFirewallRule -Name") < script.index("Where-Object { $names -notcontains $_.Name }")
    assert "-PolicyStore ActiveStore" in script
    assert "-InterfaceType" not in script
    assert "-LocalAddress @(" in script
    assert "-RemotePort 53" not in script
    assert "10.8.0.2/32" not in script
    assert guard.prefix in script
    assert "203.0.113.10/32" not in script
    assert "203.0.113.11/32" not in script


def test_public_guard_status_requires_effective_rule_pair_and_profiles(
    monkeypatch, tmp_path: Path
) -> None:
    guard = windows_guard.WindowsPublicGuard(tmp_path)
    name = f"{guard.prefix}generation"
    state = {
        "present": 2,
        "profilesOk": True,
        "effective": [
            {"name": name + "-v4", "enabled": True, "block": True},
            {"name": name + "-v6", "enabled": True, "block": True},
        ],
    }

    def fake_run(_script: str, *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, json.dumps(state), "")

    monkeypatch.setattr(windows_guard, "run_powershell", fake_run)
    assert guard.status() == "active"
    state["effective"].pop()
    assert guard.status() == "invalid"
    state["effective"].append(
        {"name": name + "-v6", "enabled": True, "block": True}
    )
    state["profilesOk"] = False
    assert guard.status() == "invalid"
    state["present"] = 0
    assert guard.status() == "absent"


def test_public_guard_rejects_invalid_server_ip(tmp_path: Path) -> None:
    guard = windows_guard.WindowsPublicGuard(tmp_path)
    with pytest.raises(PlatformError, match="requires IPv4"):
        guard.enable(["vpn.example.com"])


@pytest.mark.skipif(__import__("os").name != "nt", reason="requires Windows PowerShell")
def test_public_guard_powershell_parses(monkeypatch, tmp_path: Path) -> None:
    scripts: list[str] = []
    def capture(script: str, **_kwargs) -> subprocess.CompletedProcess[str]:
        scripts.append(script)
        return subprocess.CompletedProcess(
            [], 0, '{"present":0,"profilesOk":true,"effective":[]}', ""
        )

    monkeypatch.setattr(windows_guard, "run_powershell", capture)
    guard = windows_guard.WindowsPublicGuard(tmp_path)
    guard.enable(["203.0.113.10"])
    guard.disable()
    assert guard.status() == "absent"
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
    for line in scripts[0].splitlines():
        if not line.strip().startswith("New-NetFirewallRule -Name"):
            continue
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", line.replace("| Out-Null", "-WhatIf")],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout
