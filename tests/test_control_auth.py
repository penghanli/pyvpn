from __future__ import annotations

import asyncio
import ipaddress

from pyvpn.constants import CONTROL_VERSION
from pyvpn.framing import read_frame, write_frame
from pyvpn.constants import PACKET_TYPE_KEEPALIVE
from pyvpn.crypto import TunnelCipher, new_session_keys
from pyvpn.packet import open_packet, seal_packet
from pyvpn.server import ActiveSession, ServerConfig, VpnServer


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


def test_server_echoes_existing_encrypted_udp_keepalive() -> None:
    async def scenario() -> None:
        server = VpnServer(_server_config("test-token"))
        keys = new_session_keys()
        session = ActiveSession(
            session_id=7,
            client_id="windows-client",
            client_vip=ipaddress.IPv4Address("10.8.0.2"),
            keys=keys,
            c2s_cipher=TunnelCipher(keys.c2s),
            s2c_cipher=TunnelCipher(keys.s2c),
        )
        server._add_session(session)

        class Transport:
            sent: tuple[bytes, tuple[str, int]] | None = None

            def sendto(self, data: bytes, address: tuple[str, int]) -> None:
                self.sent = (data, address)

        transport = Transport()
        server.udp_transport = transport
        probe = seal_packet(PACKET_TYPE_KEEPALIVE, 7, 1, b"", session.c2s_cipher)
        await server.handle_udp_datagram(probe, ("192.0.2.10", 50000))

        assert session.last_udp_seen is not None
        assert transport.sent is not None
        reply, destination = transport.sent
        header, plaintext = open_packet(reply, session.s2c_cipher)
        assert destination == ("192.0.2.10", 50000)
        assert header.packet_type == PACKET_TYPE_KEEPALIVE
        assert plaintext == b""

    asyncio.run(scenario())


def test_server_replaces_previous_session_with_same_client_id() -> None:
    async def scenario() -> None:
        config = _server_config("test-token")
        config.max_clients = 1
        server = VpnServer(config)
        listener = await asyncio.start_server(server.handle_control, "127.0.0.1", 0)
        port = listener.sockets[0].getsockname()[1]
        connections = []
        try:
            for _ in range(2):
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                connections.append((reader, writer))
                await write_frame(
                    writer,
                    {
                        "type": "hello",
                        "version": CONTROL_VERSION,
                        "token": "test-token",
                        "client_id": "same-installation",
                        "mtu": 1280,
                    },
                )
                response = await read_frame(reader)
                assert response["type"] == "accept"
            assert len(server.sessions_by_id) == 1
            assert await asyncio.wait_for(connections[0][0].read(1), 1) == b""
            await write_frame(connections[1][1], {"type": "disconnect"})
            assert (await read_frame(connections[1][0]))["type"] == "disconnect"
        finally:
            for _, writer in connections:
                writer.close()
                await writer.wait_closed()
            listener.close()
            await listener.wait_closed()

    asyncio.run(scenario())
