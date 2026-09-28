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

`--noise-db 40,60,80` adds a delivery noise floor *after* the filter, one variant per level:
stationary white Gaussian noise, independent per channel, scaled so the rebuilt mix's noise
density sits that many dB below the original mix's plateau. Without it a steep stopband is
clean programme leaking through, which tracks perfectly all the way down and so looks
recoverable to any pipeline; on a real disc something sits under it. Since the noise is ours,
where the filtered programme drowns in it is known exactly (`noise_sigma`, `noise_db` and
`noise_seed` are stored), so the recoverable band is ground truth by construction.
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from beqforge import Alignment, HighPass  # noqa: E402
from beqforge.diagnose import DiagnoseParams, mean_spectrum, plateau_reference  # noqa: E402
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
    parser.add_argument(
        "--noise-db",
        default="",
        help="comma-separated levels below the mix plateau; a variant per level",
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    source = np.load(args.material, allow_pickle=True)
    fs = int(source["fs"])
    names = [str(n) for n in source["layout"]]
    gains = {n: LFE_GAIN if n == "LFE" else MAIN_GAIN for n in names}
    levels = [float(v) for v in args.noise_db.split(",") if v] or [None]
    plateau_density = (
        None if levels == [None] else mix_plateau_density(source["mono_mix"], fs)
    )
    args.out.mkdir(parents=True, exist_ok=True)
    for spec in args.specs.split(","):
        hp = parse(spec)
        filtered = {
            name: apply_high_pass(source[f"channel_{name}"].astype(np.float64), hp, fs)
            for name in names
        }
        for level in levels:
            arrays = {k: source[k] for k in source.files}
            stem = f"{args.material.stem}__{spec.replace('@', '_')}"
            channels = dict(filtered)
            if level is not None:
                # white noise of variance s² has one-sided density 2s²/fs; independent per
                # channel, so the mix's noise density is that times the sum of squared gains
                sigma = math.sqrt(
                    plateau_density
                    * 10 ** (-level / 10)
                    * fs
                    / (2 * sum(g * g for g in gains.values()))
                )
                rng = np.random.default_rng(args.seed)
                channels = {
                    n: x + sigma * rng.standard_normal(x.size)
                    for n, x in channels.items()
                }
                arrays["noise_sigma"] = np.array(sigma)
                arrays["noise_db"] = np.array(level)
                arrays["noise_seed"] = np.array(args.seed)
                stem += f"__n{level:g}"
            mix = np.zeros(len(source["mono_mix"]), dtype=np.float64)
            for name, x in channels.items():
                arrays[f"channel_{name}"] = x.astype(np.float32)
                mix += gains[name] * x
            arrays["mono_mix"] = mix.astype(np.float32)
            arrays["injected"] = np.array(spec)
            path = args.out / f"{stem}.npz"
            np.savez(path, **arrays)
            print(f"wrote {path}  ({hp}, noise {level} dB below plateau)")
    return 0


def mix_plateau_density(mix: np.ndarray, fs: int) -> float:
    """The original mix's plateau as a one-sided power density, the noise levels' datum."""
    freqs, mix_db = mean_spectrum(mix.astype(np.float64), fs)
    params = DiagnoseParams()
    level, _ = plateau_reference(mix_db, freqs, params)
    if not math.isfinite(level):
        raise SystemExit("the original mix has no plateau to set a noise level against")
    return 10 ** (level / 10)


if __name__ == "__main__":
    sys.exit(main())
