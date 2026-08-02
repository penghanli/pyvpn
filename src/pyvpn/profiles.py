from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from .auth import normalize_token, token_identifier


PROFILE_STORE_VERSION = 1
SERVER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ServerProfile:
    server_id: str
    server_host: str
    control_port: int
    token: str
    cert_fingerprint: str
    tun_name: str = "pyvpn0"
    mtu: int = 1280
    no_dns: bool = False
    bypass_ips: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", normalize_token(self.token))
        if not SERVER_ID_PATTERN.fullmatch(self.server_id):
            raise ProfileError(
                "server_id must start with a letter or digit and contain only "
                "letters, digits, dots, underscores, or hyphens"
            )
        if not self.server_host.strip() or any(char.isspace() for char in self.server_host):
            raise ProfileError("server_host must be a non-empty hostname or IP without spaces")
        if not 1 <= self.control_port <= 65535:
            raise ProfileError("control_port must be from 1 to 65535")
        if not self.token:
            raise ProfileError("token must not be empty")
        if not FINGERPRINT_PATTERN.fullmatch(self.cert_fingerprint):
            raise ProfileError("cert_fingerprint must be sha256 followed by 64 hexadecimal characters")
        if not self.tun_name.strip() or any(char.isspace() for char in self.tun_name):
            raise ProfileError("tun_name must not be empty or contain spaces")
        if not 576 <= self.mtu <= 9000:
            raise ProfileError("mtu must be from 576 to 9000")
        if any(not value.strip() for value in self.bypass_ips):
            raise ProfileError("bypass_ips must not contain empty values")

    @classmethod
    def from_dict(cls, server_id: str, value: Any) -> "ServerProfile":
        if not isinstance(value, dict):
            raise ProfileError(f"server profile {server_id!r} must be a JSON object")
        try:
            bypass_value = value.get("bypass_ips", [])
            if not isinstance(bypass_value, list):
                raise ProfileError(f"bypass_ips for {server_id!r} must be a JSON array")
            return cls(
                server_id=server_id,
                server_host=str(value["server_host"]),
                control_port=int(value.get("control_port", 8443)),
                token=str(value["token"]),
                cert_fingerprint=str(value["cert_fingerprint"]),
                tun_name=str(value.get("tun_name", "pyvpn0")),
                mtu=int(value.get("mtu", 1280)),
                no_dns=bool(value.get("no_dns", False)),
                bypass_ips=tuple(str(item) for item in bypass_value),
            )
        except KeyError as exc:
            raise ProfileError(f"server profile {server_id!r} is missing {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ProfileError(f"server profile {server_id!r} contains an invalid value") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_host": self.server_host,
            "control_port": self.control_port,
            "token": self.token,
            "cert_fingerprint": self.cert_fingerprint.lower(),
            "tun_name": self.tun_name,
            "mtu": self.mtu,
            "no_dns": self.no_dns,
            "bypass_ips": list(self.bypass_ips),
        }


@dataclass(frozen=True)
class ProfileStore:
    active_server_id: str | None
    servers: dict[str, ServerProfile]


def load_profile_store(path: Path, *, allow_missing: bool = False) -> ProfileStore:
    if not path.exists():
        if allow_missing:
            return ProfileStore(active_server_id=None, servers={})
        raise ProfileError(f"server profile file does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProfileError(f"could not read server profile file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"server profile file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfileError("server profile file must contain a JSON object")
    if value.get("version") != PROFILE_STORE_VERSION:
        raise ProfileError(
            f"unsupported server profile version: {value.get('version')!r}; "
            f"expected {PROFILE_STORE_VERSION}"
        )
    raw_servers = value.get("servers")
    if not isinstance(raw_servers, dict):
        raise ProfileError("servers must be a JSON object keyed by server_id")
    servers = {
        str(server_id): ServerProfile.from_dict(str(server_id), profile)
        for server_id, profile in raw_servers.items()
    }
    active_value = value.get("active_server_id")
    active_server_id = str(active_value) if active_value is not None else None
    if active_server_id is not None and active_server_id not in servers:
        raise ProfileError(f"active server_id does not exist: {active_server_id}")
    return ProfileStore(active_server_id=active_server_id, servers=servers)


def save_profile_store(path: Path, store: ProfileStore) -> None:
    if store.active_server_id is not None and store.active_server_id not in store.servers:
        raise ProfileError(f"active server_id does not exist: {store.active_server_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PROFILE_STORE_VERSION,
        "active_server_id": store.active_server_id,
        "servers": {
            server_id: profile.to_dict()
            for server_id, profile in sorted(store.servers.items())
        },
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def add_profile(
    path: Path,
    profile: ServerProfile,
    *,
    replace: bool = False,
    make_active: bool = False,
) -> ProfileStore:
    _require_printable_token(profile.token)
    store = load_profile_store(path, allow_missing=True)
    if profile.server_id in store.servers and not replace:
        raise ProfileError(
            f"server_id already exists: {profile.server_id}; pass --replace to update it"
        )
    servers = dict(store.servers)
    servers[profile.server_id] = profile
    active_server_id = store.active_server_id
    if active_server_id is None or make_active:
        active_server_id = profile.server_id
    updated = ProfileStore(active_server_id=active_server_id, servers=servers)
    save_profile_store(path, updated)
    return updated


def select_profile(path: Path, server_id: str) -> ProfileStore:
    store = load_profile_store(path)
    if server_id not in store.servers:
        raise ProfileError(f"unknown server_id: {server_id}")
    updated = ProfileStore(active_server_id=server_id, servers=dict(store.servers))
    save_profile_store(path, updated)
    return updated


def update_profile_token(path: Path, server_id: str | None, token: str) -> ServerProfile:
    token = normalize_token(token)
    _require_printable_token(token)
    store = load_profile_store(path)
    selected_id = server_id or store.active_server_id
    if selected_id is None:
        raise ProfileError("no active server is selected; run the servers use command")
    try:
        profile = store.servers[selected_id]
    except KeyError as exc:
        raise ProfileError(f"unknown server_id: {selected_id}") from exc
    updated_profile = replace(profile, token=token)
    servers = dict(store.servers)
    servers[selected_id] = updated_profile
    save_profile_store(
        path,
        ProfileStore(active_server_id=store.active_server_id, servers=servers),
    )
    return updated_profile


def _require_printable_token(token: str) -> None:
    if any(not character.isprintable() for character in token):
        raise ProfileError("token must contain only printable characters")


def remove_profile(path: Path, server_id: str) -> ProfileStore:
    store = load_profile_store(path)
    if server_id not in store.servers:
        raise ProfileError(f"unknown server_id: {server_id}")
    servers = dict(store.servers)
    del servers[server_id]
    active_server_id = store.active_server_id
    if active_server_id == server_id:
        active_server_id = sorted(servers)[0] if servers else None
    updated = ProfileStore(active_server_id=active_server_id, servers=servers)
    save_profile_store(path, updated)
    return updated


def selected_profile(path: Path, server_id: str | None = None) -> ServerProfile:
    store = load_profile_store(path)
    selected_id = server_id or store.active_server_id
    if selected_id is None:
        raise ProfileError("no active server is selected; run the servers use command")
    try:
        return store.servers[selected_id]
    except KeyError as exc:
        raise ProfileError(f"unknown server_id: {selected_id}") from exc


def probe_latency_ms(server_host: str, control_port: int, timeout: float) -> float | None:
    started = time.perf_counter()
    try:
        with socket.create_connection((server_host, control_port), timeout=timeout):
            pass
    except OSError:
        return None
    return (time.perf_counter() - started) * 1000.0


def _masked_token(token: str) -> str:
    if len(token) <= 4:
        return "*" * len(token)
    return "*" * min(12, len(token) - 4) + token[-4:]


def _profile_lines(profile: ServerProfile, *, active: bool, show_token: bool) -> Iterable[str]:
    token_value = profile.token if show_token else _masked_token(profile.token)
    yield f"server_id: {profile.server_id}"
    yield f"active: {'yes' if active else 'no'}"
    yield f"server: {profile.server_host}:{profile.control_port}"
    yield f"cert_fingerprint: {profile.cert_fingerprint}"
    yield f"token: {token_value}"
    yield f"token_id: {token_identifier(profile.token)}"
    yield f"tun: {profile.tun_name}"
    yield f"mtu: {profile.mtu}"
    yield f"dns: {'disabled' if profile.no_dns else 'enabled'}"
    yield f"bypass_ips: {', '.join(profile.bypass_ips) if profile.bypass_ips else '-'}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage saved pyvpn server profiles")
    parser.add_argument("--file", required=True, type=Path, help="Path to servers.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List servers and TCP control latency")
    list_parser.add_argument("--timeout", type=float, default=1.5)
    list_parser.add_argument("--no-probe", action="store_true")

    show_parser = subparsers.add_parser("show", help="Print one saved server")
    show_parser.add_argument("server_id", nargs="?")
    show_parser.add_argument("--show-token", action="store_true")

    add_parser = subparsers.add_parser("add", help="Add or update a saved server")
    add_parser.add_argument("server_id")
    add_parser.add_argument("--server-host", required=True)
    add_parser.add_argument("--control-port", type=int, default=8443)
    add_parser.add_argument("--token")
    add_parser.add_argument("--cert-fingerprint", required=True)
    add_parser.add_argument("--tun", default="pyvpn0", dest="tun_name")
    add_parser.add_argument("--mtu", type=int, default=1280)
    add_parser.add_argument("--no-dns", action="store_true")
    add_parser.add_argument("--bypass-ip", action="append", default=[])
    add_parser.add_argument("--replace", action="store_true")
    add_parser.add_argument("--use", action="store_true")

    use_parser = subparsers.add_parser("use", help="Select the active server")
    use_parser.add_argument("server_id")

    token_parser = subparsers.add_parser(
        "set-token", help="Update only the shared token for a saved server"
    )
    token_parser.add_argument("server_id", nargs="?")
    token_parser.add_argument("--token")

    remove_parser = subparsers.add_parser("remove", help="Remove a saved server")
    remove_parser.add_argument("server_id")
    return parser


def _list_profiles(path: Path, *, timeout: float, no_probe: bool) -> None:
    if timeout <= 0:
        raise ProfileError("timeout must be greater than zero")
    store = load_profile_store(path)
    if not store.servers:
        print("No saved servers.")
        return
    profiles = [store.servers[server_id] for server_id in sorted(store.servers)]
    latencies: dict[str, float | None] = {}
    if no_probe:
        latencies = {profile.server_id: None for profile in profiles}
    else:
        workers = min(8, len(profiles))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                profile.server_id: executor.submit(
                    probe_latency_ms, profile.server_host, profile.control_port, timeout
                )
                for profile in profiles
            }
            latencies = {server_id: future.result() for server_id, future in futures.items()}

    print(f"{'ACTIVE':<6} {'SERVER_ID':<20} {'SERVER':<36} LATENCY")
    for profile in profiles:
        active = "*" if profile.server_id == store.active_server_id else ""
        endpoint = f"{profile.server_host}:{profile.control_port}"
        latency = latencies[profile.server_id]
        if no_probe:
            latency_text = "not tested"
        elif latency is None:
            latency_text = "unreachable"
        else:
            latency_text = f"{latency:.1f} ms"
        print(f"{active:<6} {profile.server_id:<20} {endpoint:<36} {latency_text}")


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    path = args.file.expanduser().resolve()
    try:
        if args.command == "list":
            _list_profiles(path, timeout=args.timeout, no_probe=args.no_probe)
            return
        if args.command == "show":
            store = load_profile_store(path)
            profile = selected_profile(path, args.server_id)
            print(
                "\n".join(
                    _profile_lines(
                        profile,
                        active=profile.server_id == store.active_server_id,
                        show_token=args.show_token,
                    )
                )
            )
            return
        if args.command == "add":
            token = normalize_token(
                args.token
                or os.environ.get("PYVPN_TOKEN")
                or getpass.getpass("Shared token: ")
            )
            profile = ServerProfile(
                server_id=args.server_id,
                server_host=args.server_host,
                control_port=args.control_port,
                token=token,
                cert_fingerprint=args.cert_fingerprint,
                tun_name=args.tun_name,
                mtu=args.mtu,
                no_dns=args.no_dns,
                bypass_ips=tuple(args.bypass_ip),
            )
            store = add_profile(path, profile, replace=args.replace, make_active=args.use)
            print(f"Saved server: {profile.server_id} ({profile.server_host}:{profile.control_port})")
            print(f"Active server: {store.active_server_id}")
            return
        if args.command == "set-token":
            token = normalize_token(
                args.token
                or os.environ.get("PYVPN_TOKEN")
                or getpass.getpass("Shared token: ")
            )
            profile = update_profile_token(path, args.server_id, token)
            print(f"Updated token for server: {profile.server_id}")
            print(f"Token id: {token_identifier(profile.token)}")
            return
        if args.command == "use":
            store = select_profile(path, args.server_id)
            profile = store.servers[args.server_id]
            print(f"Active server: {profile.server_id} ({profile.server_host}:{profile.control_port})")
            return
        if args.command == "remove":
            store = remove_profile(path, args.server_id)
            print(f"Removed server: {args.server_id}")
            print(f"Active server: {store.active_server_id or '-'}")
            return
        raise ProfileError(f"unsupported command: {args.command}")
    except ProfileError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
