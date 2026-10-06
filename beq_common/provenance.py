"""Distribution build identity, without importing any workflow package."""

import hashlib
import subprocess
import sys
from pathlib import Path

from . import __version__

BUILD_REVISION_FILE = "BUILD_REVISION"
PACKAGES = ("beq_common", "beqforge", "beqforge_device_check", "beqoptimiser")


def revision() -> str:
    root = Path(__file__).resolve().parent.parent
    if getattr(sys, "frozen", False):
        try:
            return (
                Path(__file__).parent / BUILD_REVISION_FILE
            ).read_text().strip() + " (frozen build)"
        except OSError:
            return "unknown (frozen build without BUILD_REVISION)"
    digest = hashlib.sha256()
    try:
        for package in PACKAGES:
            for path in sorted((root / package).rglob("*.py")):
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    except OSError:
        return "unknown (sources unreadable)"
    try:
        result = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--abbrev=12"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        label = result.stdout.strip() or __version__
    except (OSError, subprocess.SubprocessError):
        label = __version__
    return f"{label}+src:{digest.hexdigest()[:12]}"
