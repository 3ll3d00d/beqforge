"""Greedy chooses the cascade's *structure*; the existing DE fits it, unchanged.

The seeded-population variant failed for an instructive reason: a population clustered around
greedy's answer has small difference vectors, so DE takes small steps and never leaves the
basin it was handed. On one target it improved greedy's 1.359 dB to 1.323 — it was trapped, not
helped. Seeding a global search with a mediocre point is worse than not seeding it.

But the expensive part of the current fitter is not the search, it is that the search is run
`seeds * M(M+1)/2` times — every section count, every shelf/peak split, every seed, twenty fits
a target — because nothing knows in advance how many sections are wanted or which should be
shelves. The residual does know. So greedy picks the *structure* and hands it over, and DE runs
exactly as it does today on that one configuration with a full budget and its own free
initialisation.

Nothing about how a configuration is fitted changes. What changes is how many configurations
get fitted.
"""

import time


import beqanalyser.design.filters as F
import greedy as greedy_module


def structure_fit(
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
    seeds=(0, 1),
    max_drift_db=None,
):
    started = time.perf_counter()
    F.FIT_STATS.reset()
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

    shelves = sum(1 for s in placed if s.type == "low_shelf")
    peaks = len(placed) - shelves
    # `_fit_structure` orders shelves first, so a structure of all peaks and no shelves is
    # expressed as shelves=0. It handles that; the enumeration never generated it.
    results = F._run_fits(
        [
            (
                target_db,
                freqs,
                fs,
                shelves,
                peaks,
                band_hz,
                placement_band_hz or band_hz,
                max_q,
                max_gain_db,
                realisation,
                seed,
            )
            for seed in seeds
        ]
    )
    specs, residual, _ = min(results, key=lambda r: r[1])
    specs, residual = F._prune((specs, residual), target_db, freqs, fs, band_hz, 1.0)
    return (
        specs,
        residual,
        time.perf_counter() - started,
        F.FIT_STATS.cost_evaluations + greedy_evals,
    )
