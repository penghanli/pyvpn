"""TUN device adapters."""

from __future__ import annotations

import asyncio
import ctypes
import os
import platform
import socket
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import PlatformError
from .system import run, run_powershell

TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000
ERROR_NO_MORE_ITEMS = 259
ERROR_HANDLE_EOF = 38
ERROR_BUFFER_OVERFLOW = 111
INFINITE = 0xFFFFFFFF
PF_SYSTEM = 32
AF_SYSTEM = 32
AF_SYS_CONTROL = 2
SYSPROTO_CONTROL = 2
CTLIOCGINFO = 0xC0644E03
UTUN_CONTROL_NAME = b"com.apple.net.utun_control"
UTUN_OPT_IFNAME = 2


class TunDevice:
    name: str
    mtu: int

    async def read(self) -> bytes:
        raise NotImplementedError

    async def write(self, packet: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


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


class _WintunApi:
    def __init__(self, dll_path: Path):
        if platform.system() != "Windows":
            raise PlatformError("Wintun is only available on Windows")
        if not dll_path.exists():
            raise PlatformError(
                f"wintun.dll was not found at {dll_path}. Run scripts/windows/install-client.ps1 "
                "or set PYVPN_WINTUN_DLL to the downloaded DLL path."
            )

        self.dll = ctypes.WinDLL(str(dll_path), use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self) -> None:
        self.dll.WintunCreateAdapter.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
        ]
        self.dll.WintunCreateAdapter.restype = ctypes.c_void_p
        self.dll.WintunOpenAdapter.argtypes = [ctypes.c_wchar_p]
        self.dll.WintunOpenAdapter.restype = ctypes.c_void_p
        self.dll.WintunCloseAdapter.argtypes = [ctypes.c_void_p]
        self.dll.WintunCloseAdapter.restype = None
        self.dll.WintunStartSession.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.dll.WintunStartSession.restype = ctypes.c_void_p
        self.dll.WintunEndSession.argtypes = [ctypes.c_void_p]
        self.dll.WintunEndSession.restype = None
        self.dll.WintunGetReadWaitEvent.argtypes = [ctypes.c_void_p]
        self.dll.WintunGetReadWaitEvent.restype = ctypes.c_void_p
        self.dll.WintunReceivePacket.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self.dll.WintunReceivePacket.restype = ctypes.c_void_p
        self.dll.WintunReleaseReceivePacket.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.dll.WintunReleaseReceivePacket.restype = None
        self.dll.WintunAllocateSendPacket.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.dll.WintunAllocateSendPacket.restype = ctypes.c_void_p
        self.dll.WintunSendPacket.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.dll.WintunSendPacket.restype = None
        self.kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.kernel32.WaitForSingleObject.restype = ctypes.c_uint32


def _find_wintun_dll() -> Path:
    candidates: list[Path] = []
    env_path = os.environ.get("PYVPN_WINTUN_DLL")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path(sys.executable).with_name("wintun.dll"))
    candidates.append(Path.cwd() / "wintun.dll")
    candidates.append(Path(__file__).resolve().parent / "wintun.dll")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


@dataclass
class WindowsTunDevice(TunDevice):
    name: str
    api: _WintunApi
    adapter: int
    session: int
    mtu: int

    @classmethod
    def create(cls, name: str, mtu: int) -> "WindowsTunDevice":
        api = _WintunApi(_find_wintun_dll())
        adapter = api.dll.WintunOpenAdapter(name)
        if not adapter:
            adapter = api.dll.WintunCreateAdapter(name, "PyVpn", None)
        if not adapter:
            raise PlatformError(f"WintunCreateAdapter failed: {ctypes.get_last_error()}")

        session = api.dll.WintunStartSession(adapter, 0x400000)
        if not session:
            api.dll.WintunCloseAdapter(adapter)
            raise PlatformError(f"WintunStartSession failed: {ctypes.get_last_error()}")
        return cls(name=name, api=api, adapter=adapter, session=session, mtu=mtu)

    def configure_client(self, address: str, peer: str) -> None:
        script = f"""
$ErrorActionPreference = 'Stop'
$name = {_ps_quote(self.name)}
$ip = {_ps_quote(address)}
$mtu = {int(self.mtu)}
for ($i = 0; $i -lt 30; $i++) {{
  $adapter = Get-NetAdapter -Name $name -ErrorAction SilentlyContinue
  if ($adapter) {{ break }}
  Start-Sleep -Milliseconds 500
}}
if (-not $adapter) {{ throw "Wintun adapter '$name' did not appear" }}
Get-NetIPAddress -InterfaceAlias $name -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress -InterfaceAlias $name -IPAddress $ip -PrefixLength 24 -ErrorAction Stop | Out-Null
Set-NetIPInterface -InterfaceAlias $name -AddressFamily IPv4 -InterfaceMetric 1 -ErrorAction Stop
netsh interface ipv4 set subinterface $name mtu=$mtu store=active | Out-Null
"""
        run_powershell(script)

    async def read(self) -> bytes:
        return await asyncio.to_thread(self._read_sync)

    def _read_sync(self) -> bytes:
        packet_size = ctypes.c_uint32()
        while True:
            packet = self.api.dll.WintunReceivePacket(self.session, ctypes.byref(packet_size))
            if packet:
                try:
                    return ctypes.string_at(packet, packet_size.value)
                finally:
                    self.api.dll.WintunReleaseReceivePacket(self.session, packet)
            error = ctypes.get_last_error()
            if error == ERROR_NO_MORE_ITEMS:
                event = self.api.dll.WintunGetReadWaitEvent(self.session)
                self.api.kernel32.WaitForSingleObject(event, INFINITE)
                continue
            if error == ERROR_HANDLE_EOF:
                raise PlatformError("Wintun adapter is terminating")
            raise PlatformError(f"WintunReceivePacket failed: {error}")

    async def write(self, packet: bytes) -> None:
        await asyncio.to_thread(self._write_sync, packet)

    def _write_sync(self, packet: bytes) -> None:
        allocated = self.api.dll.WintunAllocateSendPacket(self.session, len(packet))
        if not allocated:
            error = ctypes.get_last_error()
            if error == ERROR_BUFFER_OVERFLOW:
                return
            raise PlatformError(f"WintunAllocateSendPacket failed: {error}")
        ctypes.memmove(allocated, packet, len(packet))
        self.api.dll.WintunSendPacket(self.session, allocated)

    def close(self) -> None:
        if self.session:
            self.api.dll.WintunEndSession(self.session)
            self.session = 0
        if self.adapter:
            self.api.dll.WintunCloseAdapter(self.adapter)
            self.adapter = 0


@dataclass
class MacUtunDevice(TunDevice):
    name: str
    sock: socket.socket
    mtu: int
    af_prefix: bytes = struct.pack("!I", socket.AF_INET)

    @classmethod
    def create(cls, name: str, mtu: int) -> "MacUtunDevice":
        if platform.system() != "Darwin":
            raise PlatformError("macOS utun is only available on macOS")
        import fcntl

        sock = socket.socket(PF_SYSTEM, socket.SOCK_DGRAM, SYSPROTO_CONTROL)
        try:
            ctl_name = UTUN_CONTROL_NAME + b"\x00" * (96 - len(UTUN_CONTROL_NAME))
            ctl_info = struct.pack("I96s", 0, ctl_name)
            result = fcntl.ioctl(sock.fileno(), CTLIOCGINFO, ctl_info)
            ctl_id = struct.unpack("I", result[:4])[0]
            unit = _utun_unit_from_name(name)
            sockaddr_ctl = struct.pack(
                "BBHII5I",
                32,
                AF_SYSTEM,
                AF_SYS_CONTROL,
                ctl_id,
                unit,
                0,
                0,
                0,
                0,
                0,
            )
            sock.connect(sockaddr_ctl)
            actual_name = sock.getsockopt(
                SYSPROTO_CONTROL,
                UTUN_OPT_IFNAME,
                64,
            ).split(b"\x00", 1)[0].decode("ascii")
            sock.setblocking(False)
            return cls(name=actual_name, sock=sock, mtu=mtu)
        except Exception:
            sock.close()
            raise

    def configure_client(self, address: str, peer: str) -> None:
        run(
            [
                "ifconfig",
                self.name,
                "inet",
                address,
                peer,
                "netmask",
                "255.255.255.255",
                "mtu",
                str(self.mtu),
                "up",
            ]
        )

    async def read(self) -> bytes:
        loop = asyncio.get_running_loop()
        fd = self.sock.fileno()
        while True:
            try:
                data = os.read(fd, self.mtu + 132)
                if len(data) <= 4:
                    continue
                if data[:4] != self.af_prefix:
                    continue
                return data[4:]
            except BlockingIOError:
                future = loop.create_future()

                def _ready() -> None:
                    if not future.done():
                        future.set_result(None)

                loop.add_reader(fd, _ready)
                try:
                    await future
                finally:
                    loop.remove_reader(fd)

    async def write(self, packet: bytes) -> None:
        loop = asyncio.get_running_loop()
        fd = self.sock.fileno()
        view = memoryview(self.af_prefix + packet)
        while view:
            try:
                written = os.write(fd, view)
                view = view[written:]
            except BlockingIOError:
                future = loop.create_future()

                def _ready() -> None:
                    if not future.done():
                        future.set_result(None)

                loop.add_writer(fd, _ready)
                try:
                    await future
                finally:
                    loop.remove_writer(fd)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _utun_unit_from_name(name: str) -> int:
    if name.startswith("utun") and name[4:].isdigit():
        return int(name[4:]) + 1
    return 0


def create_tun(name: str, mtu: int) -> TunDevice:
    if platform.system() == "Linux":
        return LinuxTunDevice.create(name, mtu)
    if platform.system() == "Windows":
        return WindowsTunDevice.create(name, mtu)
    if platform.system() == "Darwin":
        return MacUtunDevice.create(name, mtu)
    raise PlatformError(f"unsupported platform: {platform.system()}")
