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


def _route_get(ip: str) -> tuple[str | None, str | None]:
    result = run(["ip", "route", "get", ip])
    parts = result.stdout.split()
    via = parts[parts.index("via") + 1] if "via" in parts else None
    dev = parts[parts.index("dev") + 1] if "dev" in parts else None
    return via, dev


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

    def setup(self) -> None:
        self.default_routes = run(["ip", "route", "show", "default"]).stdout.splitlines()
        for server_ip in dict.fromkeys(self.server_ips):
            via, dev = _route_get(server_ip)
            if dev is None:
                raise PlatformError(f"could not determine route to server {server_ip}")

            command = ["ip", "route", "replace", f"{server_ip}/32"]
            if via:
                command.extend(["via", via])
            command.extend(["dev", dev])
            run(command)
            self.bypassed_ips.append(server_ip)

        run(["ip", "route", "replace", "default", "via", self.gateway, "dev", self.tun_name])
        self.dns_manager = LinuxDnsManager(self.tun_name, self.dns, self.manage_dns)
        self.dns_manager.setup()

    def cleanup(self) -> None:
        if self.dns_manager is not None:
            self.dns_manager.cleanup()

        run(["ip", "route", "del", "default", "dev", self.tun_name], check=False)

        for route in self.default_routes:
            if route.strip():
                run(["ip", "route", "replace", *shlex.split(route)], check=False)

        for server_ip in self.bypassed_ips:
            run(["ip", "route", "del", f"{server_ip}/32"], check=False)
