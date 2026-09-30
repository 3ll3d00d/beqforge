#!/usr/bin/env python3
"""Time a designer request cold and warm, and how much of it is the wire (IMPROVEMENT_PLAN R2a).

    systemd-inhibit --what=sleep:idle --why=timing --mode=block \\
        uv run python tools/experiments/request_timing.py data/Send_Help.npz

Starts `tools/designer_server.py` with a fresh `--cache-dir`, then POSTs one real title the way
beqdesigner does (every array float64, base64, inline) three times: cold, warm, warm. The
server logs one timing line per request — body read, JSON parse, base64 decode, design,
respond — and this reports them with the body size and the wire's share of a warm request.
That share is what decides R2b, requests by reference: they save only the read, parse and
decode, so if those are a small part of a warm request, R2b stays parked.
"""

import argparse
import base64
import http.client
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from beqforge.material import load  # noqa: E402

TIMING = re.compile(
    r"request timing: body (?P<mb>[\d.]+) MB, read (?P<read>[\d.]+) s, "
    r"parse (?P<parse>[\d.]+) s, decode (?P<decode>[\d.]+) s, "
    r"design (?P<design>[\d.]+) s, respond (?P<respond>[\d.]+) s"
)


def _encode(values: np.ndarray) -> dict:
    as_f64 = np.ascontiguousarray(values, dtype="<f8")
    return {
        "dtype": "float64",
        "shape": list(as_f64.shape),
        "data_base64": base64.b64encode(as_f64.tobytes()).decode("ascii"),
    }


def _wait_for_health(port: int, deadline: float) -> bool:
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                conn.request("GET", "/health")
                if conn.getresponse().status == 200:
                    return True
            finally:
                conn.close()
        except OSError:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("material", type=Path)
    parser.add_argument("--port", type=int, default=8431)
    args = parser.parse_args()

    m = load(args.material)
    started = time.perf_counter()
    body = json.dumps(
        {
            "contract_version": "1.0",
            "fs": m.fs,
            "coverage": m.coverage,
            "mono_mix": _encode(m.mono_mix),
            "channels": {name: _encode(v) for name, v in m.channels.items()},
            "bass_management": None,
        }
    ).encode("utf-8")
    encode_s = time.perf_counter() - started

    cache = Path(tempfile.mkdtemp(prefix="beqforge-timing-"))
    log = cache / "server.log"
    with open(log, "w") as sink:
        server = subprocess.Popen(
            [
                sys.executable,
                str(REPO / "tools/designer_server.py"),
                "--port",
                str(args.port),
                "--cache-dir",
                str(cache / "stages"),
            ],
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    try:
        if not _wait_for_health(args.port, time.time() + 60):
            print("server never came up", file=sys.stderr)
            return 1
        round_trips = []
        for _ in ("cold", "warm", "warm"):
            conn = http.client.HTTPConnection("127.0.0.1", args.port, timeout=900)
            try:
                sent = time.perf_counter()
                conn.request(
                    "POST",
                    "/design",
                    body=body,
                    headers={"Content-Type": "application/json"},
                )
                response = conn.getresponse()
                response.read()
                round_trips.append(time.perf_counter() - sent)
            finally:
                conn.close()
            if response.status != 200:
                print(f"request failed: {response.status}", file=sys.stderr)
                return 1
    finally:
        server.terminate()
        server.wait(timeout=30)
    timings = [m.groupdict() for m in TIMING.finditer(log.read_text())]
    shutil.rmtree(cache, ignore_errors=True)
    if len(timings) != 3:
        print(f"expected 3 timing lines, got {len(timings)}", file=sys.stderr)
        return 1

    print(
        f"{args.material.stem}: client-side encode {encode_s:.2f} s (beqdesigner's side)"
    )
    for label, t, trip in zip(("cold", "warm", "warm"), timings, round_trips):
        t = {k: float(v) for k, v in t.items()}
        wire = t["read"] + t["parse"] + t["decode"]
        total = wire + t["design"] + t["respond"]
        print(
            f"  {label}: round trip {trip:6.1f} s; server {total:6.1f} s = wire {wire:5.2f} "
            f"(read {t['read']:.2f}, parse {t['parse']:.2f}, decode {t['decode']:.2f}) "
            f"+ design {t['design']:6.1f} + respond {t['respond']:.2f}; "
            f"wire {100 * wire / total:4.1f}%; body {t['mb']:.0f} MB"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
