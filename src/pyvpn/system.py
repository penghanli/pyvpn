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
