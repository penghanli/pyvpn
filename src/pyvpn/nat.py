"""Linux server NAT and forwarding management."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import PlatformError
from .system import command_exists, run


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _write_text(path: str, value: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(value)


def detect_default_interface() -> str:
    result = run(["ip", "route", "show", "default"])
    for line in result.stdout.splitlines():
        parts = line.split()
        if "dev" in parts:
            return parts[parts.index("dev") + 1]
    raise PlatformError("could not detect default network interface")


@dataclass
class LinuxNatManager:
    subnet: str
    external_interface: str | None = None
    table_name: str = "pyvpn"

    _ip_forward_before: str | None = None
    _mode: str | None = None
    _iface: str | None = None

    def enable(self) -> None:
        iface = self.external_interface or detect_default_interface()
        self._iface = iface
        self._ip_forward_before = _read_text("/proc/sys/net/ipv4/ip_forward").strip()
        if self._ip_forward_before != "1":
            _write_text("/proc/sys/net/ipv4/ip_forward", "1\n")

        if command_exists("nft"):
            self._enable_nft(iface)
            self._mode = "nft"
            return

        if command_exists("iptables"):
            run(
                [
                    "iptables",
                    "-t",
                    "nat",
                    "-A",
                    "POSTROUTING",
                    "-s",
                    self.subnet,
                    "-o",
                    iface,
                    "-j",
                    "MASQUERADE",
                ]
            )
            self._mode = "iptables"
            return

        raise PlatformError("neither nft nor iptables is available for NAT")

    def _enable_nft(self, iface: str) -> None:
        run(["nft", "delete", "table", "ip", self.table_name], check=False)
        script = f"""
table ip {self.table_name} {{
  chain postrouting {{
    type nat hook postrouting priority srcnat; policy accept;
    ip saddr {self.subnet} oifname "{iface}" masquerade
  }}
}}
"""
        run(["nft", "-f", "-"], input_text=script)

    def cleanup(self) -> None:
        if self._mode == "nft":
            run(["nft", "delete", "table", "ip", self.table_name], check=False)
        elif self._mode == "iptables":
            iface = self._iface or self.external_interface or detect_default_interface()
            run(
                [
                    "iptables",
                    "-t",
                    "nat",
                    "-D",
                    "POSTROUTING",
                    "-s",
                    self.subnet,
                    "-o",
                    iface,
                    "-j",
                    "MASQUERADE",
                ],
                check=False,
            )
        if self._ip_forward_before is not None:
            _write_text("/proc/sys/net/ipv4/ip_forward", self._ip_forward_before + "\n")
