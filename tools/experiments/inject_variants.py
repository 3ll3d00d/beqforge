#!/usr/bin/env python3
"""Differential injection on a real title: known high-passes applied to every channel.

    uv run python tools/experiments/inject_variants.py data/TITLE.npz --out data/variants

Ground truth without an unfiltered original: the title *before* injection is the reference, so
whether the source was already filtered cancels. Each variant is written as an ordinary
extraction (`<title>__<spec>.npz`) with the injected filter recorded in `injected`, so the
design tool runs on it unchanged and a comparison against the original says how far the
pipeline restored what was taken away — on real programme texture, not synthetic noise.

The mix is rebuilt from the filtered channels with the extraction's own gains, so the mix and
the channels stay the same signal. Filtering is causal (`sosfilt`), like a mastering filter.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from beqforge import Alignment, HighPass  # noqa: E402
from beqforge.harness import apply_high_pass  # noqa: E402
from beqforge.material import LFE_GAIN, MAIN_GAIN  # noqa: E402

DEFAULT_SPECS = (
    # moderate: lifting to where the content ends is the right answer
    "BW2@25",
    "LR4@20",
    "LR4@25",
    "LR4@30",
    "LR4@35",
    # steep: the protocol's leakage regime, where restoring means boosting near-noise
    "BW8@30",
    "BW12@32",
)


def parse(spec: str) -> HighPass:
    shape, corner = spec.split("@")
    alignment = (
        Alignment.LINKWITZ_RILEY if shape.startswith("LR") else Alignment.BUTTERWORTH
    )
    return HighPass(alignment, int(shape[2:]), float(corner))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("material", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/variants"))
    parser.add_argument("--specs", default=",".join(DEFAULT_SPECS))
    args = parser.parse_args()
    source = np.load(args.material, allow_pickle=True)
    fs = int(source["fs"])
    names = [str(n) for n in source["layout"]]
    args.out.mkdir(parents=True, exist_ok=True)
    for spec in args.specs.split(","):
        hp = parse(spec)
        arrays = {k: source[k] for k in source.files}
        mix = np.zeros(len(source["mono_mix"]), dtype=np.float64)
        for name in names:
            filtered = apply_high_pass(
                source[f"channel_{name}"].astype(np.float64), hp, fs
            )
            arrays[f"channel_{name}"] = filtered.astype(np.float32)
            mix += (LFE_GAIN if name == "LFE" else MAIN_GAIN) * filtered
        arrays["mono_mix"] = mix.astype(np.float32)
        arrays["injected"] = np.array(spec)
        path = args.out / f"{args.material.stem}__{spec.replace('@', '_')}.npz"
        np.savez(path, **arrays)
        print(f"wrote {path}  ({hp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
