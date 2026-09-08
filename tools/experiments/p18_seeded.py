"""Greedy placement to choose types and starting values, then DE seeded from that answer.

The two halves each fix what the other gets wrong. Greedy placement reads the section count,
the types and rough parameters straight off the residual for a few thousand evaluations, but a
local polish cannot finish a 9-to-12 parameter fit — which is why the design side reached for a
population method to begin with. DE finishes it, but starting from a uniform sample of the whole
box it spends most of its budget rediscovering things the target already says out loud.

So: greedy decides *what* the cascade is, DE decides *where exactly*, from a population seeded
around greedy's answer rather than scattered across the box. The shelf/peak split is no longer
enumerated — the residual chooses each type — which removes the `seeds * M(M+1)/2` factor as
well as most of the generations.
"""

import time

import numpy as np
from scipy import optimize

from beqanalyser.design import BiquadSpec
from beqanalyser.design.filters import biquad_sos, magnitude_db

import greedy as greedy_module


def seeded_fit(
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
    maxiter=120,
    popsize=15,
    seed=0,
):
    started = time.perf_counter()
    mask = (
        np.ones_like(freqs, dtype=bool)
        if band_hz is None
        else (freqs >= band_hz[0]) & (freqs <= band_hz[1])
    )
    placement = placement_band_hz or band_hz
    low = float(placement[0]) if placement else float(freqs[0])
    high = float(placement[1]) if placement else float(freqs[-1])

    placed, _, _, greedy_evals = greedy_module.greedy_fit(
        target_db,
        freqs,
        fs,
        max_sections,
        residual_target_db,
        band_hz=band_hz,
        placement_band_hz=placement_band_hz,
        max_q=max_q,
        max_gain_db=max_gain_db,
        realisation=realisation,
    )
    if not placed:
        return [], float("inf"), time.perf_counter() - started, greedy_evals

    kinds = [s.type for s in placed]
    evaluations = 0

    def unpack(flat):
        rows = np.asarray(flat, float).reshape(len(kinds), 3)
        return [
            BiquadSpec(k, float(max(f, 1e-6)), float(g), float(max(q, 1e-3)))
            for k, (f, q, g) in zip(kinds, rows)
        ]

    def cost(p):
        nonlocal evaluations
        evaluations += 1
        specs = unpack(p)
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

    bounds = [(low, high), (0.1, max_q), (-max_gain_db, max_gain_db)] * len(kinds)
    lower = np.array([b[0] for b in bounds])
    upper = np.array([b[1] for b in bounds])
    anchor = np.clip(
        np.array([[s.freq_hz, s.q, s.gain_db] for s in placed]).ravel(), lower, upper
    )

    # a population around greedy's answer: the anchor itself, then widening perturbations of it,
    # then a tail of uniform samples so a basin greedy missed is still reachable
    rng = np.random.default_rng(seed)
    members = max(popsize * len(anchor), 15)
    span = upper - lower
    population = [anchor]
    for i in range(1, members):
        if i < members * 0.75:
            scale = 0.02 + 0.28 * (i / (members * 0.75))
            trial = anchor + rng.normal(0.0, scale, anchor.shape) * span
        else:
            trial = lower + rng.random(anchor.shape) * span
        population.append(np.clip(trial, lower, upper))

    found = optimize.differential_evolution(
        cost,
        bounds,
        init=np.array(population),
        maxiter=maxiter,
        tol=1e-10,
        polish=True,
        seed=seed,
    )
    fine = optimize.minimize(
        cost,
        found.x,
        method="Nelder-Mead",
        bounds=bounds,
        options={"maxiter": 4000, "maxfev": 4000, "xatol": 1e-6, "fatol": 1e-8},
    )
    best = fine.x if fine.fun < found.fun else found.x
    return (
        unpack(best),
        cost(best),
        time.perf_counter() - started,
        evaluations + greedy_evals,
    )
