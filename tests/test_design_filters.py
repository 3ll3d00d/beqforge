"""The output stage.

The closed-form claim is the load-bearing one: when the protective filter shares the rolloff's
alignment and order, the exact inverse *is* a low shelf cascade. These pin that down.
"""

import dataclasses
import math

import numpy as np
import pytest

from beqforge import (
    BIQUAD_BUDGET,
    Alignment,
    BiquadSpec,
    ExactInversionUnavailable,
    HighPass,
)
import beqforge.filters as F
from beqforge.filters import (
    Realisation,
    biquad_sos,
    correction_band_hz,
    fit_to_biquads,
    high_pass_sos,
    inversion_target_db,
    invert_to_shelves,
    magnitude_db,
    residual_db,
    section_poles,
)

FS = 48000.0
FREQS = np.logspace(np.log10(3.0), np.log10(400.0), 400)
BAND = (5.0, 200.0)

BUTTERWORTH_QS = {
    2: [0.70710678],
    4: [0.54119610, 1.30656296],
    8: [0.50979558, 0.60134489, 0.89997622, 2.56291545],
}


@pytest.mark.parametrize("order, expected", sorted(BUTTERWORTH_QS.items()))
def test_butterworth_section_qs(order: int, expected: list[float]) -> None:
    pairs, reals = section_poles(HighPass(Alignment.BUTTERWORTH, order, 25.0))
    assert not reals
    assert sorted(p.q for p in pairs) == pytest.approx(sorted(expected), rel=1e-6)
    assert all(p.freq_hz == pytest.approx(25.0, rel=1e-9) for p in pairs)


def test_odd_order_leaves_one_real_pole() -> None:
    pairs, reals = section_poles(HighPass(Alignment.BUTTERWORTH, 3, 25.0))
    assert len(pairs) == 1
    assert reals == pytest.approx([25.0], rel=1e-9)


def test_linkwitz_riley_is_butterworth_squared() -> None:
    pairs, _ = section_poles(HighPass(Alignment.LINKWITZ_RILEY, 4, 25.0))
    assert [p.q for p in pairs] == pytest.approx([0.70710678] * 2, rel=1e-6)


@pytest.mark.parametrize(
    "alignment, order, rolloff_hz, protect_hz",
    [
        (Alignment.LINKWITZ_RILEY, 4, 25.0, 10.0),
        (Alignment.LINKWITZ_RILEY, 4, 35.0, 12.0),
        (Alignment.LINKWITZ_RILEY, 2, 30.0, 10.0),
        (Alignment.LINKWITZ_RILEY, 8, 25.0, 10.0),
        (Alignment.BUTTERWORTH, 4, 25.0, 10.0),
        (Alignment.BUTTERWORTH, 8, 30.0, 11.0),
        (Alignment.BESSEL_PHASE, 4, 25.0, 10.0),
    ],
)
def test_matched_alignment_inverts_exactly(
    alignment: Alignment, order: int, rolloff_hz: float, protect_hz: float
) -> None:
    """The whole §5 argument. Residual is bilinear pre-warping, not structure."""
    rolloff = HighPass(alignment, order, rolloff_hz)
    protect = HighPass(alignment, order, protect_hz)
    specs = invert_to_shelves(rolloff, protect)

    assert len(specs) == order // 2
    assert len(specs) <= BIQUAD_BUDGET
    target = inversion_target_db(rolloff, protect, FREQS, FS)
    assert residual_db(specs, target, FREQS, FS, BAND) < 5e-3


def test_shelf_parameters_match_the_closed_form() -> None:
    specs = invert_to_shelves(
        HighPass(Alignment.LINKWITZ_RILEY, 4, 25.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 10.0),
    )
    assert len(specs) == 2
    for spec in specs:
        assert spec.type == "low_shelf"
        assert spec.freq_hz == pytest.approx(math.sqrt(250.0))
        assert spec.gain_db == pytest.approx(40.0 * math.log10(2.5))
        assert spec.q == pytest.approx(0.70710678, rel=1e-6)


def test_inversion_flattens_the_rolloff_above_the_protective_corner() -> None:
    """End to end: rolloff plus its inverse should be the protective filter alone."""
    rolloff = HighPass(Alignment.LINKWITZ_RILEY, 4, 25.0)
    protect = HighPass(Alignment.LINKWITZ_RILEY, 4, 10.0)
    specs = invert_to_shelves(rolloff, protect)

    corrected = magnitude_db(high_pass_sos(rolloff, FS), FREQS, FS) + magnitude_db(
        biquad_sos(specs, FS), FREQS, FS
    )
    expected = magnitude_db(high_pass_sos(protect, FS), FREQS, FS)
    band = (FREQS >= BAND[0]) & (FREQS <= BAND[1])
    delta = (corrected - expected)[band]
    assert np.max(np.abs(delta - delta[-1])) < 5e-3


@pytest.mark.parametrize(
    "rolloff, protect",
    [
        (
            HighPass(Alignment.BUTTERWORTH, 4, 25.0),
            HighPass(Alignment.LINKWITZ_RILEY, 4, 10.0),
        ),
        (
            HighPass(Alignment.BUTTERWORTH, 4, 25.0),
            HighPass(Alignment.BUTTERWORTH, 2, 10.0),
        ),
        (
            HighPass(Alignment.BUTTERWORTH, 3, 25.0),
            HighPass(Alignment.BUTTERWORTH, 3, 10.0),
        ),
        (
            HighPass(Alignment.BUTTERWORTH, 4, 25.0),
            HighPass(Alignment.BUTTERWORTH, 4, 25.0),
        ),
    ],
)
def test_closed_form_declines_rather_than_approximating(
    rolloff: HighPass, protect: HighPass
) -> None:
    with pytest.raises(ExactInversionUnavailable):
        invert_to_shelves(rolloff, protect)


def test_numerical_fit_closes_a_mismatched_alignment() -> None:
    """The fallback path: different alignments, so no shared Q and no closed form.

    Kept deliberately small. The fit is stochastic and multimodal, so a tight bound here would
    be testing the optimiser's luck rather than the code; `fit_to_biquads` says as much.
    """
    target = inversion_target_db(
        HighPass(Alignment.BESSEL_PHASE, 4, 25.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 10.0),
        FREQS,
        FS,
    )
    specs, error = fit_to_biquads(
        target, FREQS, FS, sections=2, band_hz=BAND, seeds=(0,)
    )

    assert len(specs) == 2
    assert len(specs) <= BIQUAD_BUDGET
    assert error < 0.1
    assert residual_db(specs, target, FREQS, FS, BAND) == pytest.approx(error)

    repeat, repeat_error = fit_to_biquads(
        target, FREQS, FS, sections=2, band_hz=BAND, seeds=(0,)
    )
    assert repeat == specs, "designer-interface.md §1 requires a reproducible answer"
    assert repeat_error == error


def test_sections_are_never_placed_below_the_measured_band() -> None:
    """A section below the lowest measured frequency has its corner and Q resting on nothing.

    Only its skirt is fitted. Unbounded, the fit does exactly this — it returned a low shelf
    at 3.22 Hz with +45 dB to express a correction under 5 dB above 10 Hz, using the shelf's
    transition as a ramp rather than using it as a shelf.
    """
    target = inversion_target_db(
        HighPass(Alignment.BUTTERWORTH, 4, 14.0),
        HighPass(Alignment.BUTTERWORTH, 4, 6.0),
        FREQS,
        FS,
    )
    evidence_floor = 5.0
    placement = correction_band_hz(target, FREQS, evidence_floor)
    assert placement[0] >= evidence_floor

    specs, _ = fit_to_biquads(
        target,
        FREQS,
        FS,
        sections=2,
        band_hz=BAND,
        placement_band_hz=placement,
        max_gain_db=26.0,
        seeds=(0,),
    )
    assert all(spec.freq_hz >= evidence_floor for spec in specs)
    assert all(abs(spec.gain_db) <= 26.0 for spec in specs)


def test_correction_band_widens_upward_but_never_downward() -> None:
    """The asymmetry is deliberate: reaching up is harmless, reaching down leaves the data."""
    target = inversion_target_db(
        HighPass(Alignment.BUTTERWORTH, 4, 20.0),
        HighPass(Alignment.BUTTERWORTH, 4, 8.0),
        FREQS,
        FS,
    )
    low, high = correction_band_hz(target, FREQS, 5.0)
    assert low == pytest.approx(5.0)
    assert high > 20.0


def test_fitted_sections_stay_inside_the_evaluated_band() -> None:
    """A section outside the cost band is unconstrained, and not harmlessly so: one fit
    evaluated over 5-200 Hz placed a +15 dB peak at 378 Hz, invisible to its own residual
    and thoroughly audible on playback.
    """
    target = inversion_target_db(
        HighPass(Alignment.BUTTERWORTH, 4, 25.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 10.0),
        FREQS,
        FS,
    )
    specs, _ = fit_to_biquads(target, FREQS, FS, sections=3, band_hz=BAND, seeds=(0,))
    assert all(BAND[0] <= spec.freq_hz <= BAND[1] for spec in specs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"freq_hz": 0.0, "gain_db": 1.0, "q": 0.7},
        {"freq_hz": 20.0, "gain_db": 1.0, "q": 0.0},
        {"freq_hz": 20.0, "gain_db": float("nan"), "q": 0.7},
    ],
)
def test_biquad_spec_rejects_unpublishable_values(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        BiquadSpec(type="low_shelf", **kwargs)


def test_linkwitz_riley_rejects_odd_order() -> None:
    with pytest.raises(ValueError):
        HighPass(Alignment.LINKWITZ_RILEY, 3, 25.0)


def test_fitting_scores_the_realisation_not_just_float64() -> None:
    """A cascade that only works in double precision is not a filter anyone can use.

    Fitting on magnitude alone puts no cost on a solution built from large opposing sections:
    they cancel perfectly in float64 and the residual says so. On the target device the
    cancellation does not survive coefficient quantisation. Scoring the quantised realisation
    inside the cost rejects those while they are being fitted.
    """
    target = inversion_target_db(
        HighPass(Alignment.BUTTERWORTH, 4, 25.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 9.0),
        FREQS,
        FS,
    )
    realisation = Realisation()

    def drift_db(specs: list[BiquadSpec]) -> float:
        sos = biquad_sos(specs, realisation.fs)
        exact = magnitude_db(sos, FREQS, realisation.fs)
        quantised = magnitude_db(realisation.quantise(sos), FREQS, realisation.fs)
        band = (FREQS >= BAND[0]) & (FREQS <= BAND[1])
        return float(np.max(np.abs(quantised - exact)[band]))

    naive, naive_error = fit_to_biquads(
        target, FREQS, FS, sections=3, band_hz=BAND, seeds=(0,)
    )
    aware, aware_error = fit_to_biquads(
        target, FREQS, FS, sections=3, band_hz=BAND, realisation=realisation, seeds=(0,)
    )

    assert drift_db(aware) < drift_db(naive)
    assert drift_db(aware) < 1.0
    # the accuracy given up for that has to stay small, or this is not a trade worth making
    assert aware_error < naive_error + 0.5


def test_quantisation_leaves_the_normalised_denominator_alone() -> None:
    sos = biquad_sos([BiquadSpec("low_shelf", 12.0, 15.0, 0.9)], 96000.0)
    assert np.all(Realisation().quantise(sos)[:, 3] == 1.0)


def test_the_fit_selects_on_the_drift_that_will_be_published() -> None:
    """The cost scores drift at the exact coefficients; publication rounds them first.

    Selecting on residual alone therefore picks the most accurate cascade in the budget even
    when it is the one the acceptance model will then reject. On the third title's flatten
    target that is what happened: the 3-section fit measured 0.43 dB in the cost and 3.44 dB
    at the p90 of its publication rounding, against a 3.0 limit, while the 2-section fit at
    0.59 dB drifts 2.69 and passes. Selecting the second is worth 0.16 dB of accuracy.

    Exercised on hand-built cascades rather than fitted ones, so the case is the one intended
    rather than whatever the optimiser happens to produce.
    """
    freqs = np.logspace(np.log10(3.0), np.log10(400.0), 400)
    realisation = F.Realisation()
    fragile = [
        BiquadSpec("low_shelf", 10.59, 14.36, 0.945),
        BiquadSpec("peaking_eq", 8.36, 1.29, 4.110),
        BiquadSpec("peaking_eq", 7.17, -0.85, 5.688),
        BiquadSpec("peaking_eq", 10.59, -3.63, 5.349),
    ]
    robust = [
        BiquadSpec("low_shelf", 19.74, 2.32, 2.495),
        BiquadSpec("low_shelf", 16.23, 10.93, 0.744),
    ]

    def drift_of(specs):
        return float(np.percentile(F.drift_distribution(specs, freqs, realisation), 90))

    assert drift_of(fragile) > drift_of(robust), "the fixture no longer separates"
    limit = 0.5 * (drift_of(fragile) + drift_of(robust))

    # the fragile one is the more accurate, so residual alone would take it
    assert F._publishable(robust, 0.59, freqs, realisation, limit)
    assert not F._publishable(fragile, 0.43, freqs, realisation, limit)
    # asked per candidate rather than over the whole set, so the escalation can screen a
    # section count as it arrives and stop without fitting the ones above it
    assert F._publishable(fragile, 0.43, freqs, realisation, None)
    assert F._publishable(fragile, 0.43, freqs, None, limit)


def test_an_impossible_drift_limit_still_returns_a_cascade() -> None:
    """Abstaining is the acceptance model's job, and it can say why; this cannot."""
    freqs = np.logspace(np.log10(3.0), np.log10(400.0), 300)
    target = 12.0 / (1.0 + (freqs / 18.0) ** 2)
    specs, _ = F.fit_minimal_biquads(
        target,
        freqs,
        96000.0,
        2,
        0.05,
        band_hz=(5.0, 200.0),
        placement_band_hz=(5.0, 40.0),
        realisation=F.Realisation(),
        seeds=(0,),
        max_drift_db=0.0,
    )
    assert specs


def test_memoised_twiddles_do_not_change_the_response() -> None:
    """The twiddle cache is an optimisation and must be invisible in the answer.

    Bit-identical, not close: `_fit_structure` compares costs, so a last-bit difference in the
    magnitude can send the optimiser to a different cascade and change what gets published.
    """
    grid = np.logspace(math.log10(3.0), math.log10(400.0), 400)
    sos = F.biquad_sos(
        [
            BiquadSpec("low_shelf", 12.0, 14.0, 0.7),
            BiquadSpec("peaking_eq", 8.0, 4.0, 1.2),
        ],
        96000.0,
    )
    F._Z_POWERS.clear()
    cold = F.magnitude_db(sos, grid, 96000.0)
    warm = F.magnitude_db(sos, grid, 96000.0)
    assert np.array_equal(cold, warm)

    # and against the arithmetic with nothing memoised at all
    z1 = np.exp(-2j * np.pi * grid / 96000.0)
    z2 = z1 * z1
    b, a = sos[:, :3], sos[:, 3:]
    num = b[:, 0, None] + b[:, 1, None] * z1 + b[:, 2, None] * z2
    den = a[:, 0, None] + a[:, 1, None] * z1 + a[:, 2, None] * z2
    assert np.array_equal(
        cold, np.sum(20.0 * np.log10(np.abs(num / den) + 1e-300), axis=0)
    )


def test_a_second_grid_is_not_served_the_first_grid_s_twiddles() -> None:
    """The cache is keyed on identity, so two live grids must not collide."""
    fine = np.logspace(math.log10(3.0), math.log10(400.0), 400)
    coarse = np.logspace(math.log10(3.0), math.log10(400.0), 64)
    sos = F.biquad_sos([BiquadSpec("low_shelf", 12.0, 14.0, 0.7)], 96000.0)
    F._Z_POWERS.clear()
    assert len(F.magnitude_db(sos, fine, 96000.0)) == 400
    assert len(F.magnitude_db(sos, coarse, 96000.0)) == 64
    assert len(F.magnitude_db(sos, fine, 96000.0)) == 400
    # the same grid at a different rate is a different entry, not the same one
    at_48k = F.magnitude_db(sos, fine, 48000.0)
    assert not np.array_equal(at_48k, F.magnitude_db(sos, fine, 96000.0))


def test_the_twiddle_cache_stays_bounded() -> None:
    sos = F.biquad_sos([BiquadSpec("low_shelf", 12.0, 14.0, 0.7)], 96000.0)
    F._Z_POWERS.clear()
    for count in range(4, 4 + F._Z_POWERS_LIMIT * 3):
        F.magnitude_db(sos, np.geomspace(3.0, 400.0, count), 96000.0)
    assert len(F._Z_POWERS) <= F._Z_POWERS_LIMIT


def test_the_drift_term_is_unchanged_when_the_rates_agree() -> None:
    """`cost` reuses the published cascade as the realised one when the rates match.

    The saving is a `biquad_sos` and a `magnitude_db` per evaluation; the requirement is that
    the number it produces is the one the two-rate path would have produced.
    """
    grid = np.logspace(math.log10(3.0), math.log10(400.0), 400)
    target = np.clip(12.0 - 12.0 * np.log2(np.maximum(grid, 6.0) / 6.0), 0.0, None)
    realisation = F.Realisation()
    assert realisation.fs == 96000.0

    reused, _, _, _ = F._fit_structure(
        target,
        grid,
        96000.0,
        1,
        0,
        (5.0, 200.0),
        (5.0, 40.0),
        6.0,
        20.0,
        realisation,
        0,
    )
    # the same fit with the realisation one Hz away takes the two-rate branch
    apart, _, _, _ = F._fit_structure(
        target,
        grid,
        96000.0,
        1,
        0,
        (5.0, 200.0),
        (5.0, 40.0),
        6.0,
        20.0,
        dataclasses.replace(realisation, fs=96001.0),
        0,
    )
    for got, other in zip(reused, apart, strict=True):
        assert got.type == other.type
        assert got.freq_hz == pytest.approx(other.freq_hz, rel=1e-3)


def escalation_target() -> tuple[np.ndarray, np.ndarray]:
    freqs = np.logspace(math.log10(3.0), math.log10(400.0), 200)
    target = np.clip(
        12.0 - 12.0 * np.log2(np.maximum(freqs, 6.0) / 6.0) / np.log2(25.0 / 6.0),
        0.0,
        None,
    )
    target[freqs > 30.0] = 0.0
    return freqs, target


def test_escalating_reaches_what_enumerating_reached() -> None:
    """The whole claim of the escalation: fewer tiers fitted, same cascade published.

    Enumeration is reconstructed here rather than kept in the code, so the equivalence is
    asserted against the rule it replaced instead of against itself.
    """
    freqs, target = escalation_target()
    realisation = F.Realisation()
    kwargs = dict(
        band_hz=(5.0, 200.0),
        max_gain_db=20.0,
        realisation=realisation,
        seeds=(0, 1),
        max_drift_db=3.0,
    )
    escalated = F.fit_minimal_biquads(target, freqs, 96000.0, 3, 0.5, **kwargs)

    # what the old code did: fit every tier, prune, screen, take the first that clears both
    screened = []
    for sections in range(1, 4):
        tasks = F._structure_tasks(
            target,
            freqs,
            96000.0,
            sections,
            (5.0, 200.0),
            (5.0, 200.0),
            6.0,
            20.0,
            realisation,
            (0, 1),
        )
        best = min(F._run_fits(tasks), key=lambda r: r[1])
        specs, residual = F._prune(
            (best[0], best[1]), target, freqs, 96000.0, (5.0, 200.0), 1.0
        )
        screened.append(
            (specs, residual, F._publishable(specs, residual, freqs, realisation, 3.0))
        )
    enumerated = next(
        ((s, r) for s, r, ok in screened if ok and r <= 0.5),
        min(
            [(s, r) for s, r, ok in screened if ok] or [(s, r) for s, r, _ in screened],
            key=lambda x: x[1],
        ),
    )

    assert escalated[1] == enumerated[1]
    assert [(f.type, f.freq_hz, f.gain_db, f.q) for f in escalated[0]] == [
        (f.type, f.freq_hz, f.gain_db, f.q) for f in enumerated[0]
    ]


def test_batching_targets_does_not_change_any_of_them() -> None:
    """Fitting several together must decide exactly what fitting each alone decides."""
    freqs, first = escalation_target()
    second = first * 0.6
    kwargs = dict(band_hz=(5.0, 200.0), max_gain_db=20.0, seeds=(0,))

    alone = [
        F.fit_minimal_biquads(t, freqs, 96000.0, 2, 0.5, **kwargs)
        for t in (first, second)
    ]
    together = F.fit_minimal_biquads_all(
        [F.FitRequest(first, label="a"), F.FitRequest(second, label="b")],
        freqs,
        96000.0,
        2,
        0.5,
        **kwargs,
    )
    for one, both in zip(alone, together, strict=True):
        assert one[1] == both[1]
        assert [(f.type, f.freq_hz, f.gain_db, f.q) for f in one[0]] == [
            (f.type, f.freq_hz, f.gain_db, f.q) for f in both[0]
        ]


def test_settling_skips_the_tier_that_is_most_of_the_budget() -> None:
    """Escalation has to actually escalate, or it is enumeration with extra steps.

    It defers the *top* section count only. That count is 59% of the budget on its own, and
    deferring the cheaper ones individually costs more in idle workers than it saves in
    unfitted tiers — see `_tiers`.
    """
    freqs, target = escalation_target()

    F.FIT_STATS.reset()
    F.fit_minimal_biquads(
        target, freqs, 96000.0, 4, 50.0, band_hz=(5.0, 200.0), seeds=(0,)
    )
    # 50 dB is met by one section, so the top tier is never fitted: 1 + 2 + 3 splits
    assert F.FIT_STATS.calls == 6

    F.FIT_STATS.reset()
    F.fit_minimal_biquads(
        target, freqs, 96000.0, 4, 0.0, band_hz=(5.0, 200.0), seeds=(0,)
    )
    # unreachable, so the whole budget is spent: 1 + 2 + 3 + 4 splits at one seed
    assert F.FIT_STATS.calls == 10


def test_the_tier_groups_defer_only_the_top_section_count() -> None:
    assert F._tiers(1) == [(1,)]
    assert F._tiers(2) == [(1,), (2,)]
    assert F._tiers(4) == [(1, 2, 3), (4,)]


def test_the_polish_cannot_leave_the_box_the_search_was_given() -> None:
    """Nelder-Mead is unbounded by default and `BiquadSpec` refuses what it wanders into.

    Not theoretical: this exact target and split reached `q must be > 0, got -0.012` and raised
    out of the middle of the fit, which inside a worker process ends the run. A point outside
    the bounds was never a candidate, so bounding the polish cannot lose a valid answer.
    """
    grid = np.logspace(math.log10(3.0), math.log10(400.0), 400)
    target = np.clip(14.0 * (1 - 1 / (1 + (25.0 / grid) ** 3)), 0, None)
    target = np.where(grid > 31.0, 0.0, target)

    specs, residual, _, _ = F._fit_structure(
        target,
        grid,
        96000.0,
        4,
        0,
        (5.0, 200.0),
        (5.0, 40.0),
        6.0,
        26.0,
        F.Realisation(),
        0,
    )
    assert len(specs) == 4
    for section in specs:
        assert 5.0 <= section.freq_hz <= 40.0
        assert 0.1 <= section.q <= 6.0
        assert abs(section.gain_db) <= 26.0
    assert math.isfinite(residual)


def test_the_fitting_loop_builds_the_same_coefficients_as_the_public_route() -> None:
    """`_sos_from_parameters` is a third copy of the RBJ formulae, so pin it to the others.

    AGENTS.md warns that they exist twice and must be fixed together; this makes three. The
    justification is that the public route builds a BiquadSpec, looks a class up in a dict,
    constructs an RBJ object and collects lists before making an array, which is a fifth of the
    cost function when it runs ten million times a run — and the justification only holds while
    the two agree exactly.
    """
    rng = np.random.default_rng(0)
    for _ in range(300):
        sections = int(rng.integers(1, 5))
        shelves = int(rng.integers(0, sections + 1))
        peaks = sections - shelves
        params = np.empty(3 * sections)
        for i in range(sections):
            params[3 * i : 3 * i + 3] = (
                rng.uniform(3.0, 400.0),
                rng.uniform(0.1, 6.0),
                rng.uniform(-30.0, 30.0),
            )
        public = F.biquad_sos(F._unpack(params, shelves, peaks), 96000.0)
        direct = F._sos_from_parameters(params, shelves, peaks, 96000.0)
        assert np.array_equal(public, direct), "the two RBJ paths have diverged"


def test_placement_reaches_far_up_and_not_at_all_down() -> None:
    """The asymmetry of `correction_band_hz`, with the magnitudes it was measured at.

    Reaching up is cheap and twice useful — a higher corner is better conditioned at 96 kHz, and
    it is what blends the correction into the programme above it. Reaching down puts a section's
    corner and Q where nothing was observed. Half an octave up cost title 1 its accepted filter
    once placement stopped being a fixed literal: its sections fell to 7.7 Hz and drifted 5.04 dB
    under publication rounding against a 3.0 limit.
    """
    from beqforge.filters import WIDEN_OCTAVES, correction_band_hz

    # a correction living over 8-15 Hz, with an evidence floor at 5
    target = np.where((FREQS >= 8.0) & (FREQS <= 15.0), 10.0, 0.0)
    low, high = correction_band_hz(target, FREQS, 5.0)

    active_low = float(FREQS[np.abs(target) >= 0.5].min())
    active_high = float(FREQS[np.abs(target) >= 0.5].max())
    assert low >= 5.0, "placement must never reach below the evidence floor"
    assert low == pytest.approx(active_low, rel=0.02), (
        "and it must not be widened downward either: the floor is a clamp, not a margin"
    )
    assert high == pytest.approx(active_high * 2.0**WIDEN_OCTAVES, rel=0.02)
    assert WIDEN_OCTAVES >= 2.0, (
        "measured: 1.5 octaves and below abstains on title 1, 2.0-2.5 accepts"
    )

    # the evidence floor wins when the correction reaches under it
    deep = np.where(FREQS <= 15.0, 10.0, 0.0)
    assert correction_band_hz(deep, FREQS, 9.0)[0] == 9.0
