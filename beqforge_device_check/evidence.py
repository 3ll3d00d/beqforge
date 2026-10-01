"""Atomic arrays, append-only attempts and a run lock; all evidence stays local."""

import hashlib
import json
import os
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

import numpy as np


def atomic_json(path: Path, value: object) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_arrays(path: Path, **arrays: np.ndarray) -> None:
    if any(np.asarray(value).dtype.hasobject for value in arrays.values()):
        raise ValueError("object/pickle arrays are not evidence")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            np.savez_compressed(file, **arrays)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def append(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, allow_nan=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


@contextmanager
def run_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".run.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError(
            "run is locked; inspect the prior process/state before recovering a stale lock"
        ) from None
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def bundle(directory: Path, output: Path, *, summary_only: bool = False) -> dict:
    """Export only registered evidence; no host paths/credentials or unrelated files."""
    registry = json.loads((directory / "files.json").read_text())
    files = []
    for relative in registry:
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory.resolve()) or path.is_symlink():
            raise ValueError("evidence path escapes run directory")
        if summary_only and path.suffix == ".npz":
            continue
        if not path.is_file() or file_hash(path) != registry[relative]:
            raise ValueError(f"missing or changed evidence: {relative}")
        files.append((relative, path))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "bundle.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "replayable": not summary_only,
                    "files": [name for name, _ in files],
                }
            ),
        )
        for name, path in files:
            archive.write(path, name)
    return {
        "files": [name for name, _ in files],
        "bytes": output.stat().st_size,
        "hash": file_hash(output),
        "replayable": not summary_only,
    }


def register(directory: Path) -> None:
    names = [
        "manifest.json",
        "bench.json",
        "run.json",
        "attempts.jsonl",
        "qualification.json",
        "source.json",
        "source-snapshot.json",
        "inventory.json",
        "report.json",
        "report.html",
    ]
    files = [directory / name for name in names if (directory / name).is_file()]
    for subdir in ("captures", "stimuli", "analysis", "transport", "charts"):
        root = directory / subdir
        if root.is_dir():
            files.extend(
                path
                for path in root.iterdir()
                if path.is_file() and path.suffix in (".npz", ".json", ".txt", ".png")
            )
    atomic_json(
        directory / "files.json",
        {str(p.relative_to(directory)): file_hash(p) for p in files},
    )
