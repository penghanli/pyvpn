"""System command helpers used by platform adapters."""

from __future__ import annotations

import os
import platform
import shutil
import shlex
import subprocess
from collections.abc import Sequence

from .errors import PlatformError


def require_linux_root() -> None:
    if platform.system() != "Linux":
        raise PlatformError("this operation is only implemented on Linux")
    if os.geteuid() != 0:
        raise PlatformError("this operation must run as root")


def require_macos_root() -> None:
    if platform.system() != "Darwin":
        raise PlatformError("this operation is only implemented on macOS")
    if os.geteuid() != 0:
        raise PlatformError("this operation must run with sudo/root")


def require_windows_admin() -> None:
    if platform.system() != "Windows":
        raise PlatformError("this operation is only implemented on Windows")
    import ctypes

    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:  # noqa: BLE001
        raise PlatformError("could not determine Windows administrator status") from exc
    if not is_admin:
        raise PlatformError("this operation must run in an elevated PowerShell or terminal")


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run(
    args: Sequence[str],
    *,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        check=False,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        command = " ".join(shlex.quote(str(arg)) for arg in args)
        output = (result.stderr or result.stdout or "").strip()
        detail = f": {output}" if output else ""
        raise PlatformError(f"command failed ({result.returncode}): {command}{detail}")
    return result


def run_powershell(script: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=check,
    )
