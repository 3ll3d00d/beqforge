#!/usr/bin/env python3
"""Extract analysis signals from a video or audio file.

Produces exactly what `designer-interface.md` v1.0 §2 describes — a full-band mono mix with
LFE carried +10 dB relative to the mains, decimated to 1 kHz, plus the per-channel
decomposition — without needing beqdesigner's headless pipeline to exist. It shells out to
ffmpeg and does the mixing in numpy.

    uv run python tools/extract.py FILM.mkv --out data/

Writes `<name>.npz` holding `mono_mix`, the per-channel arrays, `fs` and `coverage`.
Load it with `beqanalyser.design.material.load`.

One ffmpeg pass decodes every channel at 1 kHz and the mix is computed afterwards. `pan` and
`aresample` are both linear, so mixing after decimation is equivalent to beqdesigner mixing
before it, and this way both signals come from the same pass.
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np

logger = logging.getLogger("extract")

ANALYSIS_FS = 1000
"""Decimated analysis rate. 500 Hz of usable bandwidth, decades above any plausible knee."""

MAIN_GAIN = 10.0 ** (-20.2 / 20.0)
LFE_GAIN = 10.0 ** (-10.2 / 20.0)
"""beqdesigner's `MAIN`/`LFE` (model/ffmpeg.py:26) — 20.2 dB of headroom, LFE +10 dB on top."""

LAYOUTS: dict[int, tuple[str, ...]] = {
    1: ("M",),
    2: ("L", "R"),
    3: ("L", "R", "LFE"),
    4: ("L", "R", "C", "LFE"),
    6: ("L", "R", "C", "LFE", "Ls", "Rs"),
    8: ("L", "R", "C", "LFE", "Lb", "Rb", "Ls", "Rs"),
}
"""Channel order ffmpeg decodes into, by channel count. Others are named positionally."""


def probe(path: Path, stream: int) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            f"a:{stream}",
            "-show_entries",
            "stream=channels,channel_layout,duration,sample_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    streams = json.loads(out.stdout).get("streams", [])
    if not streams:
        raise SystemExit(f"No audio stream a:{stream} in {path}")
    return streams[0]


def decode(path: Path, stream: int, channels: int, source_fs: int) -> np.ndarray:
    """Every channel, decimated to ANALYSIS_FS, as (samples, channels) float64.

    Material already at the analysis rate is passed through untouched rather than resampled to
    the rate it is already at.
    """
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-map", f"0:a:{stream}"]
    if source_fs != ANALYSIS_FS:
        command += ["-af", f"aresample={ANALYSIS_FS}:resampler=soxr"]
    else:
        logger.info(f"source is already at {ANALYSIS_FS} Hz; not resampling")
    out = subprocess.run(
        command + ["-f", "f64le", "-c:a", "pcm_f64le", "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(out.stdout, dtype="<f8").reshape(-1, channels)


def channel_names(count: int, layout: str | None) -> tuple[str, ...]:
    if count in LAYOUTS:
        return LAYOUTS[count]
    logger.warning(
        f"Unrecognised layout {layout!r} ({count} channels); naming positionally"
    )
    return tuple(f"c{i}" for i in range(count))


def mono_mix(samples: np.ndarray, names: tuple[str, ...]) -> np.ndarray:
    """The mix of §2: mains at MAIN_GAIN, LFE at LFE_GAIN, summed."""
    gains = np.array(
        [LFE_GAIN if n == "LFE" else MAIN_GAIN for n in names], dtype=np.float64
    )
    return samples @ gains


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, default=Path("."))
    parser.add_argument("--stream", type=int, default=0, help="audio stream index")
    parser.add_argument("--name", help="output basename (default: the source stem)")
    parser.add_argument(
        "--excerpt",
        action="store_true",
        help="mark as an excerpt rather than the complete programme",
    )
    parser.add_argument(
        "--mono-only",
        action="store_true",
        help="drop the per-channel arrays, roughly halving the file",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    info = probe(args.source, args.stream)
    count = int(info["channels"])
    names = channel_names(count, info.get("channel_layout"))
    logger.info(
        f"{args.source.name}: {count}ch {info.get('channel_layout')} -> {names}"
    )

    samples = decode(args.source, args.stream, count, int(info["sample_rate"]))
    duration_s = len(samples) / ANALYSIS_FS
    logger.info(f"decoded {duration_s / 60:.1f} minutes at {ANALYSIS_FS} Hz")

    # float32 for storage only; a 24-bit source has nothing like that much dynamic range,
    # and it halves the file. Loading widens it back to float64 for the contract.
    payload = {
        "mono_mix": mono_mix(samples, names).astype(np.float32),
        "fs": np.int32(ANALYSIS_FS),
        "coverage": "excerpt" if args.excerpt else "complete_programme",
        "layout": np.array(names),
    }
    if not args.mono_only:
        for i, name in enumerate(names):
            payload[f"channel_{name}"] = samples[:, i].astype(np.float32)

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.name or args.source.stem}.npz"
    np.savez_compressed(target, **payload)
    logger.info(f"wrote {target} ({target.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
