"""The existing DE, with only the drift term in its cost changed to the smooth bound.

No new optimiser. `_fit_structure` is untouched except that the piecewise-constant rounding it
scores drift by is replaced with the first-order sensitivity bound, which measured a rank
correlation of 0.835 against the p90 `accept` gates on where the rounding measured 0.340.
"""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402

import beqforge.filters as F  # noqa: E402
from p14_jacobian import coefficient_sensitivity  # noqa: E402

SENSITIVITY_TO_P90 = 3.0
_original = F._fit_structure


def patched(target_db, freqs, fs, shelves, peaks, band_hz, placement_hz,
            max_q, max_gain_db, realisation, seed):
    """`_fit_structure` with the drift term swapped, by patching the cost it builds."""
    import time as _time

    from scipy import optimize

    started = _time.perf_counter()
    evaluations = 0
    sections = shelves + peaks
    mask = (
        np.ones_like(freqs, dtype=bool)
        if band_hz is None
        else (freqs >= band_hz[0]) & (freqs <= band_hz[1])
    )
    low = float(placement_hz[0]) if placement_hz else float(freqs[0])
    high = float(placement_hz[1]) if placement_hz else float(freqs[-1])
    bounds = [(low, high), (0.1, max_q), (-max_gain_db, max_gain_db)] * sections
    step = (
        None
        if realisation is None
        else 2.0 ** (realisation.integer_bits - realisation.coefficient_bits)
    )

    def cost(p):
        nonlocal evaluations
        evaluations += 1
        specs = F._unpack(p, shelves, peaks)
        err = F.magnitude_db(F.biquad_sos(specs, fs), freqs, fs) - target_db
        worst = float(np.max(np.abs(err[mask])))
        if realisation is not None:
            bound = coefficient_sensitivity(specs, freqs, realisation.fs, step)
            worst = max(worst, float(np.max(bound[mask])) / SENSITIVITY_TO_P90)
        return worst

    coarse = optimize.differential_evolution(
        cost, bounds, seed=seed, maxiter=300, popsize=20, tol=1e-10, polish=True
    )
    fine = optimize.minimize(
        cost, coarse.x, method="Nelder-Mead", bounds=bounds,
        options={"maxiter": 60000, "maxfev": 60000, "xatol": 1e-10, "fatol": 1e-12},
    )
    best = fine.x if fine.fun < coarse.fun else coarse.x
    return (
        F._unpack(best, shelves, peaks),
        cost(best),
        _time.perf_counter() - started,
        evaluations,
    )


F._fit_structure = patched

from beqforge import record  # noqa: E402
from beqforge.material import load  # noqa: E402
from beqforge.pipeline import PipelineParams, run  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(message)s")
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for name in ("test_71", "test2_71", "test3_71", "test4_71"):
    material_path = Path(f"data/{name}.npz")
    started = time.perf_counter()
    material = load(material_path)
    params = PipelineParams()
    report = run(material, params, cache_path=None)
    record.write(out / f"{name}.run.json.gz", report, params, material_path, None)
    print(
        f"{name}: {report.timings.total_s:.1f}s pipeline, "
        f"accepted={report.accepted.label if report.accepted else None}",
        flush=True,
    )
print("ALLDONE")
