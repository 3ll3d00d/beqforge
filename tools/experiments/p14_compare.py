"""Current fitter vs the P14 surrogate, on every real target, through identical machinery."""

import glob
import math
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import beqanalyser.design.filters as F
from beqanalyser.design.filters import Realisation
import surrogate

GRID = np.logspace(math.log10(3.0), math.log10(400.0), 400)
FS = 96000.0
KW = dict(
    band_hz=(5.0, 200.0),
    placement_band_hz=(5.0, 40.0),
    max_gain_db=26.0,
    realisation=Realisation(),
    seeds=(0, 1),
    max_drift_db=3.0,
)
HERE = os.path.dirname(__file__)


def run(name, target, use_surrogate):
    original = F._fit_structure
    if use_surrogate:
        F._fit_structure = surrogate.surrogate_structure
    F.PARALLEL_FITS = False  # serial, so evaluations and time are attributable
    F.FIT_STATS.reset()
    t = time.perf_counter()
    try:
        specs, residual = F.fit_minimal_biquads(target, GRID, FS, 4, 0.5, **KW)
    finally:
        F._fit_structure = original
    return specs, residual, time.perf_counter() - t, F.FIT_STATS.cost_evaluations


only = sys.argv[1:] or None
rows = []
for path in sorted(glob.glob(f"{HERE}/*.npy")):
    name = os.path.basename(path)[:-4]
    if only and not any(o in name for o in only):
        continue
    target = np.load(path)
    a = run(name, target, False)
    b = run(name, target, True)
    rows.append((name, a, b))
    print(
        f"{name:34s} DE {a[1]:7.3f} dB {a[3]:9,d} ev {a[2]:7.1f}s {len(a[0])}s  |  "
        f"P14 {b[1]:7.3f} dB {b[3]:9,d} ev {b[2]:7.1f}s {len(b[0])}s",
        flush=True,
    )

print()
print(f"{'':34s}{'DE':>12s}{'P14':>12s}")
for label, i in (("evaluations", 3), ("seconds", 2)):
    da = sum(r[1][i] for r in rows)
    db = sum(r[2][i] for r in rows)
    print(f"{label:34s}{da:12,.0f}{db:12,.0f}   {da / db:.1f}x")
worse = [r for r in rows if r[2][1] > r[1][1] + 0.05]
better = [r for r in rows if r[2][1] < r[1][1] - 0.05]
print(
    f"\nresidual: {len(better)} better, {len(worse)} worse (by >0.05 dB), "
    f"{len(rows) - len(better) - len(worse)} the same"
)
for r in worse:
    print(f"  worse: {r[0]:32s} {r[1][1]:.3f} -> {r[2][1]:.3f} dB")
