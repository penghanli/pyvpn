from __future__ import annotations

import asyncio
import ipaddress

import pytest

from pyvpn.client import ClientConfig, ClientSession, VpnClient
from pyvpn.constants import PACKET_TYPE_DATA, PACKET_TYPE_KEEPALIVE
from pyvpn.crypto import TunnelCipher, new_session_keys
from pyvpn.errors import TunnelUnavailableError
from pyvpn.ingress import OrderedTunWriter
from pyvpn.packet import seal_packet
from pyvpn.server import ActiveSession, ServerConfig, VpnServer


def _packet(source: str, destination: str, marker: int) -> bytes:
    header = bytearray(20)
    header[0] = 0x45
    header[2:4] = (21).to_bytes(2, "big")
    header[8] = 64
    header[9] = 6
    header[12:16] = ipaddress.IPv4Address(source).packed
    header[16:20] = ipaddress.IPv4Address(destination).packed
    return bytes(header) + bytes([marker])


class RecordingTun:
    def __init__(self) -> None:
        self.packets: list[bytes] = []
        self.batches: list[int] = []

    async def write_batch(self, packets: list[bytes]) -> None:
        self.packets.extend(packets)
        self.batches.append(len(packets))


async def _drain(writer: OrderedTunWriter, count: int) -> None:
    task = asyncio.create_task(writer.run())
    try:
        for _ in range(100):
            if len(writer.tun.packets) == count:
                return
            await asyncio.sleep(0.001)
        raise AssertionError("TUN writer did not drain queued packets")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_ordered_tun_writer_batches_without_reordering() -> None:
    async def scenario() -> None:
        tun = RecordingTun()
        writer = OrderedTunWriter(tun, "test")
        packets = [bytes([number]) for number in range(100)]
        for packet in packets:
            writer.offer(packet)
        await _drain(writer, len(packets))
        assert tun.packets == packets
        assert tun.batches == [64, 36]

    asyncio.run(scenario())


def test_ordered_tun_writer_bounds_queue_and_reports_drops(monkeypatch, capsys) -> None:
    from pyvpn import ingress

    monkeypatch.setattr(ingress, "TUN_WRITE_QUEUE_SIZE", 2)
    writer = OrderedTunWriter(RecordingTun(), "client")
    writer.offer(b"one")
    writer.offer(b"two")
    writer.offer(b"three")
    assert writer.queue.qsize() == 2
    assert writer.dropped == 1
    assert "client UDP-to-TUN queue full" in capsys.readouterr().err


def test_ordered_tun_writer_surfaces_write_failure() -> None:
    class BrokenTun:
        async def write_batch(self, _packets: list[bytes]) -> None:
            raise TunnelUnavailableError("Wintun write failed")

    async def scenario() -> None:
        writer = OrderedTunWriter(BrokenTun(), "client")
        writer.offer(b"packet")
        with pytest.raises(TunnelUnavailableError, match="Wintun write failed"):
            await writer.run()

    asyncio.run(scenario())


def test_ordered_tun_writer_yields_between_busy_batches() -> None:
    async def scenario() -> None:
        tick = asyncio.Event()
        loop = asyncio.get_running_loop()

        class BusyTun(RecordingTun):
            async def write_batch(self, packets: list[bytes]) -> None:
                await super().write_batch(packets)
                if len(self.batches) == 1:
                    loop.call_soon(tick.set)
                elif not tick.is_set():
                    raise AssertionError("TUN writer starved other tasks")

        tun = BusyTun()
        writer = OrderedTunWriter(tun, "test")
        for marker in range(128):
            writer.offer(bytes([marker]))
        task = asyncio.create_task(writer.run())
        try:
            await asyncio.wait_for(tick.wait(), timeout=1)
            await asyncio.sleep(0)
            assert len(tun.packets) == 128
            assert not task.done()
        finally:
            task.cancel()
            result = await asyncio.gather(task, return_exceptions=True)
            assert isinstance(result[0], asyncio.CancelledError)

    asyncio.run(scenario())


def test_client_accepts_keepalive_and_queues_data_in_order() -> None:
    async def scenario() -> None:
        config = ClientConfig(
            server_host="127.0.0.1",
            control_port=8443,
            token="test-token",
            cert_fingerprint="sha256:" + "a" * 64,
            client_id="test-client",
            tun_name="pyvpn0",
            mtu=1280,
            manage_dns=True,
            bypass_ips=[],
            stop_file=None,
        )
        keys = new_session_keys()
        client = VpnClient(config)
        client.session = ClientSession(
            session_id=7,
            client_vip="10.8.0.2",
            server_vip="10.8.0.1",
            dns="1.1.1.1",
            udp_host="127.0.0.1",
            udp_port=8444,
            keys=keys,
            c2s_cipher=TunnelCipher(keys.c2s),
            s2c_cipher=TunnelCipher(keys.s2c),
        )
        tun = RecordingTun()
        client.tun = tun
        client.tun_writer = OrderedTunWriter(tun, "client")
        address = ("127.0.0.1", 8444)
        expected = [_packet("1.1.1.1", "10.8.0.2", marker) for marker in range(3)]
        for seq, plaintext in enumerate(expected, 1):
            encrypted = seal_packet(PACKET_TYPE_DATA, 7, seq, plaintext, client.session.s2c_cipher)
            client.handle_udp_datagram(encrypted, address)
        keepalive = seal_packet(PACKET_TYPE_KEEPALIVE, 7, 4, b"", client.session.s2c_cipher)
        client.handle_udp_datagram(keepalive, address)
        assert client._udp_received.is_set()
        await _drain(client.tun_writer, len(expected))
        assert tun.packets == expected

    asyncio.run(scenario())


def test_server_queues_authenticated_data_in_order() -> None:
    async def scenario() -> None:
        config = ServerConfig(
            listen_host="127.0.0.1",
            control_port=8443,
            udp_port=8444,
            public_host="127.0.0.1",
            token="test-token",
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
        server = VpnServer(config)
        keys = new_session_keys()
        session = ActiveSession(
            session_id=7,
            client_id="test-client",
            client_vip=ipaddress.IPv4Address("10.8.0.2"),
            keys=keys,
            c2s_cipher=TunnelCipher(keys.c2s),
            s2c_cipher=TunnelCipher(keys.s2c),
        )
        server._add_session(session)
        tun = RecordingTun()
        server.tun = tun
        server.tun_writer = OrderedTunWriter(tun, "server")
        expected = [_packet("10.8.0.2", "1.1.1.1", marker) for marker in range(3)]
        for seq, plaintext in enumerate(expected, 1):
            encrypted = seal_packet(PACKET_TYPE_DATA, 7, seq, plaintext, session.c2s_cipher)
            address = ("192.0.2.10", 50000) if seq < 3 else ("198.51.100.20", 51000)
            server.handle_udp_datagram(encrypted, address)
        await _drain(server.tun_writer, len(expected))
        assert tun.packets == expected
        assert session.client_addr == ("198.51.100.20", 51000)

    asyncio.run(scenario())
