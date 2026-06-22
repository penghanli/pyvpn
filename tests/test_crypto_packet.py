import pytest

from pyvpn.constants import PACKET_TYPE_DATA
from pyvpn.crypto import TunnelCipher, new_session_keys
from pyvpn.errors import ProtocolError
from pyvpn.packet import open_packet, seal_packet


def test_encrypted_packet_round_trip() -> None:
    keys = new_session_keys()
    cipher = TunnelCipher(keys.c2s)
    raw = seal_packet(PACKET_TYPE_DATA, session_id=42, seq=1, plaintext=b"packet", cipher=cipher)

    header, plaintext = open_packet(raw, cipher)

    assert header.session_id == 42
    assert header.seq == 1
    assert header.packet_type == PACKET_TYPE_DATA
    assert plaintext == b"packet"


def test_encrypted_packet_authenticates_header() -> None:
    keys = new_session_keys()
    cipher = TunnelCipher(keys.c2s)
    raw = bytearray(
        seal_packet(PACKET_TYPE_DATA, session_id=42, seq=1, plaintext=b"packet", cipher=cipher)
    )
    raw[5] = 99

    with pytest.raises(ProtocolError):
        open_packet(bytes(raw), cipher)
