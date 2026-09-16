"""Parallel fitting must decide exactly what serial fitting decides.

The pool is a performance change and nothing else. `_fit_structure` is seeded per task and
results are collected in submission order, so the selection is order-independent — this pins
that down, because a parallelism bug that merely reorders results would show up as a filter
that changes between runs rather than as a crash.
"""

import math

import numpy as np

import beqforge.filters as F


def shelf_target() -> tuple[np.ndarray, np.ndarray]:
    freqs = np.logspace(math.log10(3.0), math.log10(400.0), 200)
    target = np.clip(
        12.0 - 12.0 * np.log2(np.maximum(freqs, 6.0) / 6.0) / np.log2(25.0 / 6.0),
        0.0,
        None,
    )
    target[freqs > 30.0] = 0.0
    return freqs, target


def fit(parallel: bool) -> tuple[list, float, int]:
    freqs, target = shelf_target()
    F.PARALLEL_FITS = parallel
    F.FIT_STATS.reset()
    try:
        specs, error = F.fit_to_biquads(
            target,
            freqs,
            96000.0,
            2,
            band_hz=(5.0, 200.0),
            placement_band_hz=(5.0, 40.0),
            max_gain_db=20.0,
            seeds=(0, 1),
        )
    finally:
        F.PARALLEL_FITS = True
    return specs, error, F.FIT_STATS.calls


def test_parallel_and_serial_agree_exactly() -> None:
    serial_specs, serial_error, serial_calls = fit(parallel=False)
    parallel_specs, parallel_error, parallel_calls = fit(parallel=True)

    assert parallel_calls == serial_calls
    assert parallel_error == serial_error
    assert len(parallel_specs) == len(serial_specs)
    for got, want in zip(parallel_specs, serial_specs):
        assert got.type == want.type
        assert got.freq_hz == want.freq_hz
        assert got.gain_db == want.gain_db
        assert got.q == want.q


def test_stats_are_collected_from_workers() -> None:
    """A module-level counter incremented in a worker reports zero in the parent."""
    _, _, calls = fit(parallel=True)
    assert calls == 4  # 2 splits x 2 seeds
    assert F.FIT_STATS.seconds > 0.0
    assert F.FIT_STATS.cost_evaluations > 0


def test_the_pool_leaves_a_physical_core_free() -> None:
    """Sized in cores, not hardware threads.

    `cpu_count()` reports threads, so "all but one" of 16 put 15 CPU-bound fits on 8 cores and
    saturated the machine — the opposite of leaving headroom.
    """
    from multiprocessing import cpu_count

    physical = F._physical_cores()
    assert 1 <= physical <= cpu_count()
    assert F.FIT_WORKERS <= max(1, physical - 1)
    assert F.FIT_WORKERS >= 1
