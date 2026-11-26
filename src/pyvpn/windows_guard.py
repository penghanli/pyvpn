"""Persistent Windows Firewall guard for the portable GUI client."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import uuid
from pathlib import Path

from .errors import PlatformError
from .system import run_powershell


_LOCAL_V4 = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "224.0.0.0/4",
    "255.255.255.255/32",
)
_LOCAL_V6 = ("::1/128", "fc00::/7", "fe80::/10", "ff00::/8")


def _blocked_networks(version: int, exceptions: list[str]) -> list[str]:
    base = ipaddress.ip_network("0.0.0.0/0" if version == 4 else "::/0")
    allowed = list(ipaddress.collapse_addresses(ipaddress.ip_network(value) for value in exceptions))
    blocked = [base]
    for exception in allowed:
        next_blocked = []
        for network in blocked:
            if not network.overlaps(exception):
                next_blocked.append(network)
            elif network.subnet_of(exception):
                continue
            elif exception.subnet_of(network):
                next_blocked.extend(network.address_exclude(exception))
        blocked = next_blocked
    return [str(network) for network in blocked]


def _ps_array(values: list[str]) -> str:
    return "@(" + ",".join("'" + value + "'" for value in values) + ")"


class WindowsPublicGuard:
    def __init__(self, data_dir: Path):
        digest = hashlib.sha256(str(data_dir.resolve()).lower().encode("utf-8")).hexdigest()[:16]
        self.prefix = f"pyvpn-public-guard-{digest}-"

    def status(self) -> str:
        result = run_powershell(
            f"""
$ErrorActionPreference = 'Stop'
$profiles = @(Get-NetFirewallProfile -ErrorAction Stop)
$profilesOk = $profiles.Count -eq 3 -and @($profiles | Where-Object {{
  $_.Enabled -ne $true -or $_.AllowLocalFirewallRules -eq $false
}}).Count -eq 0
$present = @(Get-NetFirewallRule -PolicyStore PersistentStore -Name '{self.prefix}*' `
  -ErrorAction SilentlyContinue)
$effective = @(Get-NetFirewallRule -PolicyStore ActiveStore -Name '{self.prefix}*' `
  -ErrorAction SilentlyContinue | ForEach-Object {{
    [pscustomobject]@{{name=$_.Name; enabled=($_.Enabled -eq 'True'); block=($_.Action -eq 'Block')}}
  }})
[pscustomobject]@{{present=$present.Count; profilesOk=$profilesOk; effective=$effective}} |
  ConvertTo-Json -Compress -Depth 3
""",
            timeout=15,
        )
        try:
            state = json.loads(result.stdout)
            present = state["present"]
            profiles_ok = state["profilesOk"]
            effective = state["effective"] or []
            if isinstance(effective, dict):
                effective = [effective]
        except (ValueError, KeyError, TypeError) as exc:
            raise PlatformError("could not inspect public guard rules") from exc
        if not present:
            return "absent"
        if not profiles_ok:
            return "invalid"
        if not isinstance(effective, list):
            return "invalid"
        generations: dict[str, set[str]] = {}
        for rule in effective:
            if not isinstance(rule, dict):
                return "invalid"
            name = str(rule.get("name", ""))
            if not name.startswith(self.prefix) or not rule.get("enabled") or not rule.get("block"):
                continue
            suffix = name[len(self.prefix) :]
            generation, separator, family = suffix.partition("-")
            if separator and family in {"v4", "v6"}:
                generations.setdefault(generation, set()).add(family)
        return "active" if {"v4", "v6"} in generations.values() else "invalid"

    def active(self) -> bool:
        return self.status() == "active"

    def enable(self, server_ips: list[str], tunnel_vip: str | None = None) -> None:
        if not server_ips:
            raise PlatformError("no server IPv4 address for the public network guard")
        try:
            permitted = [str(ipaddress.IPv4Address(ip)) + "/32" for ip in server_ips]
        except ipaddress.AddressValueError as exc:
            raise PlatformError("the public network guard requires IPv4 server addresses") from exc
        blocked_v4 = _blocked_networks(4, [*_LOCAL_V4, *permitted])
        blocked_v6 = _blocked_networks(6, list(_LOCAL_V6))
        local_v4 = ["0.0.0.0/0"]
        if tunnel_vip:
            try:
                local_v4 = _blocked_networks(4, [str(ipaddress.IPv4Address(tunnel_vip)) + "/32"])
            except ipaddress.AddressValueError as exc:
                raise PlatformError("the public network guard requires an IPv4 tunnel address") from exc
        generation = uuid.uuid4().hex[:12]
        names = [f"{self.prefix}{generation}-v4", f"{self.prefix}{generation}-v6"]
        rules = []
        for family, remote, local in ((4, blocked_v4, local_v4), (6, blocked_v6, ["::/0"])):
            name = f"{self.prefix}{generation}-v{family}"
            rules.append(
                f"New-NetFirewallRule -Name '{name}' -DisplayName 'pyvpn public guard IPv{family}' "
                f"-Group 'pyvpn public guard' -Direction Outbound -Action Block -Profile Any "
                f"-LocalAddress {_ps_array(local)} -RemoteAddress {_ps_array(remote)} "
                "-PolicyStore PersistentStore -ErrorAction Stop | Out-Null"
            )
        names_ps = _ps_array(names)
        script = f"""
$ErrorActionPreference = 'Stop'
$profiles = @(Get-NetFirewallProfile -ErrorAction Stop)
if ($profiles.Count -ne 3 -or @($profiles | Where-Object {{
  $_.Enabled -ne $true -or $_.AllowLocalFirewallRules -eq $false
}}).Count -gt 0) {{ throw 'Windows Firewall must be enabled and local rules allowed on every profile' }}
try {{
  {chr(10).join(rules)}
  $names = {names_ps}
  $effective = @(Get-NetFirewallRule -PolicyStore ActiveStore -Name '{self.prefix}{generation}-*' -ErrorAction Stop)
  if ($effective.Count -ne 2 -or @($effective | Where-Object {{
    $_.Enabled -ne 'True' -or $_.Action -ne 'Block'
  }}).Count -gt 0) {{
    throw 'public guard rules are not active'
  }}
  Get-NetFirewallRule -PolicyStore PersistentStore -Name '{self.prefix}*' -ErrorAction SilentlyContinue |
    Where-Object {{ $names -notcontains $_.Name }} |
    Remove-NetFirewallRule -ErrorAction Stop
}} catch {{
  Get-NetFirewallRule -PolicyStore PersistentStore -Name '{self.prefix}{generation}-*' -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue
  throw
}}
"""
        run_powershell(script, timeout=35)

    def disable(self) -> None:
        script = f"""
$ErrorActionPreference = 'Stop'
Get-NetFirewallRule -PolicyStore PersistentStore -Name '{self.prefix}*' -ErrorAction SilentlyContinue |
  Remove-NetFirewallRule -ErrorAction Stop
if (Get-NetFirewallRule -PolicyStore PersistentStore -Name '{self.prefix}*' -ErrorAction SilentlyContinue) {{
  throw 'could not remove all pyvpn public guard rules'
}}
"""
        run_powershell(script, timeout=20)
