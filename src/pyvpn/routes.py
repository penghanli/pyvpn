"""Client-side route and DNS management."""

from __future__ import annotations

import ipaddress
import shlex
import socket
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PlatformError
from .system import command_exists, run


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
