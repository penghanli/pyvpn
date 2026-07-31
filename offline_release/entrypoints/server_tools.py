from __future__ import annotations

import secrets
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from pyvpn.auth import certificate_fingerprint
from pyvpn.cert import main as cert_main


def _usage() -> None:
    print(
        "usage:\n"
        "  pyvpn-tools token\n"
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


if __name__ == "__main__":
    main()
