#!/usr/bin/env python3
"""Score injected steep-filter variants against ground truth known by construction.

    uv run python tools/experiments/score_injected.py Black_Bag Incredible_Hulk
    uv run python tools/experiments/score_injected.py Black_Bag --records SCRATCH/

For each `data/variants/<title>__<spec>[__n<level>].npz` written by `inject_variants.py` that
has a run record (beside it, or in `--records`):

* **Recoverable edge.** Where the filtered programme (the no-noise control's mix, which must
  exist) stays above the injected noise density, walking down from 60 Hz. Everything below
  it is noise by construction; nothing there can be recovered.
* **Shortfall.** Inside the recoverable band, the original title's own corrected curve
  minus the variant's, each relative to its own reference (median and worst, dB).
* **Gain where noise dominates.** The frozen protocol's measure: the most the accepted
  cascade boosts any bin where our noise's density exceeds the filtered programme's.
* **Noise after correction.** Where that gain lands: the injected floor sits `noise_db` below
  the plateau at every bin, so the corrected noise is `gain - noise_db` relative to it. The
  gain alone is not a listening claim — +17 dB into a floor 80 dB down leaves it 63 dB down,
  into one 40 dB down leaves it 23 dB down (IMPROVEMENT_PLAN priority 3).

Truth never reaches the pipeline; this only reads what it produced.
"""

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from beqforge.diagnose import (  # noqa: E402
    DiagnoseParams,
    mean_spectrum,
    plateau_reference,
)

TOP_HZ = 60.0
BOTTOM_HZ = 5.0


def _record(path: Path):
    return json.load(gzip.open(path)) if path.exists() else None


def _accepted(record):
    if record is None or not record.get("accepted"):
        return None
    return next(c for c in record["candidates"] if c["label"] == record["accepted"])


def _smooth(freqs: np.ndarray, db: np.ndarray, width_octaves: float = 1 / 6):
    out = np.empty_like(db)
    for i, f in enumerate(freqs):
        near = (freqs >= f * 2 ** (-width_octaves / 2)) & (
            freqs <= f * 2 ** (width_octaves / 2)
        )
        out[i] = 10 * np.log10(np.mean(10 ** (db[near] / 10)))
    return out


def _spectrum(path: Path) -> tuple[np.ndarray, np.ndarray]:
    loaded = np.load(path)
    return mean_spectrum(loaded["mono_mix"].astype(np.float64), int(loaded["fs"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("titles", nargs="+")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument(
        "--records",
        type=Path,
        help="where the variants' run records are (default: beside the variants)",
    )
    args = parser.parse_args()
    variants = args.data / "variants"
    records = args.records or variants
    for title in args.titles:
        original = _accepted(_record(args.data / f"{title}.run.json.gz"))
        if original is None:
            print(f"{title}: the original has no accepted candidate to compare against")
            continue
        of = np.array(original["correction"]["freqs"])
        target_after = np.array(original["correction"]["after_db"], dtype=float)
        f, s = _spectrum(args.data / f"{title}.npz")
        plateau, _ = plateau_reference(s, f, DiagnoseParams())
        for path in sorted(variants.glob(f"{title}__*.npz")):
            name = path.stem
            record = _record(records / f"{name}.run.json.gz")
            if record is None:
                continue
            spec, _, level = name.split("__", 1)[1].partition("__n")
            noise_db = float(level) if level else None
            edge, dominated = BOTTOM_HZ, None
            if noise_db is not None:
                control = variants / f"{title}__{spec}.npz"
                if not control.exists():
                    print(f"{name}: no control {control.name}; skipped")
                    continue
                fc, sc = _spectrum(control)
                floor = plateau - noise_db
                smoothed = _smooth(fc, sc)
                band = (fc >= BOTTOM_HZ) & (fc <= TOP_HZ)
                above = smoothed[band] > floor
                index = len(above) - 1
                while index >= 0 and above[index]:
                    index -= 1
                edge = float(fc[band][min(index + 1, len(above) - 1)])
                dominated = (fc, sc, floor)
            winner = _accepted(record)
            if winner is None:
                reasons = "; ".join(
                    f"{c['label']}: {c['verdict']['failures'][0][:60]}"
                    for c in record["candidates"]
                    if c["verdict"]["failures"]
                )
                print(f"{name:<34} edge {edge:5.1f} Hz  declined  {reasons[:150]}")
                continue
            vf = np.array(winner["correction"]["freqs"])
            after = np.array(winner["correction"]["after_db"], dtype=float)
            gain = after - np.array(winner["correction"]["before_db"], dtype=float)
            inside = (vf >= edge) & (vf <= TOP_HZ)
            short = np.interp(vf, of, target_after)[inside] - after[inside]
            noisy_gain = math.nan
            noise_after = math.nan
            if dominated is not None:
                fc, sc, floor = dominated
                noisy = (
                    (np.interp(vf, fc, sc) < floor) & (vf >= BOTTOM_HZ) & (vf <= TOP_HZ)
                )
                noisy_gain = float(np.max(gain[noisy])) if noisy.any() else 0.0
                # the injected floor is white at `noise_db` below the plateau
                noise_after = noisy_gain - noise_db
            print(
                f"{name:<34} edge {edge:5.1f} Hz  {winner['label']:<20} "
                f"peak {np.max(gain):5.1f} dB  shortfall median {np.median(short):5.1f} "
                f"worst {np.max(short):5.1f} dB  gain where noise dominates "
                f"{noisy_gain:5.1f} dB, leaving it {noise_after:6.1f} dB re plateau"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
