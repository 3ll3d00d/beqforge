"""Current fitter vs greedy placement, on every real target.

Compared end to end — `fit_minimal_biquads` against `greedy_fit` — because the point of greedy
placement is that it does not need the tier escalation or the shelf/peak enumeration around it.
Both are then pruned and drift-screened identically, so what is compared is a publishable
cascade against a publishable cascade.
"""

import glob
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import beqforge.filters as F
from beqforge.filters import Realisation

import greedy

GRID = np.logspace(math.log10(3.0), math.log10(400.0), 400)
FS = 96000.0
REAL = Realisation()
BAND = (5.0, 200.0)
PLACE = (5.0, 40.0)
HERE = os.path.dirname(__file__)


def screen(specs, residual, target):
    """Prune and drift-screen, the way fit_minimal_biquads does, so both sides are publishable."""
    specs, residual = F._prune((specs, residual), target, GRID, FS, BAND, 1.0)
    ok = F._publishable(specs, residual, GRID, REAL, 3.0)
    return specs, residual, ok


rows = []
for path in sorted(glob.glob(f"{HERE}/*.npy")):
    name = os.path.basename(path)[:-4]
    target = np.load(path)

    F.PARALLEL_FITS = False
    F.FIT_STATS.reset()
    t = time.perf_counter()
    de_specs, de_res = F.fit_minimal_biquads(
        target,
        GRID,
        FS,
        4,
        0.5,
        band_hz=BAND,
        placement_band_hz=PLACE,
        max_gain_db=26.0,
        realisation=REAL,
        seeds=(0, 1),
        max_drift_db=3.0,
    )
    de_time = time.perf_counter() - t
    de_ev = F.FIT_STATS.cost_evaluations
    de_ok = F._publishable(de_specs, de_res, GRID, REAL, 3.0)

    g_specs, g_res, g_time, g_ev = greedy.greedy_fit(
        target,
        GRID,
        FS,
        4,
        0.5,
        band_hz=BAND,
        placement_band_hz=PLACE,
        max_gain_db=26.0,
        realisation=REAL,
    )
    g_specs, g_res, g_ok = screen(g_specs, g_res, target)

    rows.append(
        (
            name,
            de_res,
            de_ev,
            de_time,
            len(de_specs),
            de_ok,
            g_res,
            g_ev,
            g_time,
            len(g_specs),
            g_ok,
        )
    )
    print(
        f"{name:34s} DE {de_res:7.3f} {de_ev:9,d}ev {de_time:6.1f}s {len(de_specs)}s"
        f"{'' if de_ok else '!'}  |  greedy {g_res:7.3f} {g_ev:8,d}ev {g_time:6.1f}s "
        f"{len(g_specs)}s{'' if g_ok else '!'}",
        flush=True,
    )

print()
de_ev = sum(r[2] for r in rows)
g_ev = sum(r[7] for r in rows)
de_t = sum(r[3] for r in rows)
g_t = sum(r[8] for r in rows)
print(f"{'evaluations':20s}{de_ev:12,d}{g_ev:12,d}   {de_ev / g_ev:.0f}x")
print(f"{'seconds':20s}{de_t:12,.0f}{g_t:12,.0f}   {de_t / g_t:.0f}x")
worse = [r for r in rows if r[6] > r[1] + 0.05]
better = [r for r in rows if r[6] < r[1] - 0.05]
print(
    f"\nresidual: {len(better)} better, {len(worse)} worse, "
    f"{len(rows) - len(better) - len(worse)} the same (>0.05 dB)"
)
crossings = [r for r in rows if (r[1] <= 0.5) != (r[6] <= 0.5)]
print(f"threshold crossings (0.5 dB): {len(crossings)}")
for r in crossings:
    print(f"  {r[0]:32s} {r[1]:.3f} -> {r[6]:.3f}")
