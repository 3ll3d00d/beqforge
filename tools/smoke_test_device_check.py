"""Substantive frozen smoke test and checksum-bearing preview directory, no live signal."""

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

from beqforge_device_check.evidence import atomic_json, file_hash


def smoke(binary: Path, directory: Path, package: Path | None = None) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    result = subprocess.run(
        [str(binary.resolve()), "self-test", "--out", str(directory / "evidence")],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    payload = json.loads(result.stdout)
    if (
        not payload["passed"]
        or not all(payload["adapter_checks"].values())
        or not payload["native_portaudio"]
    ):
        raise ValueError("frozen self-test did not pass")
    from beqforge_device_check.manifest import digest

    if payload["provenance"]["implementation"] == digest({}):
        raise ValueError("frozen build lost its implementation revision")
    payload["self_test_elapsed_s"] = time.monotonic() - started
    payload["executable_sha256"] = file_hash(binary)
    payload["executable_bytes"] = binary.stat().st_size
    atomic_json(directory / "smoke.json", payload)
    (directory / "stderr.txt").write_text(result.stderr)
    if package:
        package.mkdir(parents=True, exist_ok=False)
        shutil.copy2(binary, package / binary.name)
        shutil.copy2(directory / "smoke.json", package / "smoke.json")
        shutil.copy2("docs/device-check.md", package / "device-check.md")
        shutil.copytree(
            "build/device-helper",
            package / "helper-notices",
            ignore=shutil.ignore_patterns("minidsp", "minidsp.exe"),
        )
        shutil.copy2("packaging/device-check/NOTICE.txt", package / "NOTICE.txt")
        paths = sorted(p for p in package.rglob("*") if p.is_file())
        (package / "SHA256SUMS").write_text(
            "".join(
                f"{file_hash(p)}  {p.relative_to(package).as_posix()}\n" for p in paths
            )
        )
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    print(json.dumps(smoke(args.executable, args.out, args.package), indent=2))
