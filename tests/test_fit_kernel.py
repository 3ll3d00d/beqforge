"""The fit's population cost (TODO 23).

Two claims carry it. The compiled and numpy kernels give the same bits, so an answer cannot
depend on whether numba is installed; and the population cost is the scalar cost, evaluated a
different way, so the search is steered by the quantity the fit is judged on.
"""

import math

import numpy as np
import pytest

import beqforge.filters as F
from beqforge import DESIGN_GRID, fit_kernel
from beqforge.filters import Realisation

FS = 96000.0
BAND = (DESIGN_GRID >= 5.0) & (DESIGN_GRID <= 220.0)
CEILING = (np.geomspace(3.0, 120.0, 150), np.full(150, 6.0))


def _population(sections: int, members: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rows = np.stack(
        [
            rng.uniform(5.0, 220.0, (members, sections)),
            rng.uniform(0.1, 6.0, (members, sections)),
            rng.uniform(-30.0, 30.0, (members, sections)),
        ],
        axis=-1,
    )
    return rows.reshape(members, 3 * sections).T


def _target(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.round(
        np.interp(
            np.log(DESIGN_GRID), np.log([3.0, 20.0, 60.0, 400.0]), rng.uniform(0, 20, 4)
        ),
        2,
    )


def _scalar_cost(p, target, shelves, peaks, realisation, ceiling) -> float:
    """`_fit_structure`'s `cost`, restated: the definition the population cost must match."""
    p = F._published_parameters(p)
    sos = F._sos_from_parameters(p, shelves, peaks, FS)
    response = F.magnitude_db(sos, DESIGN_GRID, FS)
    worst = float(np.max(np.abs((response - target)[BAND])))
    rate = FS
    realised = sos
    if realisation is not None:
        rate = realisation.fs
        device = F._sos_from_parameters(p, shelves, peaks, rate)
        undrifted = F.magnitude_db(device, DESIGN_GRID, rate)
        realised = realisation.quantise(device)
        drift = F.magnitude_db(realised, DESIGN_GRID, rate) - undrifted
        worst = max(worst, float(np.max(np.abs(drift[BAND]))))
    if ceiling is None:
        return worst
    over = float(np.max(F.magnitude_db(realised, ceiling[0], rate) - ceiling[1]))
    return worst if over <= 0.0 else 1e3 + over


CASES = [
    pytest.param(Realisation(), CEILING, id="device-at-fit-rate-with-ceiling"),
    pytest.param(Realisation(fs=48000.0), CEILING, id="device-at-another-rate"),
    pytest.param(Realisation(), None, id="no-ceiling"),
    pytest.param(None, CEILING, id="no-device"),
]


@pytest.mark.parametrize(("realisation", "ceiling"), CASES)
@pytest.mark.parametrize(("shelves", "peaks"), [(1, 0), (2, 1), (1, 3)])
def test_the_population_cost_is_the_scalar_cost(
    realisation, ceiling, shelves, peaks
) -> None:
    """Linear-domain maxima, numpy rounding and normalised coefficients change the last digits
    only: every member scores what the scalar cost gives it, over and under the ceiling."""
    target = _target(shelves * 10 + peaks)
    population = _population(shelves + peaks, 120, seed=shelves + 7 * peaks)
    cost = fit_kernel.PopulationCost(
        target, DESIGN_GRID, FS, shelves, peaks, BAND, realisation, ceiling
    )
    scored = cost(population)
    reference = np.array(
        [
            _scalar_cost(p, target, shelves, peaks, realisation, ceiling)
            for p in population.T
        ]
    )
    assert scored.shape == (population.shape[1],)
    np.testing.assert_allclose(scored, reference, rtol=0, atol=1e-6)
    if ceiling is not None:
        assert np.array_equal(scored >= 1e3, reference >= 1e3)


@pytest.mark.skipif(fit_kernel.numba is None, reason="numba is not installed")
@pytest.mark.parametrize(("realisation", "ceiling"), CASES)
def test_numba_and_numpy_give_the_same_bits(realisation, ceiling) -> None:
    """Every coefficient and every transcendental is numpy's on both paths and the kernels add,
    multiply, divide and compare in the same order, so the two must agree exactly: if numba ever
    fused a multiply-add, which installs designed would differ from which would be the result."""
    for sections, shelves in [(1, 1), (3, 1), (4, 2)]:
        target = _target(sections)
        population = _population(sections, 240, seed=sections)
        cost = fit_kernel.PopulationCost(
            target,
            DESIGN_GRID,
            FS,
            shelves,
            sections - shelves,
            BAND,
            realisation,
            ceiling,
        )
        compiled = cost(population)
        fallback = (fit_kernel._fit_and_drift, fit_kernel._worst_ratio)
        try:
            fit_kernel._fit_and_drift = fit_kernel._fit_and_drift_numpy
            fit_kernel._worst_ratio = fit_kernel._worst_ratio_numpy
            interpreted = cost(population)
        finally:
            fit_kernel._fit_and_drift, fit_kernel._worst_ratio = fallback
        assert np.array_equal(compiled, interpreted), "the kernels have parted"


def test_a_fit_returns_the_scalar_residual_of_its_published_cascade() -> None:
    """The search is the population cost's, but what a fit reports is still `residual_db`'s
    definition on the cascade as published, which is what the judge and the response read."""
    target = _target(3)
    specs, residual, _, evaluations = F._fit_structure(
        target,
        DESIGN_GRID,
        FS,
        1,
        1,
        (5.0, 220.0),
        (5.0, 220.0),
        6.0,
        30.0,
        Realisation(),
        0,
    )
    params = np.array([v for s in specs for v in (s.freq_hz, s.q, s.gain_db)])
    assert residual == _scalar_cost(params, target, 1, 1, Realisation(), None)
    assert math.isfinite(residual)
    assert evaluations > 300 * 20 * 6


@pytest.mark.skipif(fit_kernel.numba is None, reason="numba is not installed")
def test_a_kernel_compiles_uncached_when_numba_has_nowhere_to_cache(
    monkeypatch,
) -> None:
    """The designer image run as another user can write neither beside the source nor to a home,
    and numba then refuses to compile with `cache=True`: the server must still start."""
    real = fit_kernel.numba.njit

    def njit(*args, **kwargs):
        if kwargs.get("cache"):
            raise RuntimeError(
                "cannot cache function 'f': no locator available for file 'x'"
            )
        return real(*args, **kwargs)

    monkeypatch.setattr(fit_kernel.numba, "njit", njit)
    compiled = fit_kernel._compiled(lambda x: x * 2.0)
    assert compiled(1.5) == 3.0
