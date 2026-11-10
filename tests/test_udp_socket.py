from __future__ import annotations

import asyncio
import socket

import pytest

from pyvpn.udp import UDP_SOCKET_BUFFER_BYTES, _tune_socket, create_udp_endpoint


def test_udp_buffer_tuning_is_best_effort() -> None:
    class FakeSocket:
        options: list[tuple[int, int, int]] = []

        def setsockopt(self, level: int, option: int, size: int) -> None:
            self.options.append((level, option, size))
            if option == socket.SO_RCVBUF:
                raise OSError("buffer size is capped")

    fake = FakeSocket()
    _tune_socket(fake)
    assert fake.options == [
        (socket.SOL_SOCKET, socket.SO_RCVBUF, UDP_SOCKET_BUFFER_BYTES),
        (socket.SOL_SOCKET, socket.SO_SNDBUF, UDP_SOCKET_BUFFER_BYTES),
    ]


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_udp_endpoint_receives_loopback_packet(host: str) -> None:
    if host == "::1":
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as probe:
                probe.bind((host, 0))
        except OSError:
            pytest.skip("IPv6 loopback is unavailable")

    async def scenario() -> None:
        received = asyncio.Event()

        class Receiver(asyncio.DatagramProtocol):
            def datagram_received(self, data: bytes, _addr) -> None:
                if data == b"probe":
                    received.set()

        transport, _ = await create_udp_endpoint(Receiver, (host, 0))
        bound_socket = transport.get_extra_info("socket")
        sender = socket.socket(bound_socket.family, socket.SOCK_DGRAM)
        try:
            sender.sendto(b"probe", bound_socket.getsockname())
            await asyncio.wait_for(received.wait(), timeout=2)
        finally:
            sender.close()
            transport.close()

    asyncio.run(scenario())
