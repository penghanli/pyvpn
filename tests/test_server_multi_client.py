import argparse
import ipaddress

import pytest

from pyvpn.server import build_client_pool, parse_max_clients


def test_build_client_pool_starts_at_first_client_vip() -> None:
    pool = build_client_pool("10.8.0.0/24", "10.8.0.1", "10.8.0.2", 3)

    assert pool == (
        ipaddress.IPv4Address("10.8.0.2"),
        ipaddress.IPv4Address("10.8.0.3"),
        ipaddress.IPv4Address("10.8.0.4"),
    )


def test_build_client_pool_skips_server_vip() -> None:
    pool = build_client_pool("10.8.0.0/24", "10.8.0.1", "10.8.0.1", 2)

    assert pool == (
        ipaddress.IPv4Address("10.8.0.2"),
        ipaddress.IPv4Address("10.8.0.3"),
    )


def test_parse_max_clients_limits_range() -> None:
    assert parse_max_clients("1") == 1
    assert parse_max_clients("10") == 10

    with pytest.raises(argparse.ArgumentTypeError):
        parse_max_clients("0")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_max_clients("11")
