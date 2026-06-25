import struct
import sys
import types

from pyvpn import tun


class FakeSocket:
    last_instance = None

    def __init__(self, family, kind, proto):
        self.family = family
        self.kind = kind
        self.proto = proto
        self.connected_to = None
        self.blocking = None
        self.closed = False
        FakeSocket.last_instance = self

    def fileno(self):
        return 10

    def connect(self, address):
        self.connected_to = address

    def getsockopt(self, level, optname, buflen):
        return b"utun7\x00"

    def setblocking(self, value):
        self.blocking = value

    def close(self):
        self.closed = True


def test_macos_utun_connects_with_python_pf_system_address(monkeypatch):
    monkeypatch.setattr(tun.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(tun.socket, "socket", FakeSocket)

    fake_fcntl = types.SimpleNamespace(
        ioctl=lambda _fd, _request, _payload: struct.pack("I", 42) + b"\x00" * 96
    )
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)

    device = tun.MacUtunDevice.create("utun7", 1280)

    assert device.name == "utun7"
    assert FakeSocket.last_instance.connected_to == (42, 8)
    assert FakeSocket.last_instance.blocking is False
