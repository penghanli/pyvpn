from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import os
import platform
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


WINDOWS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = WINDOWS_ROOT.parent
VERSION = (WINDOWS_ROOT / "VERSION").read_text(encoding="ascii").strip()
BUILD_ROOT = REPO_ROOT / "build" / "windows_gui"
DIST_ROOT = WINDOWS_ROOT / "dist"
WINTUN_URL = "https://www.wintun.net/builds/wintun-0.14.1.zip"
WINTUN_SHA256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51"
REQUIRED_VERSIONS = {
    "PyInstaller": "6.21.0",
    "cryptography": "49.0.0",
    "cffi": "2.1.0",
    "pycparser": "3.0",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_build_host() -> None:
    if platform.system() != "Windows":
        raise SystemExit("The Windows GUI must be built on Windows.")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit(
            f"The Windows GUI requires an x64 build host; detected {platform.machine()}."
        )
    if sys.version_info[:2] != (3, 12):
        raise SystemExit(
            f"The Windows GUI requires Python 3.12; detected {platform.python_version()}."
        )
    for package, expected in REQUIRED_VERSIONS.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = "not installed"
        if actual != expected:
            raise SystemExit(f"The Windows GUI requires {package} {expected}; detected {actual}.")

    sys.path.insert(0, str(REPO_ROOT / "src"))
    from pyvpn.windows_app import WINDOWS_APP_VERSION

    if WINDOWS_APP_VERSION != VERSION:
        raise SystemExit(
            f"Version mismatch: windows_gui/VERSION={VERSION}, app={WINDOWS_APP_VERSION}"
        )


def _wintun_archive() -> Path:
    cache = BUILD_ROOT / "vendor" / "wintun-0.14.1.zip"
    candidates = [
        cache,
        *sorted((REPO_ROOT / "build" / "offline_release").glob("*/wintun-0.14.1.zip")),
    ]
    for candidate in candidates:
        if candidate.is_file() and _sha256(candidate) == WINTUN_SHA256:
            cache.parent.mkdir(parents=True, exist_ok=True)
            if candidate.resolve() != cache.resolve():
                shutil.copy2(candidate, cache)
            return cache

    cache.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {WINTUN_URL}", flush=True)
    urllib.request.urlretrieve(WINTUN_URL, cache)
    actual = _sha256(cache)
    if actual != WINTUN_SHA256:
        cache.unlink(missing_ok=True)
        raise RuntimeError(f"Wintun SHA-256 mismatch: expected {WINTUN_SHA256}, got {actual}")
    return cache


def _extract_wintun(archive: Path) -> tuple[Path, Path]:
    target = BUILD_ROOT / "vendor" / "wintun"
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(target)
    dll = target / "wintun" / "bin" / "amd64" / "wintun.dll"
    license_path = target / "wintun" / "LICENSE.txt"
    if not dll.is_file() or not license_path.is_file():
        raise RuntimeError("The official Wintun archive is missing its AMD64 DLL or license.")
    return dll, license_path


def _run_pyinstaller(wintun_dll: Path, wintun_license: Path) -> Path:
    work_dir = BUILD_ROOT / "pyinstaller"
    spec_dir = BUILD_ROOT / "spec"
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    output = DIST_ROOT / "pyvpn.exe"
    output.unlink(missing_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--uac-admin",
        "--noupx",
        "--name",
        "pyvpn",
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(REPO_ROOT / "src"),
        "--version-file",
        str(WINDOWS_ROOT / "version_info.txt"),
        "--add-binary",
        f"{wintun_dll}{os.pathsep}.",
        "--add-data",
        f"{wintun_license}{os.pathsep}licenses",
        "--add-data",
        f"{WINDOWS_ROOT / 'THIRD_PARTY_NOTICES.txt'}{os.pathsep}.",
        str(WINDOWS_ROOT / "entrypoint.py"),
    ]
    print("+ " + " ".join(str(value) for value in command), flush=True)
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    if not output.is_file():
        raise RuntimeError(f"PyInstaller output is missing: {output}")
    return output


def _pe_machine(path: Path) -> int:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError(f"Not a PE executable: {path}")
        stream.seek(0x3C)
        pe_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe_offset)
        if stream.read(4) != b"PE\0\0":
            raise RuntimeError(f"Invalid PE signature: {path}")
        return struct.unpack("<H", stream.read(2))[0]


def _manifest_text(path: Path) -> str:
    kernel32 = ctypes.windll.kernel32
    kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.LoadLibraryExW.restype = ctypes.c_void_p
    kernel32.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel32.FindResourceW.restype = ctypes.c_void_p
    kernel32.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.SizeofResource.restype = ctypes.c_uint32
    kernel32.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.LoadResource.restype = ctypes.c_void_p
    kernel32.LockResource.argtypes = [ctypes.c_void_p]
    kernel32.LockResource.restype = ctypes.c_void_p
    kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]

    module = kernel32.LoadLibraryExW(str(path), None, 0x00000002)
    if not module:
        raise RuntimeError(f"Could not load PE resources: {path}")
    try:
        resource = kernel32.FindResourceW(module, ctypes.c_void_p(1), ctypes.c_void_p(24))
        if not resource:
            raise RuntimeError("The executable does not contain a manifest resource.")
        size = kernel32.SizeofResource(module, resource)
        loaded = kernel32.LoadResource(module, resource)
        pointer = kernel32.LockResource(loaded)
        payload = ctypes.string_at(pointer, size)
    finally:
        kernel32.FreeLibrary(module)

    for encoding in ("utf-8-sig", "utf-16", "utf-16-le"):
        try:
            text = payload.decode(encoding)
        except UnicodeError:
            continue
        if "requestedExecutionLevel" in text:
            return text
    return payload.decode("latin-1", errors="replace")


def _verify_executable(path: Path) -> None:
    if _pe_machine(path) != 0x8664:
        raise RuntimeError("pyvpn.exe is not an AMD64 executable.")
    manifest = _manifest_text(path)
    if 'level="requireAdministrator"' not in manifest:
        raise RuntimeError("pyvpn.exe does not request administrator access in its manifest.")
    if path.stat().st_size < 5 * 1024 * 1024:
        raise RuntimeError("pyvpn.exe is unexpectedly small; bundled runtime may be missing.")


def _package(executable: Path, wintun_license: Path) -> Path:
    digest = _sha256(executable)
    hash_path = DIST_ROOT / "pyvpn.exe.sha256"
    hash_path.write_text(f"{digest}  pyvpn.exe\n", encoding="ascii", newline="\n")

    package_name = f"pyvpn-windows-x64-{VERSION}"
    stage = BUILD_ROOT / "package" / package_name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copy2(executable, stage / "pyvpn.exe")
    shutil.copy2(hash_path, stage / "pyvpn.exe.sha256")
    shutil.copy2(WINDOWS_ROOT / "README.md", stage / "README.md")
    shutil.copy2(WINDOWS_ROOT / "README.en.md", stage / "README.en.md")
    shutil.copy2(WINDOWS_ROOT / "THIRD_PARTY_NOTICES.txt", stage)
    shutil.copy2(REPO_ROOT / "offline_release" / "LICENSE.txt", stage / "LICENSE.txt")
    license_dir = stage / "licenses"
    license_dir.mkdir()
    shutil.copy2(wintun_license, license_dir / "WINTUN-LICENSE.txt")

    archive = DIST_ROOT / f"{package_name}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for file_path in sorted(stage.rglob("*")):
            if file_path.is_file():
                bundle.write(file_path, file_path.relative_to(stage.parent).as_posix())
    (DIST_ROOT / f"{archive.name}.sha256").write_text(
        f"{_sha256(archive)}  {archive.name}\n", encoding="ascii", newline="\n"
    )
    return archive


def main() -> None:
    _validate_build_host()
    archive = _wintun_archive()
    wintun_dll, wintun_license = _extract_wintun(archive)
    executable = _run_pyinstaller(wintun_dll, wintun_license)
    _verify_executable(executable)
    package = _package(executable, wintun_license)
    print(f"Created {executable}", flush=True)
    print(f"SHA-256: {_sha256(executable)}", flush=True)
    print(f"Created {package}", flush=True)


if __name__ == "__main__":
    main()
