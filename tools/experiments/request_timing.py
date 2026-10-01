#!/usr/bin/env python3
"""Time designer requests cold and warm, and how much of each is the wire (IMPROVEMENT_PLAN R2a/R2b).

    systemd-inhibit --what=sleep:idle --why=timing --mode=block \\
        uv run python tools/experiments/request_timing.py data/Send_Help.npz
    systemd-inhibit --what=sleep:idle --why=timing --mode=block \\
        uv run python tools/experiments/request_timing.py --reference "<work_dir>/<title>"

Starts `tools/designer_server.py` with a fresh `--cache-dir` and POSTs one real title. The
server logs one timing line per request — body read, JSON parse, decode, design, respond —
and this reports them with the body size and what the caller spent building the body.

With a material `.npz`: inline (every array float64, base64), cold then warm twice.

With `--reference`, a beqdesigner title folder (`mono.wav`, `multichannel.wav`) is sent both
ways against one server whose `--shared-root` is the folder's parent: inline cold, to warm the
cache, then inline and by reference warm, twice each. The caller's side is timed too —
base64 and JSON inline, the SHA-256 of each column by reference — so the forms compare end to
end, as beqdesigner's own table does (`design/designer-by-reference.md` §2). Loading the WAVs
is left out on both sides: the caller does it either way.
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
from beqforge.reference import digest, read_column  # noqa: E402

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


def _body(fs: int, coverage: str, mono: dict, channels: dict) -> bytes:
    return json.dumps(
        {
            "contract_version": "1.2",
            "fs": fs,
            "coverage": coverage,
            "mono_mix": mono,
            "channels": channels,
            "bass_management": None,
        }
    ).encode("utf-8")


def _inline_runs(material: Path):
    m = load(material)
    started = time.perf_counter()
    body = _body(
        m.fs,
        m.coverage,
        _encode(m.mono_mix),
        {name: _encode(v) for name, v in m.channels.items()},
    )
    caller = time.perf_counter() - started
    return [("cold", body, caller), ("warm", body, caller), ("warm", body, caller)]


def _both_forms(folder: Path):
    """Inline and by-reference bodies for one beqdesigner title, and each caller's cost."""
    from scipy.io import wavfile

    rate, frames = wavfile.read(folder / "multichannel.wav")
    opened: dict = {}
    mono = read_column(folder / "mono.wav", 0, rate, "mono_mix", opened)
    columns = {
        f"ch{i}": read_column(folder / "multichannel.wav", i, rate, f"ch{i}", opened)
        for i in range(frames.shape[1])
    }
    started = time.perf_counter()
    inline = _body(
        rate,
        "complete_programme",
        _encode(mono),
        {k: _encode(v) for k, v in columns.items()},
    )
    inline_s = time.perf_counter() - started

    def ref(path: str, channel: int, values: np.ndarray) -> dict:
        return {
            "dtype": "float64",
            "shape": [len(values)],
            "file": {"path": f"{folder.name}/{path}", "channel": channel},
            "sha256": digest(values),
        }

    started = time.perf_counter()
    by_reference = _body(
        rate,
        "complete_programme",
        ref("mono.wav", 0, mono),
        {k: ref("multichannel.wav", i, v) for i, (k, v) in enumerate(columns.items())},
    )
    reference_s = time.perf_counter() - started
    runs = [("inline cold", inline, inline_s)]
    for _ in range(2):
        runs += [
            ("inline warm", inline, inline_s),
            ("reference warm", by_reference, reference_s),
        ]
    return runs


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
    parser.add_argument("material", type=Path, nargs="?")
    parser.add_argument(
        "--reference",
        type=Path,
        help="a beqdesigner title folder: send it inline and by reference",
    )
    parser.add_argument("--port", type=int, default=8431)
    args = parser.parse_args()
    if (args.material is None) == (args.reference is None):
        parser.error("give a material .npz or --reference, one of the two")
    if args.reference is None:
        name, runs, shared_root = args.material.stem, _inline_runs(args.material), None
    else:
        name, runs = args.reference.name, _both_forms(args.reference)
        shared_root = args.reference.parent

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
                *(["--shared-root", str(shared_root)] if shared_root else []),
            ],
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    try:
        if not _wait_for_health(args.port, time.time() + 60):
            print("server never came up", file=sys.stderr)
            return 1
        round_trips = []
        for _, body, _ in runs:
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
                answer = response.read()
                round_trips.append(time.perf_counter() - sent)
            finally:
                conn.close()
            if response.status != 200:
                print(
                    f"request failed: {response.status} {answer[:300]}", file=sys.stderr
                )
                return 1
    finally:
        server.terminate()
        server.wait(timeout=30)
    timings = [m.groupdict() for m in TIMING.finditer(log.read_text())]
    shutil.rmtree(cache, ignore_errors=True)
    if len(timings) != len(runs):
        print(f"expected {len(runs)} timing lines, got {len(timings)}", file=sys.stderr)
        return 1

    print(name)
    for (label, _, caller), t, trip in zip(runs, timings, round_trips):
        t = {k: float(v) for k, v in t.items()}
        wire = t["read"] + t["parse"] + t["decode"]
        total = wire + t["design"] + t["respond"]
        print(
            f"  {label:<14s} caller {caller:5.2f} s + wire {wire:5.2f} s "
            f"(read {t['read']:.2f}, parse {t['parse']:.2f}, decode {t['decode']:.2f}) "
            f"= {caller + wire:5.2f} s; design {t['design']:6.1f} s; server {total:6.1f} s; "
            f"round trip {trip:6.1f} s; body {t['mb']:.1f} MB"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
