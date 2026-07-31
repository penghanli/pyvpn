from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path


def _usage() -> None:
    print(
        "usage:\n"
        "  pyvpn-client-tools resolve HOST\n"
        "  pyvpn-client-tools restore-macos-dns STATE_PATH"
    )


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        _usage()
        return
    if sys.argv[1] == "resolve":
        if len(sys.argv) != 3:
            raise SystemExit("usage: pyvpn-client-tools resolve HOST")
        print(socket.gethostbyname(sys.argv[2]))
        return
    if sys.argv[1] == "restore-macos-dns":
        if len(sys.argv) != 3:
            raise SystemExit("usage: pyvpn-client-tools restore-macos-dns STATE_PATH")
        state_path = Path(sys.argv[2])
        if not state_path.exists():
            return
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            service = str(state.get("service") or "")
            dns = state.get("dns")
            if service:
                servers = (
                    [str(item) for item in dns]
                    if isinstance(dns, list) and dns
                    else ["Empty"]
                )
                subprocess.run(
                    ["networksetup", "-setdnsservers", service, *servers],
                    check=False,
                )
        finally:
            state_path.unlink(missing_ok=True)
        return
    raise SystemExit(f"unknown command: {sys.argv[1]}")


if __name__ == "__main__":
    main()
