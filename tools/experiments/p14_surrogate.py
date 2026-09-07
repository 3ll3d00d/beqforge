"""P14 prototype: multi-start smooth-surrogate fitting in place of differential evolution.

**Rejected on measurement. Kept so the next person does not rebuild it to find out.**
4.6x faster over the thirteen real targets, and worse on ten of them, six of which cross
`residual_target_db` and so change the published cascade. PERFORMANCE.md section 4 has the
table and what would have to change to make it worth another attempt (an analytic Jacobian —
two-point differencing spends `dim + 1` evaluations an iteration, which is where both the
budget and the residual gap go).


Drop-in for `_fit_structure`, so the tier escalation, pruning and drift screening around it are
unchanged and only the inner solver differs. Same signature, same return shape.

Three stages per start:

1. **Least squares** on the raw error vector, via `least_squares` with a numerical Jacobian.
   Cheap: 3*sections + 1 evaluations an iteration rather than a whole DE population.
2. **Lawson's IRLS** toward the Chebyshev solution — reweight by |error| and re-solve. Minimax
   is what the contract asks for; L2 alone under-weights the worst point, which is the only
   point the residual is scored on.
3. **Nelder-Mead on the true cost**, including the quantisation drift term. That term contains
   `np.round`, so it is piecewise constant and invisible to a derivative; it has to be finished
   on the real objective or the drift control of §5.1 is silently dropped.

Starts are seeded from the target's own shape rather than sampled from the whole box: a shelf
belongs near where the target falls away, at about the gain the target asks for.
"""

import math
import time

import numpy as np
from scipy import optimize

from beqanalyser.design import BiquadSpec
from beqanalyser.design.filters import biquad_sos, magnitude_db

LAWSON_ROUNDS = 4
LS_MAX_NFEV = 400


def _unpack(params, shelves, peaks):
    rows = np.asarray(params, dtype=np.float64).reshape(shelves + peaks, 3)
    rows = rows.copy()
    rows[:, 0] = np.maximum(rows[:, 0], 1e-6)
    rows[:, 1] = np.maximum(rows[:, 1], 1e-3)
    return [
        BiquadSpec(
            "low_shelf" if i < shelves else "peaking_eq",
            float(f),
            float(g),
            float(max(q, 1e-3)),
        )
        for i, (f, q, g) in enumerate(rows)
    ]


def _seeded_starts(target_db, freqs, shelves, peaks, low, high, max_q, max_gain, rng):
    """Starts taken from the target's shape, plus random ones for the basins it misses."""
    sections = shelves + peaks
    active = np.flatnonzero(np.abs(target_db) >= 0.5)
    peak_db = float(np.max(np.abs(target_db))) if target_db.size else 1.0
    if active.size:
        lo_hz = max(low, float(freqs[active[0]]))
        hi_hz = min(high, float(freqs[active[-1]]))
    else:
        lo_hz, hi_hz = low, high
    hi_hz = max(hi_hz, lo_hz * 1.05)

    starts = []
    # the shape-led family: sections spread over where the target actually asks for something
    for spread in (1.0, 0.6, 1.6):
        row = []
        places = np.geomspace(lo_hz, hi_hz, sections + 2)[1:-1]
        for i, f in enumerate(places):
            gain = peak_db / max(sections, 1) if i < shelves else peak_db * 0.25
            row += [
                float(np.clip(f, low, high)),
                float(np.clip(0.7 * spread, 0.1, max_q)),
                float(np.clip(gain, -max_gain, max_gain)),
            ]
        starts.append(np.array(row))
    return starts


def surrogate_structure(
    target_db,
    freqs,
    fs,
    shelves,
    peaks,
    band_hz,
    placement_hz,
    max_q,
    max_gain_db,
    realisation,
    seed,
    random_starts=6,
):
    started = time.perf_counter()
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
    lower = np.array([b[0] for b in bounds])
    upper = np.array([b[1] for b in bounds])

    def error(p):
        nonlocal evaluations
        evaluations += 1
        sos = biquad_sos(_unpack(p, shelves, peaks), fs)
        return (magnitude_db(sos, freqs, fs) - target_db)[mask]

    def cost(p):
        nonlocal evaluations
        evaluations += 1
        specs = _unpack(p, shelves, peaks)
        sos = biquad_sos(specs, fs)
        response = magnitude_db(sos, freqs, fs)
        worst = float(np.max(np.abs((response - target_db)[mask])))
        if realisation is not None:
            if realisation.fs == fs:
                device, undrifted = sos, response
            else:
                device = biquad_sos(specs, realisation.fs)
                undrifted = magnitude_db(device, freqs, realisation.fs)
            drift = (
                magnitude_db(realisation.quantise(device), freqs, realisation.fs)
                - undrifted
            )
            worst = max(worst, float(np.max(np.abs(drift[mask]))))
        return worst

    rng = np.random.default_rng(seed)
    starts = _seeded_starts(
        target_db, freqs, shelves, peaks, low, high, max_q, max_gain_db, rng
    )
    for _ in range(random_starts):
        starts.append(lower + rng.random(len(lower)) * (upper - lower))

    best_x, best_cost = None, math.inf
    for start in starts:
        x = np.clip(start, lower, upper)
        weights = np.ones(int(mask.sum()))
        for round_index in range(LAWSON_ROUNDS):
            root = np.sqrt(weights / weights.mean())

            def weighted(p, root=root):
                return root * error(p)

            found = optimize.least_squares(
                weighted, x, bounds=(lower, upper), max_nfev=LS_MAX_NFEV
            )
            x = found.x
            if round_index < LAWSON_ROUNDS - 1:
                magnitude = np.abs(error(x))
                weights = weights * np.maximum(magnitude, 1e-9)
                weights /= weights.mean()
        # bounded: Nelder-Mead is otherwise free to leave the box, and BiquadSpec refuses a
        # non-positive frequency or Q. Exactly the crash PERFORMANCE.md section 6 records in
        # `_fit_structure`, reproduced here on the first target tried.
        polished = optimize.minimize(
            cost,
            x,
            method="Nelder-Mead",
            bounds=list(zip(lower, upper)),
            options={"maxiter": 2000, "maxfev": 2000, "xatol": 1e-6, "fatol": 1e-8},
        )
        candidate_x = polished.x if polished.fun < cost(x) else x
        candidate_cost = cost(candidate_x)
        if candidate_cost < best_cost:
            best_x, best_cost = candidate_x, candidate_cost

    return (
        _unpack(best_x, shelves, peaks),
        best_cost,
        time.perf_counter() - started,
        evaluations,
    )
