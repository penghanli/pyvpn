from __future__ import annotations

import asyncio
import ipaddress
from types import SimpleNamespace

from pyvpn.client import VpnClient
from pyvpn.server import VpnServer


def _packet() -> bytes:
    header = bytearray(20)
    header[0] = 0x45
    header[2:4] = (20).to_bytes(2, "big")
    header[8] = 64
    header[9] = 6
    header[12:16] = ipaddress.IPv4Address("10.8.0.2").packed
    header[16:20] = ipaddress.IPv4Address("1.1.1.1").packed
    return bytes(header)


def test_client_tun_flood_does_not_starve_other_tasks() -> None:
    async def scenario() -> None:
        tick = asyncio.Event()
        packet = _packet()
        loop = asyncio.get_running_loop()

        class BusyTun:
            count = 0

            async def read_batch(self) -> list[bytes]:
                self.count += 1
                if self.count == 1:
                    loop.call_soon(tick.set)
                if self.count == 200 and not tick.is_set():
                    raise AssertionError("client TUN loop starved the event loop")
                if self.count >= 200:
                    await asyncio.Future()
                return [packet]

        client = object.__new__(VpnClient)
        client.tun = BusyTun()
        client.session = SimpleNamespace(client_vip="10.8.0.2")
        client._send_udp = lambda *_args: None
        task = asyncio.create_task(client.tun_to_udp_loop())
        await asyncio.wait_for(tick.wait(), timeout=1)
        await asyncio.sleep(0)
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert client.tun.count >= 64

    asyncio.run(scenario())


def test_server_tun_flood_does_not_starve_other_tasks() -> None:
    async def scenario() -> None:
        tick = asyncio.Event()
        packet = _packet()
        loop = asyncio.get_running_loop()

        class BusyTun:
            count = 0

            async def read(self) -> bytes:
                self.count += 1
                if self.count == 1:
                    loop.call_soon(tick.set)
                if self.count == 200 and not tick.is_set():
                    raise AssertionError("server TUN loop starved the event loop")
                if self.count >= 200:
                    await asyncio.Future()
                return packet

        server = object.__new__(VpnServer)
        server.tun = BusyTun()
        server.sessions_by_vip = {
            ipaddress.IPv4Address("1.1.1.1"): SimpleNamespace(client_addr=("127.0.0.1", 1234))
        }
        server._send_udp = lambda *_args: None
        task = asyncio.create_task(server.tun_to_udp_loop())
        await asyncio.wait_for(tick.wait(), timeout=1)
        await asyncio.sleep(0)
        task.cancel()
        result = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert server.tun.count >= 64

    asyncio.run(scenario())
