#!/usr/bin/env python3
"""IMPROVEMENT_PLAN T8: the tracking floor under two rules, and how stable each is.

Measured 2026-09-30 and not adopted — kept so the comparison is not rebuilt. For each title's
mix, walks the half-octave bands below its plateau as `diagnose._temporal_evidence` does and
reports the floor under

* **point**: the shipped rule, stop at the first band whose envelope correlation with the
  plateau's is below `tracking_floor`;
* **bound**: stop at the first band whose correlation less `Z` block-bootstrap standard
  errors is below it (a band counts only when tracked with confidence).

The resampled unit is a contiguous run of live samples, as `extraction._block_bootstrap_se`
resamples runs of frames. Each rule is then re-applied to `RESAMPLES` resamples of the title's
own runs, and the floor it lands on most often, with its share, is printed: a rule that
"respects the uncertainty" should land on one floor more often, not less.

    uv run python tools/experiments/t8_floor_rules.py data/*.npz
"""

import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from beqforge.diagnose import (
    DiagnoseParams,
    _octave_bands,
    mean_spectrum,
    plateau_reference,
    scene_envelope,
)
from beqforge.material import load

Z = 1.645
"""`PipelineParams.confidence_z`, the evidence ceiling's yardstick."""

RESAMPLES = 400
SE_REPLICATES = 200


def _correlation(stats: np.ndarray) -> np.ndarray:
    n, sx, sy, sxx, syy, sxy = stats.T
    covariance = sxy / n - sx * sy / n**2
    return covariance / np.sqrt((sxx / n - (sx / n) ** 2) * (syy / n - (sy / n) ** 2))


def title(path: str) -> str:
    params = DiagnoseParams()
    material = load(path)
    subject, fs = material.mono_mix, material.fs
    freqs, response = mean_spectrum(subject, fs)
    band = (freqs >= params.band_hz[0]) & (freqs <= params.band_hz[1])
    _, plateau = plateau_reference(response[band], freqs[band], params)
    reference = scene_envelope(subject, fs, plateau, params)
    live = reference > (np.percentile(reference, 99) - 30.0)
    index = np.flatnonzero(live)
    starts = np.concatenate([[0], np.flatnonzero(np.diff(index) > 1) + 1])
    x = reference[live] - reference[live].mean()
    outer = np.random.default_rng(1).integers(0, starts.size, (RESAMPLES, starts.size))
    inner = np.random.default_rng(0).integers(
        0, starts.size, (SE_REPLICATES, starts.size)
    )
    bands = _octave_bands(params.band_hz[0], plateau[0])
    point, error, resampled = [], [], []
    for low, high in bands:
        y = scene_envelope(subject, fs, (low, high), params)[live]
        y = y - y.mean()
        stats = np.stack(
            [
                np.add.reduceat(v, starts)
                for v in (np.ones_like(x), x, y, x * x, y * y, x * y)
            ],
            axis=1,
        )
        point.append(_correlation(stats.sum(axis=0)[None])[0])
        error.append(_correlation(stats[inner].sum(axis=1)).std(ddof=1))
        resampled.append(_correlation(stats[outer].sum(axis=1)))
    point, error, resampled = np.array(point), np.array(error), np.array(resampled)
    threshold = params.tracking_floor

    def floor(tracked: np.ndarray) -> float:
        for (_, high), ok in zip(bands, tracked):
            if not ok:
                return round(high, 1)
        return 0.0  # tracked to the bottom of the band

    def mode(tracked: np.ndarray) -> str:
        counts = Counter(floor(tracked[:, k]) for k in range(RESAMPLES))
        value, n = counts.most_common(1)[0]
        return f"{value} ({n / RESAMPLES:.0%})"

    by_point = mode(resampled >= threshold)
    by_bound = mode(resampled - Z * error[:, None] >= threshold)
    return (
        f"{Path(path).stem:24s} point {floor(point >= threshold):6} mode {by_point:14s}"
        f" | bound {floor(point - Z * error >= threshold):6} mode {by_bound}"
    )


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=6) as pool:
        for line in pool.map(title, sys.argv[1:]):
            print(line, flush=True)
