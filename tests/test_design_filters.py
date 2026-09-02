"""The output stage of AUTOMATED_DESIGN.md §5.

The closed-form claim is the load-bearing one: when the protective filter shares the rolloff's
alignment and order, the exact inverse *is* a low shelf cascade. These pin that down.
"""

import math

import numpy as np
import pytest

from beqanalyser.design import (
    BIQUAD_BUDGET,
    Alignment,
    BiquadSpec,
    ExactInversionUnavailable,
    HighPass,
)
from beqanalyser.design.filters import (
    Realisation,
    biquad_sos,
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
