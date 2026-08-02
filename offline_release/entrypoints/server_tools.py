from __future__ import annotations

import secrets
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pyvpn.auth import certificate_fingerprint, token_identifier
from pyvpn.cert import main as cert_main


def _usage() -> None:
    print(
        "usage:\n"
        "  pyvpn-tools token\n"
        "  pyvpn-tools token-id --env-file PATH\n"
        "  pyvpn-tools token-id --pid PID\n"
        "  pyvpn-tools cert --cert PATH --key PATH --common-name NAME [--days DAYS]\n"
        "  pyvpn-tools fingerprint --cert PATH"
    )


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        _usage()
        return

    command = sys.argv[1]
    if command == "token":
        print(secrets.token_urlsafe(32))
        return
    if command == "token-id":
        if len(sys.argv) != 4 or sys.argv[2] not in {"--env-file", "--pid"}:
            raise SystemExit("usage: pyvpn-tools token-id (--env-file PATH | --pid PID)")
        if sys.argv[2] == "--env-file":
            token = _token_from_env_file(Path(sys.argv[3]))
        else:
            token = _token_from_process(int(sys.argv[3]))
        print(token_identifier(token))
        return
    if command == "cert":
        cert_main(sys.argv[2:])
        return
    if command == "fingerprint":
        if len(sys.argv) != 4 or sys.argv[2] != "--cert":
            raise SystemExit("usage: pyvpn-tools fingerprint --cert PATH")
        cert = x509.load_pem_x509_certificate(Path(sys.argv[3]).read_bytes())
        der = cert.public_bytes(serialization.Encoding.DER)
        print(certificate_fingerprint(der))
        return
    raise SystemExit(f"unknown command: {command}")


def _token_from_env_file(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("PYVPN_TOKEN="):
            return line.removeprefix("PYVPN_TOKEN=")
    raise SystemExit(f"PYVPN_TOKEN was not found in {path}")


def _token_from_process(pid: int) -> str:
    environ = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    prefix = b"PYVPN_TOKEN="
    for entry in environ:
        if entry.startswith(prefix):
            return entry.removeprefix(prefix).decode("utf-8")
    raise SystemExit(f"PYVPN_TOKEN was not found in process {pid}")


if __name__ == "__main__":
    main()
