from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path

import pytest

from pyvpn import client as client_module
from pyvpn.client import ClientConfig, ClientSession, VpnClient
from pyvpn.constants import PACKET_TYPE_DATA, PACKET_TYPE_KEEPALIVE
from pyvpn.crypto import TunnelCipher, new_session_keys
from pyvpn.errors import AuthenticationError, PlatformError, TunnelUnavailableError
from pyvpn.packet import open_packet, seal_packet
from pyvpn.routes import WindowsClientNetwork


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
        client.handle_udp_datagram(invalid, client.server_udp_addr)
        assert not probe.done()

        reply = seal_packet(PACKET_TYPE_KEEPALIVE, 7, 1, b"", client.session.s2c_cipher)
        client.handle_udp_datagram(reply, client.server_udp_addr)
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


@pytest.mark.parametrize(
    ("message", "expected_error"),
    [
        ("server is full: 5 clients are already active", TunnelUnavailableError),
        ("authentication failed", AuthenticationError),
    ],
)
def test_client_retries_capacity_but_not_bad_token(
    monkeypatch, message: str, expected_error: type[Exception]
) -> None:
    client, _ = make_client()
    client.tun = None
    client.session = None
    client.udp_transport = None

    class FakeWriter:
        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    async def fake_open(_address: str):
        return object(), FakeWriter()

    async def fake_hello(_writer) -> None:
        pass

    async def fake_read(_reader):
        return {"type": "error", "message": message}

    async def fake_write(_writer, _message) -> None:
        pass

    monkeypatch.setattr(client_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(client_module, "require_linux_root", lambda: None)
    monkeypatch.setattr(client_module, "resolve_ipv4", lambda _host: "127.0.0.1")
    monkeypatch.setattr(client, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(client, "_open_control", fake_open)
    monkeypatch.setattr(client, "_send_hello", fake_hello)
    monkeypatch.setattr(client_module, "read_frame", fake_read)
    monkeypatch.setattr(client_module, "write_frame", fake_write)

    with pytest.raises(expected_error):
        asyncio.run(client.run())


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


def test_windows_worker_keeps_retrying_until_network_recovers(monkeypatch, tmp_path: Path) -> None:
    windows_gui = pytest.importorskip("pyvpn.windows_gui")
    attempts = 0

    async def flaky_client(_args: list[str]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 10:
            raise TunnelUnavailableError("temporary network loss")

    monkeypatch.setattr(windows_gui, "client_async_main", flaky_client)
    monkeypatch.setattr(windows_gui, "RECONNECT_DELAYS", (0,))
    assert windows_gui._run_client_with_retries([], tmp_path / "stop") == 0
    assert attempts == 10


@pytest.mark.parametrize(
    "failure",
    [
        asyncio.IncompleteReadError(b"", 4),
        PlatformError("Find-NetRoute: System Error 1232"),
    ],
)
def test_windows_worker_retries_route_and_control_failures(
    monkeypatch, tmp_path: Path, failure: Exception
) -> None:
    windows_gui = pytest.importorskip("pyvpn.windows_gui")
    attempts = 0

    async def flaky_client(_args: list[str]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise failure

    monkeypatch.setattr(windows_gui, "client_async_main", flaky_client)
    monkeypatch.setattr(windows_gui, "RECONNECT_DELAYS", (0,))
    assert windows_gui._run_client_with_retries([], tmp_path / "stop") == 0
    assert attempts == 2


def test_windows_route_drift_requests_reconnect(monkeypatch) -> None:
    client, _ = make_client()
    network = WindowsClientNetwork("pyvpn0", ["127.0.0.1"], "10.8.0.1", "1.1.1.1")
    client.network = network
    monkeypatch.setattr(client_module, "WINDOWS_ROUTE_CHECK_INTERVAL", 0)

    def route_changed() -> None:
        raise PlatformError("server bypass route changed")

    monkeypatch.setattr(network, "verify", route_changed)
    with pytest.raises(TunnelUnavailableError, match="Windows route or DNS changed"):
        asyncio.run(client.windows_route_health_loop())


def test_windows_route_health_tolerates_one_failed_check(monkeypatch) -> None:
    client, _ = make_client()
    network = WindowsClientNetwork("pyvpn0", ["127.0.0.1"], "10.8.0.1", "1.1.1.1")
    client.network = network
    monkeypatch.setattr(client_module, "WINDOWS_ROUTE_CHECK_INTERVAL", 0)
    checks = 0

    def intermittent_check() -> None:
        nonlocal checks
        checks += 1
        if checks in (1, 3, 4):
            raise PlatformError("Find-NetRoute: System Error 1232")

    monkeypatch.setattr(network, "verify", intermittent_check)
    with pytest.raises(TunnelUnavailableError, match="Windows route or DNS changed"):
        asyncio.run(client.windows_route_health_loop())
    assert checks == 4


def test_client_forwards_wintun_batch_in_order() -> None:
    client, transport = make_client()

    def ipv4_packet(source: str, marker: int) -> bytes:
        header = bytearray(20)
        header[0] = 0x45
        header[2:4] = (21).to_bytes(2, "big")
        header[8] = 64
        header[9] = 6
        header[12:16] = ipaddress.IPv4Address(source).packed
        header[16:20] = ipaddress.IPv4Address("1.1.1.1").packed
        return bytes(header) + bytes([marker])

    class FakeBatchTun:
        calls = 0

        async def read_batch(self) -> list[bytes]:
            self.calls += 1
            if self.calls == 1:
                return [
                    ipv4_packet("10.8.0.2", 1),
                    ipv4_packet("10.8.0.3", 2),
                    ipv4_packet("10.8.0.2", 3),
                ]
            await asyncio.Future()

    tun = FakeBatchTun()
    client.tun = tun

    async def scenario() -> None:
        task = asyncio.create_task(client.tun_to_udp_loop())
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert tun.calls == 2
    assert len(transport.sent) == 2
    plaintexts = [
        open_packet(data, client.session.c2s_cipher)[1]
        for data, _ in transport.sent
    ]
    assert [plaintext[-1] for plaintext in plaintexts] == [1, 3]
    assert all(
        open_packet(data, client.session.c2s_cipher)[0].packet_type == PACKET_TYPE_DATA
        for data, _ in transport.sent
    )


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


def test_cli_reconnect_keeps_one_client_id(monkeypatch) -> None:
    attempts: list[str] = []

    async def flaky_client(argv: list[str]) -> None:
        attempts.append(client_module.build_parser().parse_args(argv).client_id)
        if len(attempts) < 3:
            raise TunnelUnavailableError("temporary UDP loss")

    monkeypatch.setattr(client_module, "async_main", flaky_client)
    monkeypatch.setattr(client_module, "CLI_RECONNECT_DELAYS", (0,))
    monkeypatch.setattr(client_module.sys, "argv", ["pyvpn-client", "--reconnect"])
    client_module.main()
    assert len(attempts) == 3
    assert len(set(attempts)) == 1


def test_cli_reconnect_honors_stop_during_recovery(monkeypatch, tmp_path: Path) -> None:
    stop_file = tmp_path / "client.stop"
    attempts = 0

    async def interrupted_client(_argv: list[str]) -> None:
        nonlocal attempts
        attempts += 1
        stop_file.write_text("stop\n", encoding="ascii")
        raise TunnelUnavailableError("temporary UDP loss")

    monkeypatch.setattr(client_module, "async_main", interrupted_client)
    monkeypatch.setattr(
        client_module.sys,
        "argv",
        ["pyvpn-client", "--reconnect", "--stop-file", str(stop_file)],
    )
    client_module.main()
    assert attempts == 1
    assert not stop_file.exists()


def test_cli_reconnect_retries_control_eof(monkeypatch) -> None:
    attempts = 0

    async def disconnected(_argv: list[str]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise asyncio.IncompleteReadError(b"", 4)

    monkeypatch.setattr(client_module, "async_main", disconnected)
    monkeypatch.setattr(client_module, "CLI_RECONNECT_DELAYS", (0,))
    monkeypatch.setattr(client_module.sys, "argv", ["pyvpn-client", "--reconnect"])
    client_module.main()
    assert attempts == 2


def test_cli_without_reconnect_keeps_one_shot_behavior(monkeypatch) -> None:
    attempts = 0

    async def failing_client() -> None:
        nonlocal attempts
        attempts += 1
        raise TunnelUnavailableError("temporary UDP loss")

    monkeypatch.setattr(client_module, "async_main", failing_client)
    monkeypatch.setattr(client_module.sys, "argv", ["pyvpn-client"])
    with pytest.raises(TunnelUnavailableError, match="temporary UDP loss"):
        client_module.main()
    assert attempts == 1


def test_online_client_launchers_enable_reconnect() -> None:
    root = Path(__file__).resolve().parents[1] / "scripts"
    windows = (root / "windows" / "install-client.ps1").read_text(encoding="utf-8")
    linux = (root / "linux" / "install-client.sh").read_text(encoding="utf-8")
    macos = (root / "macos" / "install-client.sh").read_text(encoding="utf-8")

    assert '`$argsList = @(\n  "--reconnect",' in windows
    assert 'ARGS=(\n  --reconnect' in linux
    assert 'ARGS=(\n  --reconnect' in macos
