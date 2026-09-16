#!/usr/bin/env python3
"""Extract analysis signals from a video or audio file.

Produces exactly what `designer-interface.md` v1.0 §2 describes — a full-band mono mix with
LFE carried +10 dB relative to the mains, decimated to 1 kHz, plus the per-channel
decomposition — without needing beqdesigner's headless pipeline to exist. It shells out to
ffmpeg and does the mixing in numpy.

    uv run python tools/extract.py FILM.mkv --out data/

Writes `<name>.npz` holding `mono_mix`, per-channel arrays, `fs`, `coverage`, decoded
`layout`, `source_layout` and `extraction_mapping` provenance. Unknown or missing layouts
are refused: channel count alone cannot identify speakers. Legacy extractions need
re-extraction or verification against their source; relabelling cannot repair a bad mix.
Load it with `beqforge.material.load`.

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

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqforge.material import LFE_GAIN, MAIN_GAIN  # noqa: E402

logger = logging.getLogger("extract")

ANALYSIS_FS = 1000
"""Decimated analysis rate. 500 Hz of usable bandwidth, decades above any plausible knee."""

# Explicit ffmpeg native channel order; never infer speaker roles from a count.
LAYOUTS: dict[str, tuple[str, ...]] = {
    "mono": ("M",),
    "stereo": ("L", "R"),
    "2.1": ("L", "R", "LFE"),
    "3.0": ("L", "R", "C"),
    "3.0(back)": ("L", "R", "Cb"),
    "4.0": ("L", "R", "C", "Cb"),
    "quad": ("L", "R", "Lb", "Rb"),
    "quad(side)": ("L", "R", "Ls", "Rs"),
    "3.1": ("L", "R", "C", "LFE"),
    "4.1": ("L", "R", "C", "LFE", "Cb"),
    "5.0": ("L", "R", "C", "Lb", "Rb"),
    "5.0(side)": ("L", "R", "C", "Ls", "Rs"),
    "5.1": ("L", "R", "C", "LFE", "Lb", "Rb"),
    "5.1(side)": ("L", "R", "C", "LFE", "Ls", "Rs"),
    "6.0": ("L", "R", "C", "Cb", "Ls", "Rs"),
    "6.0(front)": ("L", "R", "Lc", "Rc", "Ls", "Rs"),
    "hexagonal": ("L", "R", "C", "Lb", "Rb", "Cb"),
    "6.1": ("L", "R", "C", "LFE", "Cb", "Ls", "Rs"),
    "6.1(back)": ("L", "R", "C", "LFE", "Lb", "Rb", "Cb"),
    "6.1(front)": ("L", "R", "LFE", "Lc", "Rc", "Ls", "Rs"),
    "7.0": ("L", "R", "C", "Lb", "Rb", "Ls", "Rs"),
    "7.0(front)": ("L", "R", "C", "Lc", "Rc", "Ls", "Rs"),
    "7.1": ("L", "R", "C", "LFE", "Lb", "Rb", "Ls", "Rs"),
    "7.1(wide)": ("L", "R", "C", "LFE", "Lb", "Rb", "Lc", "Rc"),
    "7.1(wide-side)": ("L", "R", "C", "LFE", "Lc", "Rc", "Ls", "Rs"),
}


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
    names = LAYOUTS.get(layout)
    if names is None:
        raise ValueError(
            f"Unsupported or ambiguous channel layout {layout!r} ({count} channels); "
            "extract from a source with an explicit supported ffmpeg layout"
        )
    if len(names) != count:
        raise ValueError(
            f"Channel layout {layout!r} defines {len(names)} channels, but stream reports {count}"
        )
    return names


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
    try:
        names = channel_names(count, info.get("channel_layout"))
    except ValueError as exc:
        parser.error(str(exc))
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
        "source_layout": info["channel_layout"],
        "extraction_mapping": "ffmpeg_layout_v1",
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
