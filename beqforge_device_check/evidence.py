"""Atomic arrays, append-only attempts and a run lock; all evidence stays local."""

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

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
    """Export registered local evidence, preserving provenance; never upload it."""
    registry = json.loads((directory / "files.json").read_text())
    files = []
    for relative in registry:
        candidate = directory / relative
        path = candidate.resolve()
        if not path.is_relative_to(directory.resolve()) or candidate.is_symlink():
            raise ValueError("evidence path escapes run directory")
        if not evidence_name(relative):
            raise ValueError("unrecognised evidence path")
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
                    "files": {name: file_hash(path) for name, path in files},
                    "privacy": "local evidence retains bench identities and host configuration; review before sharing",
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


def evidence_name(name: str) -> bool:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or "\\" in name
        or ":" in name
        or any(p in ("..", ".") for p in path.parts)
    ):
        return False
    if path.as_posix() != name:
        return False
    if len(path.parts) == 1:
        return name in (
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
        )
    return (
        len(path.parts) == 2
        and path.parts[0] in ("captures", "stimuli", "analysis", "transport", "charts")
        and path.suffix in (".npz", ".json", ".txt", ".png")
    )


def import_bundle(
    source: Path, output: Path, *, maximum_bytes: int = 2 * 1024**3
) -> dict:
    """Validate paths, bounds and every hash before atomically exposing an offline run."""
    if output.exists():
        raise ValueError("bundle import destination must not exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".bundle-import-", dir=output.parent))
    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)) or len(names) > 100000:
                raise ValueError("duplicate or excessive archive entries")
            if sum(member.file_size for member in members) > maximum_bytes:
                raise ValueError("bundle exceeds uncompressed byte bound")
            if (
                "bundle.json" not in names
                or archive.getinfo("bundle.json").file_size > 16 * 1024**2
            ):
                raise ValueError("missing or oversized bundle manifest")
            manifest = json.loads(archive.read("bundle.json"))
            hashes = manifest.get("files")
            if manifest.get("schema_version") != 1 or not isinstance(hashes, dict):
                raise ValueError(
                    "unsupported bundle schema; per-file SHA-256 is required"
                )
            if set(names) != {*hashes, "bundle.json"}:
                raise ValueError("archive members differ from registered evidence")
            for name, expected in hashes.items():
                member = archive.getinfo(name)
                mode = member.external_attr >> 16
                if not evidence_name(name) or stat.S_ISLNK(mode) or member.is_dir():
                    raise ValueError("unsafe or unrecognised bundle path")
                if not isinstance(expected, str) or len(expected) != 64:
                    raise ValueError("invalid evidence hash")
                destination = temporary / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(member) as incoming,
                    destination.open("xb") as outgoing,
                ):
                    shutil.copyfileobj(incoming, outgoing, length=1024**2)
                if file_hash(destination) != expected:
                    raise ValueError(f"bundle evidence hash mismatch: {name}")
        atomic_json(temporary / "files.json", hashes)
        result = {
            "schema_version": 1,
            "bundle_sha256": file_hash(source),
            "replayable": manifest["replayable"],
            "files": len(hashes),
            "offline_only": True,
        }
        atomic_json(temporary / "bundle-import.json", result)
        os.rename(temporary, output)
        return result
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


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
        {p.relative_to(directory).as_posix(): file_hash(p) for p in files},
    )
