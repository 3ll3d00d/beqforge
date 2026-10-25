#!/usr/bin/env python3
"""Smoke-test a packaged `beqforge` executable's `serve-designer` subcommand, end to end.

Run after `pyinstaller` builds `dist/beqforge` (or `dist/beqforge.exe` on Windows):

    uv run python tools/smoke_test_exe.py dist/beqforge

Starts the packaged binary as a subprocess and drives it over real HTTP exactly the way
beqdesigner would — a health check, then one real accepted-candidate request with a known-
injected rolloff. That second call is the one that matters: it is what actually exercises the
fitter's multiprocessing fork/spawn *inside a frozen executable*, PyInstaller's riskiest
packaging failure mode and the one platform difference (Windows defaults to 'spawn', which
re-execs the frozen binary itself) that cannot be verified by only checking `--help` or
`/health`. Exits non-zero and says why on any failure.

The request is then sent a second time: the server runs with `--cache-dir`, and the second
answer must be identical and must have come from the stage cache — the proof that a frozen
build can key the cache at all (R2a; before, `digest_of` read sources the
executable does not ship). The server refuses the cache unless every cached stage's baked
digest is present, so a hit on the analysis covers them all.

Last, the same audio is sent by reference (contract 1.2): written to float64 WAVs under the
server's `--shared-root` and named by path with each column's SHA-256. The answer must be the
same again — the proof that WAV decoding and the path checks work inside the executable.

The server runs two design workers (`--workers 2`) and must say so on `/health`. An idle
worker is taken in turn, so the three requests alternate between them: both spawned workers
design for real inside the executable, and the cache hit is one worker reusing what the other
wrote.
"""

import argparse
import base64
import gzip
import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

from beqforge import Alignment, HighPass  # noqa: E402
from beqforge.designer import DESIGN_VERSION  # noqa: E402
from beqforge.harness import apply_high_pass  # noqa: E402
from beqforge.material import LFE_GAIN  # noqa: E402


def _encode(arr: np.ndarray) -> dict:
    as_f64 = np.ascontiguousarray(arr, dtype="<f8")
    return {
        "dtype": "float64",
        "shape": list(as_f64.shape),
        "data_base64": base64.b64encode(as_f64.tobytes()).decode("ascii"),
    }


def _post(conn: http.client.HTTPConnection, path: str, body: dict) -> tuple[int, dict]:
    conn.request(
        "POST",
        path,
        body=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    response = conn.getresponse()
    return response.status, json.loads(response.read())


def _known_filter_request(duration_s: float = 150.0, seed: int = 101) -> dict:
    """A single-channel (LFE) title with a real, known Butterworth-4 rolloff injected at 24 Hz —
    the same construction `beqforge.harness.evidence_cases`' `varying_filtered` case uses, and
    `tests/test_design_designer_server.py`'s in-process equivalent.
    """
    fs = 1000
    n = int(duration_s * fs)
    rng = np.random.default_rng(seed)
    scene = np.arange(n) // (4 * fs)
    levels = np.where(scene % 3 == 0, 0.0, np.where(scene % 3 == 1, 0.06, 0.3))
    source = rng.standard_normal(n) * levels
    hp = HighPass(Alignment.BUTTERWORTH, 4, 24.0)
    low = signal.sosfilt(signal.butter(2, 35, fs=fs, output="sos"), source)
    varying = source + np.where(scene % 3 == 1, 5.0, 0.0) * low
    filtered = apply_high_pass(varying, hp, fs)
    noise = rng.standard_normal(n) * 1e-5
    samples = filtered + noise
    return {
        "contract_version": "1.0",
        "fs": fs,
        "coverage": "complete_programme",
        "mono_mix": _encode(LFE_GAIN * samples),
        "channels": {"LFE": _encode(samples)},
        "bass_management": None,
    }


def _by_reference(root: Path) -> dict:
    """`_known_filter_request`, its arrays in float64 WAVs under `root`, sent by path.

    float64 so the files hold the inline values exactly; the digest is of the decoded column.
    """
    import hashlib

    from scipy.io import wavfile

    request = _known_filter_request()

    def decode(encoded: dict) -> np.ndarray:
        return np.frombuffer(base64.b64decode(encoded["data_base64"]), dtype="<f8")

    def reference(name: str, values: np.ndarray) -> dict:
        wavfile.write(root / name, request["fs"], values)
        return {
            "dtype": "float64",
            "shape": [len(values)],
            "file": {"path": name, "channel": 0},
            "sha256": hashlib.sha256(
                np.ascontiguousarray(values, dtype="<f8").tobytes()
            ).hexdigest(),
        }

    return {
        **request,
        "mono_mix": reference("mono.wav", decode(request["mono_mix"])),
        "channels": {
            name: reference(f"{name}.wav", decode(encoded))
            for name, encoded in request["channels"].items()
        },
    }


def _wait_for_health(port: int, deadline: float) -> dict | None:
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                conn.request("GET", "/health")
                response = conn.getresponse()
                if response.status == 200:
                    health = json.loads(response.read())
                    if health.get("status") == "ok":
                        return health
            finally:
                conn.close()
        except OSError:
            pass
        time.sleep(0.5)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "executable", type=Path, help="path to the built beqforge binary"
    )
    parser.add_argument("--port", type=int, default=8423)
    # guards against a hang, not speed limits: CI runners are several times slower than a
    # desktop, a onefile build unpacks itself, and both design workers import the pipeline,
    # one after the other, before it can answer /health
    parser.add_argument("--startup-timeout", type=float, default=120.0)
    parser.add_argument("--request-timeout", type=float, default=600.0)
    args = parser.parse_args()

    if not args.executable.exists():
        print(f"FAIL: {args.executable} does not exist", file=sys.stderr)
        return 1

    records = Path(tempfile.mkdtemp(prefix="beqforge-smoke-"))
    stages = Path(tempfile.mkdtemp(prefix="beqforge-smoke-cache-"))
    shared = Path(tempfile.mkdtemp(prefix="beqforge-smoke-shared-"))
    proc = subprocess.Popen(
        [
            str(args.executable),
            "serve-designer",
            "--port",
            str(args.port),
            "--strategy",
            "flatten",
            "--record-dir",
            str(records),
            "--cache-dir",
            str(stages),
            "--shared-root",
            str(shared),
            "--workers",
            "2",
            "--quiet",
        ]
    )
    try:
        health = _wait_for_health(args.port, time.time() + args.startup_timeout)
        if health is None:
            print("FAIL: server never came up (no /health response)", file=sys.stderr)
            return 1
        if health.get("parallel") != 2:
            print(f"FAIL: /health should say parallel 2: {health}", file=sys.stderr)
            return 1
        # 1.4: the design version is the source's, whatever the packaging; the build is baked
        identity = {
            name: health.get(name)
            for name in ("design_version", "design_settings", "designer_build")
        }
        if (
            identity["design_version"] != DESIGN_VERSION
            or not identity["design_settings"]
            or not str(identity["designer_build"]).endswith("(frozen build)")
        ):
            print(
                f"FAIL: /health should say design version {DESIGN_VERSION}, its settings "
                f"and a frozen build: {health}",
                file=sys.stderr,
            )
            return 1
        print("OK: /health")

        conn = http.client.HTTPConnection(
            "127.0.0.1", args.port, timeout=args.request_timeout
        )
        try:
            status, body = _post(conn, "/design", _known_filter_request())
        finally:
            conn.close()
        if status != 200 or body.get("decline_reason") or not body.get("candidates"):
            print(
                f"FAIL: expected an accepted candidate, got {status} {body}",
                file=sys.stderr,
            )
            return 1
        if any(body.get(name) != value for name, value in identity.items()):
            print(f"FAIL: the response and /health disagree: {body}", file=sys.stderr)
            return 1
        candidate = body["candidates"][0]
        print(
            f"OK: accepted a real candidate (method={candidate['method']!r}, "
            f"confidence={candidate['confidence']:.2f})"
        )
        # a frozen build has no git checkout and no sources: the revision must be the one
        # beqforge.spec baked in, and writing a record must not need either
        commentary = candidate.get("commentary") or {}
        build = commentary.get("beqforge_revision", "")
        if not build.endswith("(frozen build)") or build.startswith("unknown"):
            print(f"FAIL: no baked build revision, got {build!r}", file=sys.stderr)
            return 1
        print(f"OK: build revision {build!r}")
        written = Path(commentary.get("run_record", ""))
        if not written.is_file():
            print(
                f"FAIL: no run record written, got {commentary.get('run_record')!r}",
                file=sys.stderr,
            )
            return 1
        print(f"OK: run record {written.name}")

        conn = http.client.HTTPConnection(
            "127.0.0.1", args.port, timeout=args.request_timeout
        )
        try:
            again_status, again = _post(conn, "/design", _known_filter_request())
        finally:
            conn.close()
        if again_status != 200 or again != body:
            print("FAIL: the repeat request answered differently", file=sys.stderr)
            return 1
        with gzip.open(written, "rt", encoding="utf-8") as handle:
            timings = json.load(handle)["timings"]
        stages_run = [name for name, _ in timings["stages"]]
        # numba falls back to numpy silently and with the same answer, so a frozen build that
        # failed to bundle it would pass everything above and only be several times slower
        if timings["fit"].get("kernel") != "numba":
            print(
                f"FAIL: the fit ran on the {timings['fit'].get('kernel')!r} kernel, "
                "not numba: the executable did not bundle it",
                file=sys.stderr,
            )
            return 1
        if "analysis/cached" not in stages_run:
            print(
                f"FAIL: the repeat request did not reuse the analysis: {stages_run}",
                file=sys.stderr,
            )
            return 1
        if not any(stages.rglob("*.json.gz")):
            print(f"FAIL: nothing cached in {stages}", file=sys.stderr)
            return 1
        print("OK: repeat request answered the same, from the stage cache")

        conn = http.client.HTTPConnection(
            "127.0.0.1", args.port, timeout=args.request_timeout
        )
        try:
            ref_status, by_ref = _post(conn, "/design", _by_reference(shared))
        finally:
            conn.close()
        if ref_status != 200 or by_ref != body:
            print(
                f"FAIL: the request by reference answered differently: {ref_status} {by_ref}",
                file=sys.stderr,
            )
            return 1
        print("OK: the same audio by reference answered the same")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        shutil.rmtree(records, ignore_errors=True)
        shutil.rmtree(stages, ignore_errors=True)
        shutil.rmtree(shared, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
