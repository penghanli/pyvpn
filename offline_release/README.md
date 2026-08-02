# pyvpn Offline Release

This directory builds self-contained pyvpn packages for customers who cannot
reach GitHub or PyPI. Offline client packages install into `pyvpn-client`
inside the extracted package directory and keep server profiles in a local
`config/servers.json`. Existing system-wide client installations are left
unchanged. Fresh server installs default to five simultaneous clients.

## Outputs

`offline_release/dist/` receives seven platform/role archives plus one
all-platform archive. The directory is ignored by Git.

## Build

Install the pinned build dependencies with Python 3.12:

```text
python -m pip install -r offline_release/build-requirements.txt
```

Intel macOS is the sole dependency exception. Upstream removed x86_64 macOS
support in cryptography 49.0.0, so that package uses the final supported source
release, cryptography 47.0.0, built with static OpenSSL 3:

```text
OPENSSL_STATIC=1 OPENSSL_DIR="$(brew --prefix openssl@3)" \
  python -m pip install -r offline_release/build-requirements-macos-x86_64.txt
```

Build the package matching the current operating system:

```text
python offline_release/build_package.py build --platform windows --arch x64 --role client
python offline_release/build_package.py build --platform linux --arch x86_64 --role client
python offline_release/build_package.py build --platform linux --arch x86_64 --role server
python offline_release/build_package.py build --platform macos --arch arm64 --role client
```

Assemble the all-platform archive after all seven files are present:

```text
python offline_release/build_package.py assemble
```

Verify any generated archive:

```text
python offline_release/build_package.py verify offline_release/dist/<archive>
```

Normal cross-platform builds and GitHub prereleases are produced by
`.github/workflows/offline-release.yml`.

## Release

Push `offline-v<version>` only after the matching commit is on `main`. The tag
workflow builds all seven packages and creates a prerelease:

```text
git tag offline-v0.1.0-r6
git push origin offline-v0.1.0-r6
```

Keep the release as a prerelease until Windows x64, Linux x86_64, Linux ARM64,
Intel Mac, and Apple Silicon Mac have each passed a real connect, route, DNS,
and disconnect-restoration test. Then promote the same release:

```text
gh release edit offline-v0.1.0-r6 --prerelease=false
```

Download and verify every release asset into the ignored local `dist/`:

```text
powershell -ExecutionPolicy Bypass -File offline_release/download-release.ps1
```
