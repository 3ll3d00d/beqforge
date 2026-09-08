import math
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import beqanalyser.design.filters as F
from beqanalyser.design.filters import Realisation
import structure

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
    d_specs, d_res = F.fit_minimal_biquads(
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
    d_t, d_ev = time.perf_counter() - t, F.FIT_STATS.cost_evaluations
    s_specs, s_res, s_t, s_ev = structure.structure_fit(
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
    ok = F._publishable(s_specs, s_res, GRID, REAL, 3.0)
    rows.append((name, d_res, d_ev, d_t, s_res, s_ev, s_t))
    print(
        f"{name:34s} DE {d_res:7.3f} {d_ev:9,d}ev {d_t:6.1f}s {len(d_specs)}s  |  "
        f"structure {s_res:7.3f} {s_ev:8,d}ev {s_t:6.1f}s {len(s_specs)}s"
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
    f"better: {sum(1 for r in rows if r[4] < r[1] - 0.05)}/{len(rows)}, "
    f"crossings: {sum(1 for r in rows if (r[1] <= 0.5) != (r[4] <= 0.5))}"
)
