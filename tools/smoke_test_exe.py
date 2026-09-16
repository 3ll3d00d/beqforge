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
"""

import argparse
import base64
import http.client
import json
import subprocess
import sys
import time
from pathlib import Path

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

from beqforge import Alignment, HighPass  # noqa: E402
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


def _wait_for_health(port: int, deadline: float) -> bool:
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                conn.request("GET", "/health")
                response = conn.getresponse()
                if response.status == 200 and json.loads(response.read()) == {
                    "status": "ok"
                }:
                    return True
            finally:
                conn.close()
        except OSError:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "executable", type=Path, help="path to the built beqforge binary"
    )
    parser.add_argument("--port", type=int, default=8423)
    parser.add_argument("--startup-timeout", type=float, default=20.0)
    parser.add_argument("--request-timeout", type=float, default=90.0)
    args = parser.parse_args()

    if not args.executable.exists():
        print(f"FAIL: {args.executable} does not exist", file=sys.stderr)
        return 1

    proc = subprocess.Popen(
        [
            str(args.executable),
            "serve-designer",
            "--port",
            str(args.port),
            "--strategy",
            "flatten",
            "--quiet",
        ]
    )
    try:
        if not _wait_for_health(args.port, time.time() + args.startup_timeout):
            print("FAIL: server never came up (no /health response)", file=sys.stderr)
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
        candidate = body["candidates"][0]
        print(
            f"OK: accepted a real candidate (method={candidate['method']!r}, "
            f"confidence={candidate['confidence']:.2f})"
        )
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    sys.exit(main())
