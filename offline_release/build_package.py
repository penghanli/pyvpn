from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

OFFLINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = OFFLINE_ROOT.parent
VERSION = (OFFLINE_ROOT / "VERSION").read_text(encoding="utf-8").strip()
DEFAULT_OUTPUT_DIR = OFFLINE_ROOT / "dist"
BUILD_ROOT = REPO_ROOT / "build" / "offline_release"

WINTUN_URL = "https://www.wintun.net/builds/wintun-0.14.1.zip"
WINTUN_SHA256 = "07c256185d6ee3652e09fa55c0b673e2624b565e02c4b9091c79ca7d2f24ef51"

REQUIRED_BUILD_VERSIONS = {
    "PyInstaller": "6.21.0",
    "cryptography": "49.0.0",
    "cffi": "2.1.0",
    "pycparser": "3.0",
}

BUILD_VERSION_OVERRIDES = {
    ("macos", "x86_64"): {
        "cryptography": "47.0.0",
    },
}

PACKAGE_MATRIX = (
    ("windows", "x64", "client"),
    ("linux", "x86_64", "client"),
    ("linux", "x86_64", "server"),
    ("linux", "arm64", "client"),
    ("linux", "arm64", "server"),
    ("macos", "x86_64", "client"),
    ("macos", "arm64", "client"),
)

PLATFORM_SYSTEM = {
    "windows": "Windows",
    "linux": "Linux",
    "macos": "Darwin",
}

MACHINE_ALIASES = {
    "x64": {"amd64", "x86_64"},
    "x86_64": {"amd64", "x86_64"},
    "arm64": {"arm64", "aarch64"},
}


def _package_name(target_platform: str, arch: str, role: str) -> str:
    return f"pyvpn-offline-{role}-{target_platform}-{arch}-{VERSION}"


def _archive_suffix(target_platform: str) -> str:
    return ".zip" if target_platform == "windows" else ".tar.gz"


def _archive_name(target_platform: str, arch: str, role: str) -> str:
    return _package_name(target_platform, arch, role) + _archive_suffix(target_platform)


def _run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=REPO_ROOT, env=env, check=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit() -> str:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def _dependency_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _required_build_versions(target_platform: str, arch: str) -> dict[str, str]:
    versions = REQUIRED_BUILD_VERSIONS.copy()
    versions.update(BUILD_VERSION_OVERRIDES.get((target_platform, arch), {}))
    return versions


def _openssl_version() -> str:
    try:
        from cryptography.hazmat.backends.openssl.backend import backend

        return backend.openssl_version_text()
    except Exception as exc:  # pragma: no cover - build environment diagnostic
        return f"unavailable ({type(exc).__name__})"


def _validate_build_host(target_platform: str, arch: str) -> None:
    actual_system = platform.system()
    if actual_system != PLATFORM_SYSTEM[target_platform]:
        raise SystemExit(
            f"{target_platform}/{arch} must be built on {PLATFORM_SYSTEM[target_platform]}, "
            f"not {actual_system}"
        )
    actual_machine = platform.machine().lower()
    if actual_machine not in MACHINE_ALIASES[arch]:
        raise SystemExit(
            f"{target_platform}/{arch} must be built on {arch}; detected {actual_machine}"
        )
    if sys.version_info[:2] != (3, 12):
        detected = platform.python_version()
        raise SystemExit(f"offline packages require Python 3.12; detected {detected}")
    for dependency, expected in _required_build_versions(target_platform, arch).items():
        actual = _dependency_version(dependency)
        if actual != expected:
            raise SystemExit(
                f"offline packages require {dependency} {expected}; detected {actual}"
            )


def _pyinstaller(
    *,
    entrypoint: Path,
    name: str,
    work_dir: Path,
    target_platform: str,
    arch: str,
) -> Path:
    dist_dir = work_dir / "frozen"
    pyi_work = work_dir / "pyinstaller-work" / name
    spec_dir = work_dir / "spec"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(pyi_work),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(REPO_ROOT / "src"),
    ]
    if target_platform == "macos":
        command.extend(["--target-architecture", arch])
    command.append(str(entrypoint))
    env = os.environ.copy()
    if target_platform == "macos":
        env["MACOSX_DEPLOYMENT_TARGET"] = "12.0"
    _run(command, env=env)
    output = dist_dir / name
    if not output.is_dir():
        raise RuntimeError(f"PyInstaller output is missing: {output}")
    return output


def _download_wintun(work_dir: Path) -> tuple[Path, Path]:
    archive = work_dir / "wintun-0.14.1.zip"
    if not archive.exists() or _sha256(archive) != WINTUN_SHA256:
        archive.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {WINTUN_URL}", flush=True)
        urllib.request.urlretrieve(WINTUN_URL, archive)
    actual = _sha256(archive)
    if actual != WINTUN_SHA256:
        raise RuntimeError(f"Wintun SHA-256 mismatch: expected {WINTUN_SHA256}, got {actual}")

    extract_dir = work_dir / "wintun"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(extract_dir)
    dll = extract_dir / "wintun" / "bin" / "amd64" / "wintun.dll"
    license_path = extract_dir / "wintun" / "LICENSE.txt"
    if not dll.is_file() or not license_path.is_file():
        raise RuntimeError("official Wintun archive is missing amd64 DLL or LICENSE.txt")
    return dll, license_path


def _copy_template(template_name: str, package_root: Path) -> None:
    template_dir = OFFLINE_ROOT / "templates" / template_name
    if not template_dir.is_dir():
        raise RuntimeError(f"package template is missing: {template_dir}")
    shutil.copytree(template_dir, package_root, dirs_exist_ok=True)
    shutil.copy2(OFFLINE_ROOT / "LICENSE.txt", package_root)
    shutil.copy2(OFFLINE_ROOT / "THIRD_PARTY_NOTICES.txt", package_root)


def _write_build_info(
    package_root: Path,
    *,
    target_platform: str,
    arch: str,
    role: str,
) -> None:
    values = {
        "VERSION": VERSION,
        "PLATFORM": target_platform,
        "ARCH": arch,
        "ROLE": role,
        "SOURCE_COMMIT": _source_commit(),
        "PYTHON_VERSION": platform.python_version(),
        "PYINSTALLER_VERSION": _dependency_version("PyInstaller"),
        "CRYPTOGRAPHY_VERSION": _dependency_version("cryptography"),
        "CFFI_VERSION": _dependency_version("cffi"),
        "PYCPARSER_VERSION": _dependency_version("pycparser"),
        "OPENSSL_VERSION": _openssl_version(),
        "BUILD_SYSTEM": platform.system(),
        "BUILD_RELEASE": platform.release(),
        "BUILD_MACHINE": platform.machine(),
    }
    if target_platform == "linux":
        values["GLIBC_BASELINE"] = "2.28"
    if target_platform == "macos":
        values["MACOS_DEPLOYMENT_TARGET"] = "12.0"
    metadata = "".join(f"{key}={value}\n" for key, value in values.items())
    (package_root / "PACKAGE-METADATA").write_text(metadata, encoding="utf-8", newline="\n")
    build_info = "\n".join(
        [
            f"pyvpn offline release {VERSION}",
            f"target: {target_platform}/{arch}/{role}",
            f"source commit: {values['SOURCE_COMMIT']}",
            f"Python: {values['PYTHON_VERSION']}",
            f"PyInstaller: {values['PYINSTALLER_VERSION']}",
            f"cryptography: {values['CRYPTOGRAPHY_VERSION']}",
            f"cffi: {values['CFFI_VERSION']}",
            f"pycparser: {values['PYCPARSER_VERSION']}",
            f"OpenSSL: {values['OPENSSL_VERSION']}",
            (
                "build host: "
                f"{values['BUILD_SYSTEM']} {values['BUILD_RELEASE']} "
                f"{values['BUILD_MACHINE']}"
            ),
            "",
        ]
    )
    (package_root / "BUILD-INFO.txt").write_text(build_info, encoding="utf-8", newline="\n")


def _make_executable(path: Path) -> None:
    if path.exists():
        path.chmod(path.stat().st_mode | 0o111)


def _write_manifest(package_root: Path) -> None:
    manifest_path = package_root / "SHA256SUMS"
    rows: list[str] = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(package_root).as_posix()
        rows.append(f"{_sha256(path)}  {relative}")
    manifest_path.write_text("\n".join(rows) + "\n", encoding="ascii", newline="\n")


def _verify_tree(package_root: Path) -> None:
    manifest_path = package_root / "SHA256SUMS"
    if not manifest_path.is_file():
        raise RuntimeError(f"SHA256SUMS is missing from {package_root}")
    for line in manifest_path.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        expected, separator, relative = line.partition("  ")
        if not separator or len(expected) != 64:
            raise RuntimeError(f"invalid SHA256SUMS line: {line}")
        path = package_root / Path(relative)
        if not path.is_file():
            raise RuntimeError(f"manifest file is missing: {relative}")
        actual = _sha256(path)
        if actual != expected:
            raise RuntimeError(
                f"SHA-256 mismatch for {relative}: expected {expected}, got {actual}"
            )


def _create_zip(source_root: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zf:
        for path in sorted(source_root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(source_root.parent).as_posix())


def _root_owned_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    return info


def _create_tar(source_root: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz", compresslevel=9) as tf:
        tf.add(
            source_root,
            arcname=source_root.name,
            recursive=True,
            filter=_root_owned_tar_info,
        )


def _extract_archive(archive_path: Path, destination: Path) -> Path:
    if archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(destination, filter="data")
    elif archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(destination)
    else:
        raise RuntimeError(f"unsupported archive type: {archive_path}")
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError(f"archive must contain one root directory: {archive_path}")
    return roots[0]


def verify_archive(archive_path: Path) -> None:
    archive_path = archive_path.resolve()
    with tempfile.TemporaryDirectory(prefix="pyvpn-offline-verify-") as temp:
        package_root = _extract_archive(archive_path, Path(temp))
        _verify_tree(package_root)
    print(f"Verified {archive_path}", flush=True)


def build_package(
    *,
    target_platform: str,
    arch: str,
    role: str,
    output_dir: Path,
) -> Path:
    if (target_platform, arch, role) not in PACKAGE_MATRIX:
        raise SystemExit(f"unsupported package target: {target_platform}/{arch}/{role}")
    _validate_build_host(target_platform, arch)

    package_name = _package_name(target_platform, arch, role)
    work_dir = BUILD_ROOT / package_name
    if work_dir.exists():
        shutil.rmtree(work_dir)
    package_root = work_dir / "stage" / package_name
    package_root.mkdir(parents=True)

    template_name = f"{target_platform}-{role}"
    _copy_template(template_name, package_root)
    payload = package_root / "payload"
    payload.mkdir()

    if role == "client":
        frozen = _pyinstaller(
            entrypoint=OFFLINE_ROOT / "entrypoints" / "client.py",
            name="pyvpn-client",
            work_dir=work_dir,
            target_platform=target_platform,
            arch=arch,
        )
        shutil.copytree(frozen, payload / "pyvpn-client")
        if target_platform == "macos":
            client_tools = _pyinstaller(
                entrypoint=OFFLINE_ROOT / "entrypoints" / "client_tools.py",
                name="pyvpn-client-tools",
                work_dir=work_dir,
                target_platform=target_platform,
                arch=arch,
            )
            shutil.copytree(client_tools, payload / "pyvpn-client-tools")
        if target_platform == "windows":
            wintun_dll, wintun_license = _download_wintun(work_dir)
            shutil.copy2(wintun_dll, payload / "pyvpn-client" / "wintun.dll")
            license_dir = package_root / "licenses"
            license_dir.mkdir()
            shutil.copy2(wintun_license, license_dir / "WINTUN-LICENSE.txt")
    else:
        server = _pyinstaller(
            entrypoint=OFFLINE_ROOT / "entrypoints" / "server.py",
            name="pyvpn-server",
            work_dir=work_dir,
            target_platform=target_platform,
            arch=arch,
        )
        tools = _pyinstaller(
            entrypoint=OFFLINE_ROOT / "entrypoints" / "server_tools.py",
            name="pyvpn-tools",
            work_dir=work_dir,
            target_platform=target_platform,
            arch=arch,
        )
        shutil.copytree(server, payload / "pyvpn-server")
        shutil.copytree(tools, payload / "pyvpn-tools")

    _write_build_info(
        package_root,
        target_platform=target_platform,
        arch=arch,
        role=role,
    )
    for script in package_root.glob("*.sh"):
        _make_executable(script)
    for executable in payload.rglob("pyvpn-*"):
        if executable.is_file() and executable.suffix != ".exe":
            _make_executable(executable)
    _write_manifest(package_root)
    _verify_tree(package_root)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / _archive_name(target_platform, arch, role)
    archive_path.unlink(missing_ok=True)
    if target_platform == "windows":
        _create_zip(package_root, archive_path)
    else:
        _create_tar(package_root, archive_path)
    verify_archive(archive_path)
    print(f"Created {archive_path}", flush=True)
    return archive_path


def _find_unique_archive(input_dir: Path, filename: str) -> Path:
    matches = [path for path in input_dir.rglob(filename) if path.is_file()]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one {filename} under {input_dir}, found {len(matches)}"
        )
    return matches[0]


def assemble_all(input_dir: Path, output_dir: Path) -> Path:
    package_name = f"pyvpn-offline-all-{VERSION}"
    work_dir = BUILD_ROOT / package_name
    if work_dir.exists():
        shutil.rmtree(work_dir)
    package_root = work_dir / "stage" / package_name
    package_root.mkdir(parents=True)
    _copy_template("all", package_root)

    source_archives: list[Path] = []
    for target_platform, arch, role in PACKAGE_MATRIX:
        filename = _archive_name(target_platform, arch, role)
        source = _find_unique_archive(input_dir, filename)
        source_archives.append(source)
        shutil.copy2(source, package_root / filename)

    _write_manifest(package_root)
    _verify_tree(package_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    release_archives: list[Path] = []
    for source in source_archives:
        destination = output_dir / source.name
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        release_archives.append(destination)
    archive_path = output_dir / f"{package_name}.zip"
    archive_path.unlink(missing_ok=True)
    _create_zip(package_root, archive_path)
    verify_archive(archive_path)
    release_archives.append(archive_path)
    release_manifest = output_dir / "SHA256SUMS"
    release_manifest.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in sorted(release_archives)),
        encoding="ascii",
        newline="\n",
    )
    print(f"Created {archive_path}", flush=True)
    return archive_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and verify pyvpn offline packages")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--platform", choices=sorted(PLATFORM_SYSTEM), required=True)
    build.add_argument("--arch", choices=sorted(MACHINE_ALIASES), required=True)
    build.add_argument("--role", choices=["client", "server"], required=True)
    build.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    assemble = subparsers.add_parser("assemble")
    assemble.add_argument("--input-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    assemble.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    verify = subparsers.add_parser("verify")
    verify.add_argument("archive", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "build":
        build_package(
            target_platform=args.platform,
            arch=args.arch,
            role=args.role,
            output_dir=args.output_dir,
        )
    elif args.command == "assemble":
        assemble_all(args.input_dir, args.output_dir)
    else:
        verify_archive(args.archive)


if __name__ == "__main__":
    main()
