from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pyvpn import client as client_module
from pyvpn.client import ClientConfig, ClientSession, VpnClient
from pyvpn.constants import PACKET_TYPE_KEEPALIVE
from pyvpn.crypto import TunnelCipher, new_session_keys
from pyvpn.errors import AuthenticationError, TunnelUnavailableError
from pyvpn.packet import seal_packet


class FakeUdpTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, address: tuple[str, int]) -> None:
        self.sent.append((data, address))


def make_client() -> tuple[VpnClient, FakeUdpTransport]:
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
    client.tun = object()
    transport = FakeUdpTransport()
    client.udp_transport = transport
    client.server_udp_addr = ("127.0.0.1", 8444)
    return client, transport


def test_client_waits_for_authenticated_udp_response() -> None:
    async def scenario() -> None:
        client, transport = make_client()
        probe = asyncio.create_task(client._await_udp_ready())
        await asyncio.sleep(0)
        assert len(transport.sent) == 1
        assert not probe.done()

        wrong_key = TunnelCipher(new_session_keys().s2c)
        invalid = seal_packet(PACKET_TYPE_KEEPALIVE, 7, 1, b"", wrong_key)
        await client.handle_udp_datagram(invalid, client.server_udp_addr)
        assert not probe.done()

        reply = seal_packet(PACKET_TYPE_KEEPALIVE, 7, 1, b"", client.session.s2c_cipher)
        await client.handle_udp_datagram(reply, client.server_udp_addr)
        await probe
        assert client._last_udp_received is not None

    asyncio.run(scenario())


def test_client_reports_missing_udp_path(monkeypatch) -> None:
    monkeypatch.setattr(client_module, "UDP_PROBE_TIMEOUT", 0.03)
    monkeypatch.setattr(client_module, "UDP_PROBE_INTERVAL", 0.005)

    async def scenario() -> None:
        client, transport = make_client()
        with pytest.raises(TunnelUnavailableError, match="UDP tunnel did not respond"):
            await client._await_udp_ready()
        assert len(transport.sent) >= 2

    asyncio.run(scenario())


def test_client_detects_udp_stall_after_connection() -> None:
    client, _ = make_client()
    client._last_udp_received = 10.0
    client._check_udp_health(10.0 + client_module.UDP_STALE_TIMEOUT)
    with pytest.raises(TunnelUnavailableError, match="stopped responding"):
        client._check_udp_health(10.0 + client_module.UDP_STALE_TIMEOUT + 1)


def test_windows_worker_retries_transient_failure(monkeypatch, tmp_path: Path) -> None:
    windows_gui = pytest.importorskip("pyvpn.windows_gui")
    attempts = 0

    async def flaky_client(_args: list[str]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TunnelUnavailableError("temporary UDP loss")

    monkeypatch.setattr(windows_gui, "client_async_main", flaky_client)
    monkeypatch.setattr(windows_gui, "RECONNECT_DELAYS", (0, 0))
    assert windows_gui._run_client_with_retries([], tmp_path / "stop") == 0
    assert attempts == 3


def test_windows_worker_does_not_retry_authentication_failure(
    monkeypatch, tmp_path: Path
) -> None:
    windows_gui = pytest.importorskip("pyvpn.windows_gui")
    async def bad_token(_args: list[str]) -> None:
        raise AuthenticationError("wrong token")

    monkeypatch.setattr(windows_gui, "client_async_main", bad_token)
    with pytest.raises(AuthenticationError):
        windows_gui._run_client_with_retries([], tmp_path / "stop")


def test_windows_worker_honors_stop_during_recovery(monkeypatch, tmp_path: Path) -> None:
    windows_gui = pytest.importorskip("pyvpn.windows_gui")
    stop_file = tmp_path / "stop"
    attempts = 0

    async def interrupted_client(_args: list[str]) -> None:
        nonlocal attempts
        attempts += 1
        stop_file.write_text("stop\n", encoding="ascii")
        raise TunnelUnavailableError("temporary UDP loss")

    monkeypatch.setattr(windows_gui, "client_async_main", interrupted_client)
    assert windows_gui._run_client_with_retries([], stop_file) == 0
    assert attempts == 1
    assert not stop_file.exists()


def test_windows_client_id_is_stable_across_restarts(tmp_path: Path) -> None:
    windows_gui = pytest.importorskip("pyvpn.windows_gui")
    path = tmp_path / "client.id"
    first = windows_gui._persistent_client_id(path)
    second = windows_gui._persistent_client_id(path)
    assert first == second
    assert path.read_text(encoding="ascii").strip() == first
