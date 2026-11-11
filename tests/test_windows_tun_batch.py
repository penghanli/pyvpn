from __future__ import annotations

import asyncio
import ctypes
import threading
from pathlib import Path

import pytest

from pyvpn import tun
from pyvpn.errors import TunnelUnavailableError


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


def test_wintun_batches_writes_in_order_and_retries_transient_full_ring(monkeypatch) -> None:
    class FakeDll:
        def __init__(self) -> None:
            self.attempts = 0
            self.buffers: list[ctypes.Array] = []
            self.sent: list[bytes] = []

        def WintunAllocateSendPacket(self, _session, packet_size: int) -> int:
            self.attempts += 1
            if self.attempts == 1:
                return 0
            buffer = ctypes.create_string_buffer(packet_size)
            self.buffers.append(buffer)
            return ctypes.addressof(buffer)

        def WintunSendPacket(self, _session, packet: int) -> None:
            self.sent.append(ctypes.string_at(packet, 1))

    class FakeApi:
        def __init__(self) -> None:
            self.dll = FakeDll()

    monkeypatch.setattr(tun.ctypes, "get_last_error", lambda: tun.ERROR_BUFFER_OVERFLOW, raising=False)
    api = FakeApi()
    device = tun.WindowsTunDevice("pyvpn0", api, adapter=1, session=2, mtu=1280)
    asyncio.run(device.write_batch([b"a", b"b", b"c"]))
    assert api.dll.attempts == 4
    assert api.dll.sent == [b"a", b"b", b"c"]


def test_wintun_persistent_full_ring_requests_reconnect(monkeypatch) -> None:
    class FakeDll:
        def WintunAllocateSendPacket(self, _session, _packet_size: int) -> int:
            return 0

    class FakeApi:
        dll = FakeDll()

    monkeypatch.setattr(tun.ctypes, "get_last_error", lambda: tun.ERROR_BUFFER_OVERFLOW, raising=False)
    monkeypatch.setattr(tun, "WINTUN_SEND_RETRY_TIMEOUT", 0.0)
    device = tun.WindowsTunDevice("pyvpn0", FakeApi(), adapter=1, session=2, mtu=1280)
    with pytest.raises(TunnelUnavailableError, match="send ring stayed full"):
        asyncio.run(device.write_batch([b"packet"]))


def test_wintun_close_waits_for_active_io() -> None:
    class FakeDll:
        def __init__(self) -> None:
            self.closed: list[str] = []

        def WintunEndSession(self, _session: int) -> None:
            self.closed.append("session")

        def WintunCloseAdapter(self, _adapter: int) -> None:
            self.closed.append("adapter")

    class FakeApi:
        def __init__(self) -> None:
            self.dll = FakeDll()

    api = FakeApi()
    device = tun.WindowsTunDevice("pyvpn0", api, adapter=1, session=2, mtu=1280)
    device._begin_io()
    finished = threading.Event()

    def close() -> None:
        device.close()
        finished.set()

    worker = threading.Thread(target=close)
    worker.start()
    try:
        with device._io_condition:
            assert device._io_condition.wait_for(lambda: device._closing, timeout=2)
        assert not finished.is_set()
        assert api.dll.closed == []
    finally:
        device._end_io()
        worker.join(timeout=2)

    assert finished.is_set()
    assert api.dll.closed == ["session", "adapter"]
    with pytest.raises(TunnelUnavailableError, match="terminating"):
        device._begin_io()
