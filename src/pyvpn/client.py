"""pyvpn client runtime."""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import socket
import ssl
import uuid
from dataclasses import dataclass, field

from .auth import certificate_fingerprint, normalize_fingerprint
from .constants import CONTROL_VERSION, DEFAULT_MTU, PACKET_TYPE_DATA, PACKET_TYPE_KEEPALIVE
from .crypto import SessionKeys, TunnelCipher
from .errors import AuthenticationError, ProtocolError
from .framing import read_frame, write_frame
from .ip import inspect_ipv4
from .packet import open_packet, parse_header, seal_packet
from .replay import ReplayWindow
from .routes import LinuxClientNetwork, resolve_ipv4
from .system import require_linux_root
from .tun import LinuxTunDevice, create_tun


@dataclass
class ClientConfig:
    server_host: str
    control_port: int
    token: str
    cert_fingerprint: str
    client_id: str
    tun_name: str
    mtu: int
    manage_dns: bool


@dataclass
class ClientSession:
    session_id: int
    client_vip: str
    server_vip: str
    dns: str
    udp_host: str
    udp_port: int
    keys: SessionKeys
    c2s_cipher: TunnelCipher
    s2c_cipher: TunnelCipher
    replay: ReplayWindow = field(default_factory=ReplayWindow)
    tx_seq: int = 0

    def next_seq(self) -> int:
        self.tx_seq += 1
        return self.tx_seq


class ClientUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, client: "VpnClient"):
        self.client = client

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.create_task(self.client.handle_udp_datagram(data, addr))

    def error_received(self, exc: Exception) -> None:
        print(f"UDP error: {exc}")


class VpnClient:
    def __init__(self, config: ClientConfig):
        self.config = config
        self.tun: LinuxTunDevice | None = None
        self.network: LinuxClientNetwork | None = None
        self.udp_transport: asyncio.DatagramTransport | None = None
        self.session: ClientSession | None = None
        self.server_udp_addr: tuple[str, int] | None = None

    async def run(self) -> None:
        if platform.system() != "Linux":
            create_tun(self.config.tun_name, self.config.mtu)
            return
        require_linux_root()

        server_ip = resolve_ipv4(self.config.server_host)
        reader, writer = await self._open_control()
        try:
            await self._send_hello(writer)
            accept = await read_frame(reader)
            if accept.get("type") == "error":
                raise AuthenticationError(str(accept.get("message", "server rejected client")))
            self.session = self._parse_accept(accept)

            self.tun = LinuxTunDevice.create(self.config.tun_name, self.config.mtu)
            self.tun.configure_client(self.session.client_vip, self.session.server_vip)

            self.network = LinuxClientNetwork(
                tun_name=self.tun.name,
                server_ips=[server_ip, self.session.udp_host],
                gateway=self.session.server_vip,
                dns=self.session.dns,
                manage_dns=self.config.manage_dns,
            )
            self.network.setup()

            loop = asyncio.get_running_loop()
            self.udp_transport, _ = await loop.create_datagram_endpoint(
                lambda: ClientUdpProtocol(self),
                local_addr=("0.0.0.0", 0),
            )
            self.server_udp_addr = (self.session.udp_host, self.session.udp_port)
            self._send_udp(PACKET_TYPE_KEEPALIVE, b"")

            tasks = [
                asyncio.create_task(self.tun_to_udp_loop()),
                asyncio.create_task(self.control_heartbeat_loop(reader, writer)),
                asyncio.create_task(self.udp_keepalive_loop()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        finally:
            try:
                await write_frame(writer, {"type": "disconnect"})
            except Exception:  # noqa: BLE001
                pass
            writer.close()
            await writer.wait_closed()
            await self.cleanup()

    async def _open_control(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        reader, writer = await asyncio.open_connection(
            self.config.server_host,
            self.config.control_port,
            ssl=context,
            server_hostname=None,
        )
        ssl_object = writer.get_extra_info("ssl_object")
        cert_der = ssl_object.getpeercert(binary_form=True)
        expected = normalize_fingerprint(self.config.cert_fingerprint)
        actual = normalize_fingerprint(certificate_fingerprint(cert_der))
        if actual != expected:
            writer.close()
            await writer.wait_closed()
            raise AuthenticationError(f"server certificate fingerprint mismatch: {actual}")
        return reader, writer

    async def _send_hello(self, writer) -> None:
        await write_frame(
            writer,
            {
                "type": "hello",
                "version": CONTROL_VERSION,
                "token": self.config.token,
                "client_id": self.config.client_id,
                "mtu": self.config.mtu,
                "capabilities": ["ipv4", "dns", "chacha20-poly1305"],
            },
        )

    def _parse_accept(self, message: dict[str, object]) -> ClientSession:
        if message.get("type") != "accept" or message.get("version") != CONTROL_VERSION:
            raise ProtocolError("server did not send an accept frame")
        crypto = message.get("crypto")
        endpoint = message.get("udp_endpoint")
        dns_values = message.get("dns")
        if not isinstance(crypto, dict) or not isinstance(endpoint, dict):
            raise ProtocolError("invalid accept frame")
        if not isinstance(dns_values, list) or not dns_values:
            raise ProtocolError("accept frame did not include DNS")
        udp_host = str(endpoint.get("host") or self.config.server_host)
        if udp_host in {"0.0.0.0", "::"}:
            udp_host = self.config.server_host
        keys = SessionKeys.from_json(crypto)
        client_vip = str(message["client_vip"]).split("/", 1)[0]
        return ClientSession(
            session_id=int(message["session_id"]),
            client_vip=client_vip,
            server_vip=str(message["server_vip"]),
            dns=str(dns_values[0]),
            udp_host=socket.gethostbyname(udp_host),
            udp_port=int(endpoint["port"]),
            keys=keys,
            c2s_cipher=TunnelCipher(keys.c2s),
            s2c_cipher=TunnelCipher(keys.s2c),
        )

    async def tun_to_udp_loop(self) -> None:
        if self.tun is None:
            return
        while True:
            packet = await self.tun.read()
            try:
                info = inspect_ipv4(packet)
            except ProtocolError:
                continue
            if str(info.source) != self.session.client_vip:
                continue
            self._send_udp(PACKET_TYPE_DATA, packet[: info.total_length])

    async def handle_udp_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        session = self.session
        if session is None or self.tun is None:
            return
        try:
            header = parse_header(data)
            if header.session_id != session.session_id:
                return
            header, plaintext = open_packet(data, session.s2c_cipher)
            if not session.replay.accept(header.seq):
                return
            if header.packet_type == PACKET_TYPE_KEEPALIVE:
                return
            info = inspect_ipv4(plaintext)
            if str(info.destination) != session.client_vip:
                return
            await self.tun.write(plaintext[: info.total_length])
        except ProtocolError:
            return

    async def control_heartbeat_loop(self, reader, writer) -> None:
        while True:
            await asyncio.sleep(15)
            await write_frame(writer, {"type": "heartbeat"})
            response = await asyncio.wait_for(read_frame(reader), timeout=10)
            if response.get("type") == "error":
                raise ProtocolError(str(response.get("message", "server error")))

    async def udp_keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            self._send_udp(PACKET_TYPE_KEEPALIVE, b"")

    def _send_udp(self, packet_type: int, plaintext: bytes) -> None:
        if self.udp_transport is None or self.server_udp_addr is None or self.session is None:
            return
        data = seal_packet(
            packet_type,
            self.session.session_id,
            self.session.next_seq(),
            plaintext,
            self.session.c2s_cipher,
        )
        self.udp_transport.sendto(data, self.server_udp_addr)

    async def cleanup(self) -> None:
        if self.network is not None:
            self.network.cleanup()
        if self.udp_transport is not None:
            self.udp_transport.close()
        if self.tun is not None:
            self.tun.close()


def _token_from_arg(value: str | None) -> str:
    token = value or os.environ.get("PYVPN_TOKEN")
    if not token:
        raise SystemExit("token is required: pass --token or set PYVPN_TOKEN")
    return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the pyvpn client")
    parser.add_argument("--server-host", required=True)
    parser.add_argument("--control-port", type=int, default=8443)
    parser.add_argument("--token")
    parser.add_argument("--cert-fingerprint", required=True)
    parser.add_argument("--client-id", default=str(uuid.uuid4()))
    parser.add_argument("--tun", default="pyvpn0", dest="tun_name")
    parser.add_argument("--mtu", type=int, default=DEFAULT_MTU)
    parser.add_argument("--no-dns", action="store_true")
    return parser


async def async_main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = ClientConfig(
        server_host=args.server_host,
        control_port=args.control_port,
        token=_token_from_arg(args.token),
        cert_fingerprint=args.cert_fingerprint,
        client_id=args.client_id,
        tun_name=args.tun_name,
        mtu=args.mtu,
        manage_dns=not args.no_dns,
    )
    await VpnClient(config).run()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
