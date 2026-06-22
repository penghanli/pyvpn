"""TUN device adapters."""

from __future__ import annotations

import asyncio
import os
import platform
import struct
from dataclasses import dataclass

from .errors import PlatformError
from .system import run

TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000


class TunDevice:
    name: str
    mtu: int

    async def read(self) -> bytes:
        raise NotImplementedError

    async def write(self, packet: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


@dataclass
class LinuxTunDevice(TunDevice):
    name: str
    fd: int
    mtu: int

    @classmethod
    def create(cls, name: str, mtu: int) -> "LinuxTunDevice":
        if platform.system() != "Linux":
            raise PlatformError("Linux TUN is only available on Linux")
        import fcntl

        fd = os.open("/dev/net/tun", os.O_RDWR | os.O_NONBLOCK)
        ifr = struct.pack("16sH", name.encode("ascii"), IFF_TUN | IFF_NO_PI)
        result = fcntl.ioctl(fd, TUNSETIFF, ifr)
        actual_name = result[:16].split(b"\x00", 1)[0].decode("ascii")
        return cls(name=actual_name, fd=fd, mtu=mtu)

    def configure_server(self, address: str, prefix_len: int) -> None:
        run(["ip", "addr", "flush", "dev", self.name], check=False)
        run(["ip", "addr", "add", f"{address}/{prefix_len}", "dev", self.name])
        run(["ip", "link", "set", "dev", self.name, "mtu", str(self.mtu), "up"])

    def configure_client(self, address: str, peer: str) -> None:
        run(["ip", "addr", "flush", "dev", self.name], check=False)
        run(["ip", "addr", "add", f"{address}/32", "peer", peer, "dev", self.name])
        run(["ip", "link", "set", "dev", self.name, "mtu", str(self.mtu), "up"])

    async def read(self) -> bytes:
        loop = asyncio.get_running_loop()
        while True:
            try:
                return os.read(self.fd, self.mtu + 128)
            except BlockingIOError:
                future = loop.create_future()

                def _ready() -> None:
                    if not future.done():
                        future.set_result(None)

                loop.add_reader(self.fd, _ready)
                try:
                    await future
                finally:
                    loop.remove_reader(self.fd)

    async def write(self, packet: bytes) -> None:
        loop = asyncio.get_running_loop()
        view = memoryview(packet)
        while view:
            try:
                written = os.write(self.fd, view)
                view = view[written:]
            except BlockingIOError:
                future = loop.create_future()

                def _ready() -> None:
                    if not future.done():
                        future.set_result(None)

                loop.add_writer(self.fd, _ready)
                try:
                    await future
                finally:
                    loop.remove_writer(self.fd)

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass


def create_tun(name: str, mtu: int) -> TunDevice:
    if platform.system() == "Linux":
        return LinuxTunDevice.create(name, mtu)
    if platform.system() == "Windows":
        raise PlatformError(
            "Windows client requires a Wintun adapter binding; this v1 package "
            "includes the protocol/runtime but not the Wintun ctypes wrapper yet."
        )
    if platform.system() == "Darwin":
        raise PlatformError(
            "macOS system VPN must run through NetworkExtension; see macos/."
        )
    raise PlatformError(f"unsupported platform: {platform.system()}")
