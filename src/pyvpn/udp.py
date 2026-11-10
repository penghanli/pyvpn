"""UDP endpoint setup shared by the client and server."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable

UDP_SOCKET_BUFFER_BYTES = 4 * 1024 * 1024


def _tune_socket(sock: socket.socket) -> None:
    for option in (socket.SO_RCVBUF, socket.SO_SNDBUF):
        try:
            sock.setsockopt(socket.SOL_SOCKET, option, UDP_SOCKET_BUFFER_BYTES)
        except OSError:
            pass


async def create_udp_endpoint(
    protocol_factory: Callable[[], asyncio.DatagramProtocol],
    local_addr: tuple[str, int],
) -> tuple[asyncio.DatagramTransport, asyncio.DatagramProtocol]:
    family, kind, protocol, _, bind_addr = socket.getaddrinfo(
        *local_addr, type=socket.SOCK_DGRAM, flags=socket.AI_PASSIVE
    )[0]
    sock = socket.socket(family, kind, protocol)
    try:
        _tune_socket(sock)
        sock.bind(bind_addr)
        sock.setblocking(False)
        return await asyncio.get_running_loop().create_datagram_endpoint(
            protocol_factory, sock=sock
        )
    except BaseException:
        sock.close()
        raise
