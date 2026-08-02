from __future__ import annotations

import asyncio

from pyvpn.constants import CONTROL_VERSION
from pyvpn.framing import read_frame, write_frame
from pyvpn.server import ServerConfig, VpnServer


def _server_config(token: str) -> ServerConfig:
    return ServerConfig(
        listen_host="127.0.0.1",
        control_port=0,
        udp_port=8444,
        public_host="127.0.0.1",
        token=token,
        certfile="unused",
        keyfile="unused",
        tun_name="pyvpn0",
        subnet="10.8.0.0/24",
        server_vip="10.8.0.1",
        client_vip="10.8.0.2",
        dns="1.1.1.1",
        mtu=1280,
        external_interface=None,
        session_timeout=60,
        max_clients=5,
    )


async def _authenticate(server_token: str, client_token: str) -> dict[str, object]:
    vpn_server = VpnServer(_server_config(server_token))
    listener = await asyncio.start_server(vpn_server.handle_control, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        await write_frame(
            writer,
            {
                "type": "hello",
                "version": CONTROL_VERSION,
                "token": client_token,
                "client_id": "test-client",
                "mtu": 1280,
                "capabilities": ["ipv4"],
            },
        )
        response = await read_frame(reader)
        if response.get("type") == "accept":
            await write_frame(writer, {"type": "disconnect"})
            await read_frame(reader)
        writer.close()
        await writer.wait_closed()
        return response
    finally:
        listener.close()
        await listener.wait_closed()


def test_control_auth_accepts_an_identical_token() -> None:
    response = asyncio.run(_authenticate("same-token", "same-token"))
    assert response["type"] == "accept"


def test_control_auth_rejects_a_different_token_before_session_setup() -> None:
    response = asyncio.run(_authenticate("server-token", "client-token"))
    assert response == {"type": "error", "message": "authentication failed"}
