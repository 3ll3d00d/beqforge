"""DE from scratch vs greedy-seeded DE, on the targets where greedy alone did worst."""

import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import beqforge.filters as F
from beqforge.filters import Realisation

import seeded

GRID = np.logspace(math.log10(3.0), math.log10(400.0), 400)
FS, REAL = 96000.0, Realisation()
BAND, PLACE = (5.0, 200.0), (5.0, 40.0)
HERE = os.path.dirname(__file__)
NAMES = sys.argv[1:] or [
    "test4_71__flatten",
    "test4_71__counterfactual-25dB",
    "test2_71__flatten",
    "test3_71__flatten",
]

rows = []
for name in NAMES:
    target = np.load(f"{HERE}/{name}.npy")
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
    de_t, de_ev = time.perf_counter() - t, F.FIT_STATS.cost_evaluations

    s_specs, s_res, s_t, s_ev = seeded.seeded_fit(
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
    s_specs, s_res = F._prune((s_specs, s_res), target, GRID, FS, BAND, 1.0)
    ok = F._publishable(s_specs, s_res, GRID, REAL, 3.0)
    rows.append((name, de_res, de_ev, de_t, s_res, s_ev, s_t))
    print(
        f"{name:34s} DE {de_res:7.3f} {de_ev:9,d}ev {de_t:6.1f}s {len(de_specs)}s  |  "
        f"seeded {s_res:7.3f} {s_ev:8,d}ev {s_t:6.1f}s {len(s_specs)}s"
        f"{'' if ok else ' DRIFT'}",
        flush=True,
    )

de_ev = sum(r[2] for r in rows)
s_ev = sum(r[5] for r in rows)
de_t = sum(r[3] for r in rows)
s_t = sum(r[6] for r in rows)
print(f"\nevaluations {de_ev:,} -> {s_ev:,}  ({de_ev / s_ev:.0f}x)")
print(f"seconds     {de_t:,.0f} -> {s_t:,.0f}  ({de_t / s_t:.0f}x)")
print(
    f"worse: {sum(1 for r in rows if r[4] > r[1] + 0.05)}/{len(rows)}, "
    f"better: {sum(1 for r in rows if r[4] < r[1] - 0.05)}/{len(rows)}"
)
