"""System command helpers used by platform adapters."""

from __future__ import annotations

import os
import platform
import shutil
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
    return subprocess.run(
        list(args),
        check=check,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


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
