"""Fetch a hash-pinned, target-native miniDSP helper and its upstream licence."""

import argparse
import hashlib
import platform
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from beqforge_device_check.engines import MINIDSP_VERSION
from beqforge_device_check.evidence import atomic_bytes, atomic_json, file_hash

ASSETS = {
    "linux-x86_64": (
        "minidsp.x86_64-unknown-linux-gnu.tar.gz",
        "37f9d1be8e41fd506fca7ce006d80a73bd83b954082ac6642162e2ba67e38fb2",
    ),
    "macos-arm64": (
        "minidsp.arm64-apple-darwin.tar.gz",
        "8fd92b7fccd8684eee44962d04f8b250e45d6b583b0284f79e92adeb6bc6bea3",
    ),
    "macos-x86_64": (
        "minidsp.x86_64-apple-darwin.tar.gz",
        "2c0630404ea6d408dd90c2c5506cd9992977a3c56fe7932087bdb9e9a6371692",
    ),
    "windows-x86_64": (
        "minidsp.x86_64-pc-windows-msvc.zip",
        "516e27e1cc1a8752ba67fa99cd6023eda14a24cbfd8e0d2809e2c54d13691dda",
    ),
}


def host_target() -> str:
    system = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}[
        platform.system()
    ]
    machine = {
        "AMD64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }[platform.machine()]
    return f"{system}-{machine}"


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def prepare(target: str, directory: Path, cache: Path) -> dict:
    if target != host_target():
        raise ValueError(
            f"build on target architecture: requested {target}, running {host_target()}"
        )
    asset, expected = ASSETS[target]
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / asset
    url = f"https://github.com/mrene/minidsp-rs/releases/download/v{MINIDSP_VERSION}/{asset}"
    if not archive.exists():
        atomic_bytes(archive, download(url))
    if file_hash(archive) != expected:
        raise ValueError("helper archive SHA-256 mismatch")
    name = "minidsp.exe" if target.startswith("windows") else "minidsp"
    # Read only one known member; never extract archive paths onto the filesystem.
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as source:
            data = source.read(name)
    else:
        with tarfile.open(archive, "r:gz") as source:
            member = source.getmember(name)
            if not member.isfile():
                raise ValueError("helper member is not a regular file")
            with source.extractfile(member) as file:
                data = file.read()
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / name
    atomic_bytes(binary, data)
    binary.chmod(0o755)
    import subprocess

    version = subprocess.run(
        [str(binary.resolve()), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if version != f"minidsp {MINIDSP_VERSION}":
        raise ValueError(f"unexpected native helper version: {version}")
    licence_url = (
        f"https://raw.githubusercontent.com/mrene/minidsp-rs/v{MINIDSP_VERSION}/LICENSE"
    )
    licence = cache / f"minidsp-{MINIDSP_VERSION}-LICENSE"
    if not licence.exists():
        atomic_bytes(licence, download(licence_url))
    if b"Apache License" not in licence.read_bytes():
        raise ValueError("upstream Apache licence was not retrieved")
    shutil.copyfile(licence, directory / "minidsp-LICENSE.txt")
    result = {
        "version": version,
        "target": target,
        "archive_sha256": expected,
        "binary_sha256": hashlib.sha256(data).hexdigest(),
        "source": url,
        "licence_source": licence_url,
        "licence_sha256": file_hash(licence),
    }
    atomic_json(directory / "helper.json", result)
    if target.startswith("linux"):
        notices = directory / "native-notices"
        notices.mkdir(exist_ok=True)
        for package in (
            "libportaudio2",
            "libusb-1.0-0",
            "libudev1",
            "libgcc-s1",
            "libstdc++6",
            "libc6",
        ):
            source = Path("/usr/share/doc") / package / "copyright"
            if not source.is_file():
                raise ValueError(f"missing Linux native notice: {source}")
            shutil.copyfile(source, notices / f"{package}-copyright.txt")
        for licence in ("LGPL-2.1", "LGPL-3", "GPL-2", "GPL-3"):
            shutil.copyfile(
                Path("/usr/share/common-licenses") / licence, notices / f"{licence}.txt"
            )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=ASSETS, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.target, args.out, args.cache))
