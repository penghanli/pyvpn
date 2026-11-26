"""Shared runtime helpers for the portable Windows GUI."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping


WINDOWS_APP_VERSION = "0.1.0-r8"
LOG_MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class WorkerIdentity:
    pid: int
    created_at: int


@dataclass(frozen=True)
class WindowsAppPaths:
    executable_dir: Path
    data_dir: Path
    profiles: Path
    pid: Path
    stop: Path
    ready: Path
    log: Path
    error_log: Path


def resolve_app_paths(
    executable_dir: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> WindowsAppPaths:
    """Resolve portable storage while reusing a nearby offline-client profile."""

    env = os.environ if environment is None else environment
    executable_dir = executable_dir.resolve()
    data_override = env.get("PYVPN_GUI_DATA_DIR", "").strip()
    profile_override = env.get("PYVPN_PROFILE_FILE", "").strip()

    if profile_override:
        profiles = Path(profile_override).expanduser().resolve()
        data_dir = profiles.parent
    elif data_override:
        data_dir = Path(data_override).expanduser().resolve()
        profiles = data_dir / "servers.json"
    else:
        existing_profiles = (
            executable_dir / "pyvpn-client" / "config" / "servers.json",
            executable_dir / "config" / "servers.json",
        )
        profiles = next(
            (candidate for candidate in existing_profiles if candidate.is_file()),
            executable_dir / "pyvpn-data" / "servers.json",
        )
        data_dir = profiles.parent

    return WindowsAppPaths(
        executable_dir=executable_dir,
        data_dir=data_dir,
        profiles=profiles,
        pid=data_dir / "client.pid",
        stop=data_dir / "client.stop",
        ready=data_dir / "client.ready",
        log=data_dir / "client.log",
        error_log=data_dir / "client.err.log",
    )


def is_windows_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def native_windows_architecture(
    environment: Mapping[str, str] | None = None,
) -> str:
    env = os.environ if environment is None else environment
    architecture = env.get("PROCESSOR_ARCHITEW6432") or env.get(
        "PROCESSOR_ARCHITECTURE"
    )
    return (architecture or "unknown").lower()


def _process_creation_time(pid: int) -> int | None:
    if pid <= 0 or os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def process_is_running(identity: WorkerIdentity) -> bool:
    if identity.pid <= 0 or identity.created_at <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(identity.pid, 0)
        except OSError:
            return False
        return True
    return _process_creation_time(identity.pid) == identity.created_at


def read_pid(path: Path) -> WorkerIdentity | None:
    try:
        pid_text, created_text = path.read_text(encoding="ascii").split()
        identity = WorkerIdentity(int(pid_text), int(created_text))
    except (OSError, ValueError):
        return None
    return identity if identity.pid > 0 and identity.created_at > 0 else None


def write_pid(path: Path, pid: int) -> None:
    created_at = _process_creation_time(pid)
    if created_at is None:
        raise OSError("could not verify the Windows worker process identity")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(f"{pid} {created_at}\n", encoding="ascii")
    os.replace(temporary, path)


def remove_pid_if_current(path: Path, pid: int) -> None:
    identity = read_pid(path)
    if identity is None or identity.pid != pid or not process_is_running(identity):
        return
    try:
        path.unlink()
    except OSError:
        pass


def begin_log_session(
    path: Path, server_id: str, *, max_bytes: int = LOG_MAX_BYTES
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size >= max_bytes:
        path.replace(path.with_name(path.name + ".1"))
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"\n[{timestamp}] session started: {server_id}\n")
    return path.stat().st_size


def tail_text(
    path: Path, *, max_bytes: int = 16_384, start_offset: int = 0
) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, start_offset, size - max_bytes))
            payload = stream.read()
    except OSError:
        return ""
    return payload.decode("utf-8", errors="replace").strip()


def configure_bundled_wintun() -> Path | None:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if not bundle_dir:
        return None
    wintun_path = Path(bundle_dir) / "wintun.dll"
    if wintun_path.is_file():
        os.environ["PYVPN_WINTUN_DLL"] = str(wintun_path)
        return wintun_path
    return None


def bundled_resource(relative_path: str) -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    root = Path(bundle_dir) if bundle_dir else Path(__file__).resolve().parents[2]
    return root / relative_path


def protect_data_directory(path: Path) -> bool:
    """Limit portable secrets to SYSTEM and Administrators when possible."""

    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        return False
    result = subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode == 0
