from __future__ import annotations

import asyncio
import ctypes
from pathlib import Path

from pyvpn import tun


def test_wintun_batches_reads_without_losing_single_read_packets(monkeypatch) -> None:
    class FakeDll:
        def __init__(self) -> None:
            self.packets = [bytes([index]) for index in range(80)]
            self.buffers: list[ctypes.Array] = []

        def WintunReceivePacket(self, _session, size_ptr):
            if not self.packets:
                return 0
            packet = self.packets.pop(0)
            buffer = ctypes.create_string_buffer(packet)
            self.buffers.append(buffer)
            ctypes.cast(size_ptr, ctypes.POINTER(ctypes.c_uint32)).contents.value = len(packet)
            return ctypes.addressof(buffer)

        def WintunReleaseReceivePacket(self, _session, _packet) -> None:
            pass

    class FakeApi:
        def __init__(self) -> None:
            self.dll = FakeDll()

    monkeypatch.setattr(
        tun.ctypes, "get_last_error", lambda: tun.ERROR_NO_MORE_ITEMS, raising=False
    )
    api = FakeApi()
    device = tun.WindowsTunDevice("pyvpn0", api, adapter=1, session=2, mtu=1280)

    async def scenario() -> list[bytes]:
        first = await device.read()
        second = await device.read_batch()
        third = await device.read_batch()
        return [first, *second, *third]

    assert asyncio.run(scenario()) == [bytes([index]) for index in range(80)]


def test_wintun_ring_capacity_falls_back_for_older_machines(monkeypatch) -> None:
    class FakeDll:
        capacities: list[int] = []

        def WintunOpenAdapter(self, _name: str) -> int:
            return 1

        def WintunStartSession(self, _adapter: int, capacity: int) -> int:
            self.capacities.append(capacity)
            return 0 if capacity == tun.WINTUN_RING_CAPACITY else 2

    class FakeApi:
        def __init__(self) -> None:
            self.dll = FakeDll()

    api = FakeApi()
    monkeypatch.setattr(tun, "_WintunApi", lambda _path: api)
    monkeypatch.setattr(tun, "_find_wintun_dll", lambda: Path("wintun.dll"))
    device = tun.WindowsTunDevice.create("pyvpn0", 1280)

    assert device.session == 2
    assert api.dll.capacities == [tun.WINTUN_RING_CAPACITY, tun.WINTUN_FALLBACK_RING_CAPACITY]
