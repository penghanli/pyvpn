"""Linux pyvpn server runtime."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import secrets
import signal
import ssl
import time
from dataclasses import dataclass, field

from .auth import token_matches
from .constants import (
    CONTROL_VERSION,
    DEFAULT_CLIENT_SUBNET,
    DEFAULT_CLIENT_VIP,
    DEFAULT_DNS,
    DEFAULT_MTU,
    DEFAULT_SERVER_VIP,
    PACKET_TYPE_DATA,
    PACKET_TYPE_KEEPALIVE,
)
from .crypto import SessionKeys, TunnelCipher, new_session_keys
from .errors import ProtocolError
from .framing import read_frame, write_frame
from .ip import inspect_ipv4
from .nat import LinuxNatManager
from .packet import open_packet, parse_header, seal_packet
from .replay import ReplayWindow
from .system import require_linux_root
from .tun import LinuxTunDevice

DEFAULT_MAX_CLIENTS = 3
MIN_MAX_CLIENTS = 1
MAX_MAX_CLIENTS = 10


@dataclass
class ServerConfig:
    listen_host: str
    control_port: int
    udp_port: int
    public_host: str | None
    token: str
    certfile: str
    keyfile: str
    tun_name: str
    subnet: str
    server_vip: str
    client_vip: str
    dns: str
    mtu: int
    external_interface: str | None
    session_timeout: float
    max_clients: int


@dataclass
class ActiveSession:
    session_id: int
    client_id: str
    client_vip: ipaddress.IPv4Address
    keys: SessionKeys
    c2s_cipher: TunnelCipher
    s2c_cipher: TunnelCipher
    replay: ReplayWindow = field(default_factory=ReplayWindow)
    client_addr: tuple[str, int] | None = None
    tx_seq: int = 0
    last_seen: float = field(default_factory=time.monotonic)
    control_writer: object | None = None

    def next_seq(self) -> int:
        self.tx_seq += 1
        return self.tx_seq


class ServerUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: "VpnServer"):
        self.server = server

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.create_task(self.server.handle_udp_datagram(data, addr))

    def error_received(self, exc: Exception) -> None:
        print(f"UDP error: {exc}")


class VpnServer:
    def __init__(self, config: ServerConfig):
        self.config = config
        self.tun: LinuxTunDevice | None = None
        self.nat: LinuxNatManager | None = None
        self.udp_transport: asyncio.DatagramTransport | None = None
        self.sessions_by_id: dict[int, ActiveSession] = {}
        self.sessions_by_vip: dict[ipaddress.IPv4Address, ActiveSession] = {}
        self.client_pool = build_client_pool(
            config.subnet,
            config.server_vip,
            config.client_vip,
            config.max_clients,
        )
        self._stop = asyncio.Event()

    async def run(self) -> None:
        require_linux_root()
        self.tun = LinuxTunDevice.create(self.config.tun_name, self.config.mtu)
        self.tun.configure_server(self.config.server_vip, 24)

        self.nat = LinuxNatManager(self.config.subnet, self.config.external_interface)
        self.nat.enable()

        loop = asyncio.get_running_loop()
        await self._install_signal_handlers(loop)

        self.udp_transport, _ = await loop.create_datagram_endpoint(
            lambda: ServerUdpProtocol(self),
            local_addr=(self.config.listen_host, self.config.udp_port),
        )

        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(self.config.certfile, self.config.keyfile)

        control_server = await asyncio.start_server(
            self.handle_control,
            host=self.config.listen_host,
            port=self.config.control_port,
            ssl=tls,
        )

        stop_task = asyncio.create_task(self._stop.wait())
        tun_task = asyncio.create_task(self.tun_to_udp_loop())
        timeout_task = asyncio.create_task(self.session_timeout_loop())
        try:
            async with control_server:
                done, pending = await asyncio.wait(
                    [stop_task, tun_task, timeout_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    if task is not stop_task:
                        task.result()
        finally:
            control_server.close()
            await control_server.wait_closed()
            stop_task.cancel()
            tun_task.cancel()
            timeout_task.cancel()
            await self.cleanup()

    async def _install_signal_handlers(self, loop: asyncio.AbstractEventLoop) -> None:
        for signame in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, signame, None)
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                pass

    async def handle_control(self, reader, writer) -> None:
        peer = writer.get_extra_info("peername")
        session: ActiveSession | None = None
        try:
            hello = await read_frame(reader)
            if hello.get("type") != "hello" or hello.get("version") != CONTROL_VERSION:
                await self._send_error(writer, "invalid hello")
                return

            supplied_token = str(hello.get("token", ""))
            if not token_matches(self.config.token, supplied_token):
                await self._send_error(writer, "authentication failed")
                return

            if len(self.sessions_by_id) >= self.config.max_clients:
                await self._send_error(
                    writer,
                    f"server is full: {self.config.max_clients} clients are already active",
                )
                return

            client_id = str(hello.get("client_id") or "client")
            client_vip = self._allocate_client_vip()
            if client_vip is None:
                await self._send_error(writer, "server is full: no client address is available")
                return

            keys = new_session_keys()
            session = ActiveSession(
                session_id=self._new_session_id(),
                client_id=client_id,
                client_vip=client_vip,
                keys=keys,
                c2s_cipher=TunnelCipher(keys.c2s),
                s2c_cipher=TunnelCipher(keys.s2c),
            )
            session.control_writer = writer
            self._add_session(session)

            endpoint_host = self.config.public_host or self.config.listen_host
            await write_frame(
                writer,
                {
                    "type": "accept",
                    "version": CONTROL_VERSION,
                    "session_id": session.session_id,
                    "client_vip": f"{session.client_vip}/32",
                    "server_vip": self.config.server_vip,
                    "routes": ["0.0.0.0/0"],
                    "dns": [self.config.dns],
                    "mtu": self.config.mtu,
                    "udp_endpoint": {"host": endpoint_host, "port": self.config.udp_port},
                    "crypto": keys.to_json(),
                },
            )
            print(f"accepted client {client_id} from {peer}")
            await self._control_loop(reader, writer, session)
        except asyncio.IncompleteReadError:
            pass
        except Exception as exc:  # noqa: BLE001
            print(f"control connection error from {peer}: {exc}")
        finally:
            if session is not None:
                self._remove_session(session)
            await self._close_writer(writer)

    async def _control_loop(self, reader, writer, session: ActiveSession) -> None:
        while self.sessions_by_id.get(session.session_id) is session:
            message = await read_frame(reader)
            msg_type = message.get("type")
            if msg_type == "heartbeat":
                session.last_seen = time.monotonic()
                await write_frame(writer, {"type": "heartbeat", "time": time.time()})
            elif msg_type == "disconnect":
                await write_frame(writer, {"type": "disconnect"})
                return
            else:
                await self._send_error(writer, f"unsupported control frame: {msg_type}")
                return

    async def _send_error(self, writer, message: str) -> None:
        await write_frame(writer, {"type": "error", "message": message})

    def _allocate_client_vip(self) -> ipaddress.IPv4Address | None:
        for address in self.client_pool:
            if address not in self.sessions_by_vip:
                return address
        return None

    def _new_session_id(self) -> int:
        while True:
            session_id = secrets.randbits(64)
            if session_id not in self.sessions_by_id:
                return session_id

    def _add_session(self, session: ActiveSession) -> None:
        self.sessions_by_id[session.session_id] = session
        self.sessions_by_vip[session.client_vip] = session

    def _remove_session(self, session: ActiveSession) -> None:
        if self.sessions_by_id.get(session.session_id) is session:
            self.sessions_by_id.pop(session.session_id, None)
        if self.sessions_by_vip.get(session.client_vip) is session:
            self.sessions_by_vip.pop(session.client_vip, None)

    async def handle_udp_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            header = parse_header(data)
            session = self.sessions_by_id.get(header.session_id)
            if session is None:
                return
            if header.session_id != session.session_id:
                return
            header, plaintext = open_packet(data, session.c2s_cipher)
            if not session.replay.accept(header.seq):
                return
            session.client_addr = addr
            session.last_seen = time.monotonic()

            if header.packet_type == PACKET_TYPE_KEEPALIVE:
                self._send_udp(session, PACKET_TYPE_KEEPALIVE, b"")
                return

            info = inspect_ipv4(plaintext)
            if info.source != session.client_vip:
                return
            if self.tun is not None:
                await self.tun.write(plaintext[: info.total_length])
        except ProtocolError:
            return

    async def tun_to_udp_loop(self) -> None:
        if self.tun is None:
            return
        while True:
            packet = await self.tun.read()
            try:
                info = inspect_ipv4(packet)
            except ProtocolError:
                continue
            session = self.sessions_by_vip.get(info.destination)
            if session is None or session.client_addr is None:
                continue
            self._send_udp(session, PACKET_TYPE_DATA, packet[: info.total_length])

    async def session_timeout_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            for session in list(self.sessions_by_id.values()):
                if time.monotonic() - session.last_seen <= self.config.session_timeout:
                    continue
                print(f"client {session.client_id} timed out")
                self._remove_session(session)
                writer = session.control_writer
                if writer is not None:
                    writer.close()

    def _send_udp(self, session: ActiveSession, packet_type: int, plaintext: bytes) -> None:
        if self.udp_transport is None or session.client_addr is None:
            return
        data = seal_packet(
            packet_type,
            session.session_id,
            session.next_seq(),
            plaintext,
            session.s2c_cipher,
        )
        self.udp_transport.sendto(data, session.client_addr)

    async def cleanup(self) -> None:
        sessions = list(self.sessions_by_id.values())
        self.sessions_by_id.clear()
        self.sessions_by_vip.clear()
        for session in sessions:
            if session.control_writer is not None:
                await self._close_writer(session.control_writer)
        if self.udp_transport is not None:
            self.udp_transport.close()
            await asyncio.sleep(0)
        if self.nat is not None:
            self.nat.cleanup()
        if self.tun is not None:
            self.tun.close()

    async def _close_writer(self, writer) -> None:
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), timeout=2)
        except Exception as exc:  # noqa: BLE001
            print(f"ignored control close error: {exc}")


def build_client_pool(
    subnet: str,
    server_vip: str,
    first_client_vip: str,
    max_clients: int,
) -> tuple[ipaddress.IPv4Address, ...]:
    if not MIN_MAX_CLIENTS <= max_clients <= MAX_MAX_CLIENTS:
        raise ValueError("max clients must be from 1 to 10")
    network = ipaddress.IPv4Network(subnet, strict=False)
    server_address = ipaddress.IPv4Address(server_vip)
    first_address = ipaddress.IPv4Address(first_client_vip)
    if server_address not in network:
        raise ValueError(f"server VIP {server_address} is outside subnet {network}")
    if first_address not in network:
        raise ValueError(f"client VIP {first_address} is outside subnet {network}")

    addresses: list[ipaddress.IPv4Address] = []
    current = int(first_address)
    last_usable = int(network.broadcast_address) - 1
    while current <= last_usable and len(addresses) < max_clients:
        address = ipaddress.IPv4Address(current)
        if address != server_address and address != network.network_address:
            addresses.append(address)
        current += 1

    if len(addresses) < max_clients:
        raise ValueError(f"subnet {network} does not have {max_clients} usable client addresses")
    return tuple(addresses)


def parse_max_clients(value: str) -> int:
    try:
        max_clients = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("max clients must be an integer from 1 to 10") from exc
    if not MIN_MAX_CLIENTS <= max_clients <= MAX_MAX_CLIENTS:
        raise argparse.ArgumentTypeError("max clients must be from 1 to 10")
    return max_clients


def _token_from_arg(value: str | None) -> str:
    token = value or os.environ.get("PYVPN_TOKEN")
    if not token:
        raise SystemExit("token is required: pass --token or set PYVPN_TOKEN")
    return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Linux pyvpn server")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--control-port", type=int, default=8443)
    parser.add_argument("--udp-port", type=int, default=8444)
    parser.add_argument("--public-host")
    parser.add_argument("--token")
    parser.add_argument("--cert", required=True, dest="certfile")
    parser.add_argument("--key", required=True, dest="keyfile")
    parser.add_argument("--tun", default="pyvpn0", dest="tun_name")
    parser.add_argument("--subnet", default=DEFAULT_CLIENT_SUBNET)
    parser.add_argument("--server-vip", default=DEFAULT_SERVER_VIP)
    parser.add_argument("--client-vip", default=DEFAULT_CLIENT_VIP)
    parser.add_argument("--dns", default=DEFAULT_DNS)
    parser.add_argument("--mtu", type=int, default=DEFAULT_MTU)
    parser.add_argument("--external-interface")
    parser.add_argument("--session-timeout", type=float, default=60.0)
    parser.add_argument("--max-clients", type=parse_max_clients, default=DEFAULT_MAX_CLIENTS)
    return parser


async def async_main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = ServerConfig(
        listen_host=args.listen_host,
        control_port=args.control_port,
        udp_port=args.udp_port,
        public_host=args.public_host,
        token=_token_from_arg(args.token),
        certfile=args.certfile,
        keyfile=args.keyfile,
        tun_name=args.tun_name,
        subnet=args.subnet,
        server_vip=args.server_vip,
        client_vip=args.client_vip,
        dns=args.dns,
        mtu=args.mtu,
        external_interface=args.external_interface,
        session_timeout=args.session_timeout,
        max_clients=args.max_clients,
    )
    await VpnServer(config).run()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
