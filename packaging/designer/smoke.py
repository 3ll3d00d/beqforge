#!/usr/bin/env python3
"""Exercise a built designer image: `/health`, then one design inline and one by reference.

    python3 packaging/designer/smoke.py beqforge-designer:smoke

Standard library only, so it runs on a CI host with no project environment. The image's
defaults are what is checked: it listens on 8420, takes audio by reference under /work and
keeps its stage cache in /cache. `check()` is the same check against any running server, which
`tests/test_designer_image.py` runs against an in-process one.
"""

import argparse
import base64
import hashlib
import json
import os
import pathlib
import random
import socket
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave

FS = 1000
SECONDS = 20  # noise with no rolloff: a fast, certain decline


def samples(seconds: int = SECONDS, seed: int = 0) -> list[int]:
    """Deterministic s16 noise, quiet enough never to clip."""
    rng = random.Random(seed)
    return [
        max(-32768, min(32767, round(rng.gauss(0, 0.05) * 32768)))
        for _ in range(FS * seconds)
    ]


def as_float64(pcm: list[int]) -> bytes:
    """The contract's arithmetic for an s16 column: little-endian float64 of sample / 2**15."""
    return struct.pack(f"<{len(pcm)}d", *(value / 32768.0 for value in pcm))


def write_wav(path: pathlib.Path, pcm: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(FS)
        out.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))


def inline_request(pcm: list[int]) -> dict:
    data = base64.b64encode(as_float64(pcm)).decode("ascii")
    return {
        "contract_version": "1.0",
        "fs": FS,
        "coverage": "complete_programme",
        "mono_mix": {"dtype": "float64", "shape": [len(pcm)], "data_base64": data},
        "channels": None,
        "bass_management": None,
    }


def reference_request(relative: str, pcm: list[int]) -> dict:
    return {
        **inline_request(pcm),
        "contract_version": "1.2",
        "mono_mix": {
            "dtype": "float64",
            "shape": [len(pcm)],
            "file": {"path": relative, "channel": 0},
            "sha256": hashlib.sha256(as_float64(pcm)).hexdigest(),
        },
    }


def call(
    base: str, path: str, body: dict | None = None, timeout: float = 120
) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def assert_response(status: int, body: dict, what: str) -> None:
    assert status == 200, f"{what}: HTTP {status}: {body}"
    assert (body.get("candidates") is None) != (body.get("decline_reason") is None), (
        f"{what}: exactly one of candidates and decline_reason: {body}"
    )
    said = body.get("decline_message") or json.dumps(body.get("candidates"))
    assert "beqforge" in said or body.get("candidates"), (
        f"{what}: no build named: {body}"
    )


def check(base: str, work: pathlib.Path) -> None:
    """`base` serves the designer with `work` as its shared root (as the server sees it)."""
    status, health = call(base, "/health")
    assert status == 200 and health.get("shared_root") is True, (
        f"/health: {status} {health}"
    )
    assert health.get("contract_version", "").startswith("1."), f"/health: {health}"

    pcm = samples()
    assert_response(*call(base, "/design", inline_request(pcm)), "inline")
    write_wav(work / "smoke" / "mono.wav", pcm)
    assert_response(
        *call(base, "/design", reference_request("smoke/mono.wav", pcm)), "by reference"
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_for(base: str, seconds: float = 60) -> None:
    deadline = time.time() + seconds
    while True:
        try:
            if call(base, "/health", timeout=2)[0] == 200:
                return
        except (OSError, ValueError):
            pass
        if time.time() > deadline:
            raise TimeoutError(f"{base}/health did not answer within {seconds} s")
        time.sleep(0.5)


def smoke(image: str) -> None:
    port = _free_port()
    with tempfile.TemporaryDirectory() as directory:
        work = pathlib.Path(directory)
        os.chmod(work, 0o777)  # the container's user need not be this one
        name = f"beqforge-designer-smoke-{port}"
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "-p",
                f"127.0.0.1:{port}:8420",
                "-v",
                f"{work}:/work",
                image,
            ],
            check=True,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            _wait_for(base)
            check(base, work)
            health = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            print(
                f"designer image {image}: inline and by-reference designs answered (health {health})"
            )
        finally:
            subprocess.run(["docker", "logs", name], check=False)
            subprocess.run(
                ["docker", "rm", "-f", name], check=False, capture_output=True
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("image")
    smoke(parser.parse_args().image)
