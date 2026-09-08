"""P18 prototype: place sections where the residual is worst, then polish jointly.

The approach REW's filter matcher uses, and the one `beqanalyser/filter.py` already uses on the
clustering side of this repo — where `fit_composite_to_peq` walks a residual, fits the most
prominent feature it finds, subtracts it and repeats. The design side instead searches every
parameter of every section at once with a 240-member population, which is a far harder problem
than the physics needs: a section's effect is *local*, so the error at 12 Hz is very largely
controlled by the section nearest 12 Hz.

Three savings, none of which is about making an evaluation cheaper:

* **Placement is read off the data, not searched for.** A bell goes where the residual peaks,
  at the gain the residual has there, with a Q from the feature's width. That is a starting
  point good enough that a 3-parameter local fit finishes it.
* **The section type comes from the residual's shape**, so the shelf/peak split is not
  enumerated. That removes the `seeds * M(M+1)/2` term — twenty fits a target become one pass.
* **The dimension never exceeds three** during placement. The joint polish at the end is the
  only time all parameters move together, and it starts somewhere sensible.

Everything is derived from the target: no fixed frequency decides anything, which is §2.1 and
is where `filter.py`'s own version would not survive being moved across (it reads its shelf
characteristics at a hardcoded 10 and 120 Hz).
"""

import math
import time

import numpy as np
from scipy import optimize

from beqanalyser.design import BiquadSpec
from beqanalyser.design.filters import biquad_sos, magnitude_db


def _response(specs, freqs, fs):
    if not specs:
        return np.zeros_like(freqs)
    return magnitude_db(biquad_sos(specs, fs), freqs, fs)


def _propose(residual, freqs, mask, low, high, max_q, max_gain):
    """A section seeded from the residual's worst feature, or None if there is none left."""
    inside = mask & (freqs >= low) & (freqs <= high)
    if not inside.any():
        return None
    scores = np.where(inside, np.abs(residual), 0.0)
    at = int(np.argmax(scores))
    peak = float(residual[at])
    if abs(peak) < 0.05:
        return None
    f0 = float(freqs[at])

    # shelf or bell, decided by whether the feature runs off the bottom of the placement band
    # rather than by any nominated frequency: a shelf is a step that does not come back.
    below = inside & (freqs <= f0)
    edge = float(residual[np.flatnonzero(inside)[0]])
    shelf_like = below.sum() <= 2 or (
        abs(edge) >= 0.7 * abs(peak) and np.sign(edge) == np.sign(peak)
    )

    if shelf_like:
        # the corner is where the step is half made; the gain is the step itself
        half = peak / 2.0
        upper = np.flatnonzero(inside & (np.abs(residual) <= abs(half)))
        corner = float(freqs[upper[0]]) if upper.size else f0
        return BiquadSpec(
            "low_shelf",
            float(np.clip(corner, low, high)),
            float(np.clip(peak, -max_gain, max_gain)),
            0.707,
        )

    # a bell: Q from the width of the feature at half its height, measured on the residual
    half_level = abs(peak) / 2.0
    span = np.flatnonzero(inside & (np.abs(residual) >= half_level))
    if span.size >= 2:
        lo_hz, hi_hz = float(freqs[span[0]]), float(freqs[span[-1]])
        width = max(math.log2(max(hi_hz / max(lo_hz, 1e-9), 1.02)), 0.05)
        q = float(np.clip(1.0 / width, 0.2, max_q))
    else:
        q = 2.0
    return BiquadSpec(
        "peaking_eq",
        float(np.clip(f0, low, high)),
        float(np.clip(peak, -max_gain, max_gain)),
        q,
    )


def greedy_fit(
    target_db,
    freqs,
    fs,
    max_sections,
    residual_target_db,
    band_hz=None,
    placement_band_hz=None,
    max_q=6.0,
    max_gain_db=30.0,
    realisation=None,
    polish_maxfev=6000,
):
    started = time.perf_counter()
    evaluations = 0
    mask = (
        np.ones_like(freqs, dtype=bool)
        if band_hz is None
        else (freqs >= band_hz[0]) & (freqs <= band_hz[1])
    )
    placement = placement_band_hz or band_hz
    low = float(placement[0]) if placement else float(freqs[0])
    high = float(placement[1]) if placement else float(freqs[-1])

    def cost_of(specs):
        nonlocal evaluations
        evaluations += 1
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

    def unpack(flat, kinds):
        rows = np.asarray(flat, float).reshape(len(kinds), 3)
        return [
            BiquadSpec(k, float(max(f, 1e-6)), float(g), float(max(q, 1e-3)))
            for k, (f, q, g) in zip(kinds, rows)
        ]

    def optimise(specs, maxfev):
        kinds = [s.type for s in specs]
        x0 = np.array([[s.freq_hz, s.q, s.gain_db] for s in specs]).ravel()
        bounds = [(low, high), (0.1, max_q), (-max_gain_db, max_gain_db)] * len(specs)
        lower = np.array([b[0] for b in bounds])
        upper = np.array([b[1] for b in bounds])
        found = optimize.minimize(
            lambda p: cost_of(unpack(p, kinds)),
            np.clip(x0, lower, upper),
            method="Nelder-Mead",
            bounds=bounds,
            options={"maxiter": maxfev, "maxfev": maxfev, "xatol": 1e-5, "fatol": 1e-7},
        )
        return unpack(found.x, kinds), float(found.fun)

    specs: list[BiquadSpec] = []
    best = ([], cost_of([])) if False else None
    for _ in range(max_sections):
        residual = target_db - _response(specs, freqs, fs)
        proposed = _propose(residual, freqs, mask, low, high, max_q, max_gain_db)
        if proposed is None:
            break
        # fit the new section alone first (three parameters, seeded from the data), then let
        # every section move together from that point
        fixed = list(specs)
        kinds = [proposed.type]

        def one(p):
            return cost_of(fixed + unpack(p, kinds))

        seeded = np.array([proposed.freq_hz, proposed.q, proposed.gain_db])
        alone = optimize.minimize(
            one,
            seeded,
            method="Nelder-Mead",
            bounds=[(low, high), (0.1, max_q), (-max_gain_db, max_gain_db)],
            options={"maxiter": 600, "maxfev": 600, "xatol": 1e-4, "fatol": 1e-6},
        )
        specs = fixed + unpack(alone.x, kinds)
        specs, residual_now = optimise(specs, polish_maxfev)
        if best is None or residual_now < best[1]:
            best = (list(specs), residual_now)
        if residual_now <= residual_target_db:
            break

    if best is None:
        best = ([], math.inf)
    return best[0], best[1], time.perf_counter() - started, evaluations
