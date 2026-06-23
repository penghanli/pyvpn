"""Client-side route and DNS management."""

from __future__ import annotations

import ipaddress
import json
import shlex
import socket
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PlatformError
from .system import command_exists, run
from .system import run_powershell


def resolve_ipv4(host: str) -> str:
    try:
        return str(ipaddress.IPv4Address(host))
    except ipaddress.AddressValueError:
        return socket.gethostbyname(host)


MANAGEMENT_TABLE = "51820"
MANAGEMENT_RULE_PRIORITY = "100"


@dataclass(frozen=True)
class RouteInfo:
    via: str | None
    dev: str | None
    src: str | None


def _route_get(ip: str) -> RouteInfo:
    result = run(["ip", "route", "get", ip])
    parts = result.stdout.split()
    via = parts[parts.index("via") + 1] if "via" in parts else None
    dev = parts[parts.index("dev") + 1] if "dev" in parts else None
    src = parts[parts.index("src") + 1] if "src" in parts else None
    return RouteInfo(via=via, dev=dev, src=src)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _mac_default_route() -> RouteInfo:
    result = run(["route", "-n", "get", "default"])
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values = value.strip().split()
        if values:
            fields[key.strip()] = values[0]
    return RouteInfo(
        via=fields.get("gateway"),
        dev=fields.get("interface"),
        src=fields.get("ifscope"),
    )


def _mac_service_for_device(device: str) -> str | None:
    if not command_exists("networksetup"):
        return None
    result = run(["networksetup", "-listallhardwareports"], check=False)
    if result.returncode != 0:
        return None
    current_service: str | None = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Hardware Port: "):
            current_service = line.split(": ", 1)[1]
        elif line.startswith("Device: ") and line.split(": ", 1)[1] == device:
            return current_service
    return None


@dataclass
class LinuxDnsManager:
    interface: str
    dns: str
    manage_dns: bool = True
    used_resolvectl: bool = False
    resolv_conf_backup: str | None = None
    resolv_conf_path: Path = Path("/etc/resolv.conf")

    def setup(self) -> None:
        if not self.manage_dns:
            return
        if command_exists("resolvectl"):
            dns_result = run(["resolvectl", "dns", self.interface, self.dns], check=False)
            domain_result = run(["resolvectl", "domain", self.interface, "~."], check=False)
            if dns_result.returncode == 0 and domain_result.returncode == 0:
                self.used_resolvectl = True
                return

        self.resolv_conf_backup = self.resolv_conf_path.read_text(encoding="utf-8")
        self.resolv_conf_path.write_text(
            f"# Managed by pyvpn. Restored on client shutdown.\nnameserver {self.dns}\n",
            encoding="utf-8",
        )

    def cleanup(self) -> None:
        if not self.manage_dns:
            return
        if self.used_resolvectl:
            run(["resolvectl", "revert", self.interface], check=False)
            return
        if self.resolv_conf_backup is not None:
            self.resolv_conf_path.write_text(self.resolv_conf_backup, encoding="utf-8")


@dataclass
class LinuxClientNetwork:
    tun_name: str
    server_ips: list[str]
    gateway: str
    dns: str
    manage_dns: bool = True
    default_routes: list[str] = field(default_factory=list)
    bypassed_ips: list[str] = field(default_factory=list)
    dns_manager: LinuxDnsManager | None = None
    management_src: str | None = None

    def setup(self) -> None:
        self.default_routes = run(["ip", "route", "show", "default"]).stdout.splitlines()
        if not self.server_ips:
            raise PlatformError("no server route targets configured")

        default_route = _route_get(self.server_ips[0])
        if default_route.dev is None:
            raise PlatformError(f"could not determine route to server {self.server_ips[0]}")
        self._setup_management_policy(default_route)

        for server_ip in dict.fromkeys(self.server_ips):
            route = _route_get(server_ip)
            if route.dev is None:
                raise PlatformError(f"could not determine route to server {server_ip}")

            command = ["ip", "route", "replace", f"{server_ip}/32"]
            if route.via:
                command.extend(["via", route.via])
            command.extend(["dev", route.dev])
            run(command)
            self.bypassed_ips.append(server_ip)

        run(["ip", "route", "replace", "default", "via", self.gateway, "dev", self.tun_name])
        self.dns_manager = LinuxDnsManager(self.tun_name, self.dns, self.manage_dns)
        self.dns_manager.setup()

    def _setup_management_policy(self, route: RouteInfo) -> None:
        if route.dev is None or route.src is None:
            return

        self.management_src = route.src
        run(
            [
                "ip",
                "rule",
                "del",
                "priority",
                MANAGEMENT_RULE_PRIORITY,
                "from",
                f"{route.src}/32",
                "table",
                MANAGEMENT_TABLE,
            ],
            check=False,
        )
        run(["ip", "route", "flush", "table", MANAGEMENT_TABLE], check=False)

        command = ["ip", "route", "replace", "default"]
        if route.via:
            command.extend(["via", route.via])
        command.extend(["dev", route.dev, "table", MANAGEMENT_TABLE])
        run(command)
        run(
            [
                "ip",
                "rule",
                "add",
                "priority",
                MANAGEMENT_RULE_PRIORITY,
                "from",
                f"{route.src}/32",
                "table",
                MANAGEMENT_TABLE,
            ]
        )
        run(["ip", "route", "flush", "cache"], check=False)

    def cleanup(self) -> None:
        if self.dns_manager is not None:
            self.dns_manager.cleanup()

        if self.management_src is not None:
            run(
                [
                    "ip",
                    "rule",
                    "del",
                    "priority",
                    MANAGEMENT_RULE_PRIORITY,
                    "from",
                    f"{self.management_src}/32",
                    "table",
                    MANAGEMENT_TABLE,
                ],
                check=False,
            )
            run(["ip", "route", "flush", "table", MANAGEMENT_TABLE], check=False)

        run(["ip", "route", "del", "default", "dev", self.tun_name], check=False)

        for route in self.default_routes:
            if route.strip():
                run(["ip", "route", "replace", *shlex.split(route)], check=False)

        for server_ip in self.bypassed_ips:
            run(["ip", "route", "del", f"{server_ip}/32"], check=False)


@dataclass
class MacDnsManager:
    interface: str
    dns: str
    manage_dns: bool = True
    state_path: Path = Path("/var/run/pyvpn/macos-dns-state.json")
    service: str | None = None
    previous_dns: list[str] | None = None

    def setup(self) -> None:
        if not self.manage_dns:
            return
        self.service = _mac_service_for_device(self.interface)
        if not self.service:
            return
        result = run(["networksetup", "-getdnsservers", self.service], check=False)
        self.previous_dns = []
        if result.returncode == 0:
            lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if lines and not lines[0].startswith("There aren't any DNS Servers"):
                self.previous_dns = lines
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"service": self.service, "dns": self.previous_dns}),
            encoding="utf-8",
        )
        run(["networksetup", "-setdnsservers", self.service, self.dns])

    def cleanup(self) -> None:
        if not self.manage_dns:
            return
        service = self.service
        previous_dns = self.previous_dns
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                service = str(state.get("service") or service or "")
                dns_value = state.get("dns")
                if isinstance(dns_value, list):
                    previous_dns = [str(item) for item in dns_value]
            except (OSError, json.JSONDecodeError):
                pass
        if service:
            if previous_dns:
                run(["networksetup", "-setdnsservers", service, *previous_dns], check=False)
            else:
                run(["networksetup", "-setdnsservers", service, "Empty"], check=False)
        try:
            self.state_path.unlink()
        except OSError:
            pass


@dataclass
class MacClientNetwork:
    tun_name: str
    server_ips: list[str]
    gateway: str
    dns: str
    manage_dns: bool = True
    bypassed_ips: list[str] = field(default_factory=list)
    dns_manager: MacDnsManager | None = None
    default_gateway: str | None = None
    default_interface: str | None = None

    def setup(self) -> None:
        if not self.server_ips:
            raise PlatformError("no server route targets configured")

        default_route = _mac_default_route()
        self.default_gateway = default_route.via
        self.default_interface = default_route.dev
        if self.default_gateway is None and self.default_interface is None:
            raise PlatformError("could not determine the current macOS default route")

        for server_ip in dict.fromkeys(self.server_ips):
            run(["route", "-n", "delete", "-host", server_ip], check=False)
            if self.default_gateway:
                run(["route", "-n", "add", "-host", server_ip, self.default_gateway])
            else:
                run(
                    [
                        "route",
                        "-n",
                        "add",
                        "-host",
                        server_ip,
                        "-interface",
                        str(self.default_interface),
                    ]
                )
            self.bypassed_ips.append(server_ip)

        for network in ("0.0.0.0", "128.0.0.0"):
            run(
                ["route", "-n", "delete", "-net", network, "-netmask", "128.0.0.0"],
                check=False,
            )
            run(
                [
                    "route",
                    "-n",
                    "add",
                    "-net",
                    network,
                    "-netmask",
                    "128.0.0.0",
                    self.gateway,
                ]
            )

        dns_interface = self.default_interface or self.tun_name
        self.dns_manager = MacDnsManager(dns_interface, self.dns, self.manage_dns)
        self.dns_manager.setup()

    def cleanup(self) -> None:
        if self.dns_manager is not None:
            self.dns_manager.cleanup()

        for network in ("0.0.0.0", "128.0.0.0"):
            run(
                ["route", "-n", "delete", "-net", network, "-netmask", "128.0.0.0"],
                check=False,
            )

        for server_ip in self.bypassed_ips:
            run(["route", "-n", "delete", "-host", server_ip], check=False)


@dataclass
class WindowsClientNetwork:
    tun_name: str
    server_ips: list[str]
    gateway: str
    dns: str
    manage_dns: bool = True

    def setup(self) -> None:
        unique_server_ips = list(dict.fromkeys(self.server_ips))
        server_ips_ps = "@(" + ",".join(_ps_quote(ip) for ip in unique_server_ips) + ")"
        dns_script = ""
        if self.manage_dns:
            dns_script = (
                f"Set-DnsClientServerAddress -InterfaceAlias $tunName "
                f"-ServerAddresses @({_ps_quote(self.dns)}) -ErrorAction Stop"
            )

        script = f"""
$ErrorActionPreference = 'Stop'
$tunName = {_ps_quote(self.tun_name)}
$gateway = {_ps_quote(self.gateway)}
$serverIps = {server_ips_ps}
$tun = Get-NetAdapter -Name $tunName -ErrorAction Stop
$default = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
  Where-Object {{ $_.NextHop -ne '0.0.0.0' }} |
  Sort-Object RouteMetric, InterfaceMetric |
  Select-Object -First 1
if (-not $default) {{ throw 'Could not find the current IPv4 default route' }}

foreach ($ip in $serverIps) {{
  Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "$ip/32" -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
  New-NetRoute -DestinationPrefix "$ip/32" -InterfaceIndex $default.InterfaceIndex `
    -NextHop $default.NextHop -RouteMetric 1 -PolicyStore ActiveStore -ErrorAction Stop | Out-Null
}}

foreach ($prefix in @('0.0.0.0/1', '128.0.0.0/1')) {{
  Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -InterfaceIndex $tun.ifIndex `
    -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
  New-NetRoute -DestinationPrefix $prefix -InterfaceIndex $tun.ifIndex -NextHop $gateway `
    -RouteMetric 1 -PolicyStore ActiveStore -ErrorAction Stop | Out-Null
}}

{dns_script}
"""
        run_powershell(script)

    def cleanup(self) -> None:
        unique_server_ips = list(dict.fromkeys(self.server_ips))
        server_ips_ps = "@(" + ",".join(_ps_quote(ip) for ip in unique_server_ips) + ")"
        script = f"""
$tunName = {_ps_quote(self.tun_name)}
$serverIps = {server_ips_ps}
$tun = Get-NetAdapter -Name $tunName -ErrorAction SilentlyContinue
if ($tun) {{
  foreach ($prefix in @('0.0.0.0/1', '128.0.0.0/1')) {{
    Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -InterfaceIndex $tun.ifIndex `
      -ErrorAction SilentlyContinue |
      Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
  }}
  Set-DnsClientServerAddress -InterfaceAlias $tunName -ResetServerAddresses `
    -ErrorAction SilentlyContinue
}}
foreach ($ip in $serverIps) {{
  Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "$ip/32" -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
}}
"""
        run_powershell(script, check=False)
