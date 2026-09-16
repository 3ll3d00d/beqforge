"""The parametric rolloff model.

The question the build order posed: is a free-slope model good enough, or does identification
need a discrete set of candidate alignments? These answer it. The model turns out to reproduce
Butterworth and Linkwitz-Riley *exactly* rather than approximately, so it identifies rather
than merely fits — and it declines on anything else.
"""

import numpy as np
import pytest

from beqforge import Alignment, HighPass
from beqforge.filters import high_pass_sos, magnitude_db
from beqforge.rolloff import (
    DB_PER_OCTAVE_PER_ORDER,
    attenuation_db,
    fit_rolloff,
    identify,
)

FS = 48000.0
FREQS = np.logspace(np.log10(2.0), np.log10(600.0), 700)
CORNER = 25.0
FIT_BAND = (0.4 * CORNER, 16.0 * CORNER)


def _response(alignment: Alignment, order: int, corner_hz: float) -> np.ndarray:
    return magnitude_db(
        high_pass_sos(HighPass(alignment, order, corner_hz), FS), FREQS, FS
    )


@pytest.mark.parametrize("order", [2, 4, 8])
def test_model_is_a_butterworth_high_pass_at_knee_twice_the_order(order: int) -> None:
    """Not an approximation — the algebra is an identity, so the error is float noise."""
    # the identity is exact in the analogue domain; ~1e-5 dB is the bilinear transform
    model = attenuation_db(FREQS, CORNER, order * DB_PER_OCTAVE_PER_ORDER, 2.0 * order)
    assert (
        np.max(np.abs(model - _response(Alignment.BUTTERWORTH, order, CORNER))) < 1e-4
    )


@pytest.mark.parametrize("order", [2, 4, 8])
def test_model_is_a_linkwitz_riley_high_pass_at_knee_equal_to_the_order(
    order: int,
) -> None:
    model = attenuation_db(FREQS, CORNER, order * DB_PER_OCTAVE_PER_ORDER, float(order))
    assert (
        np.max(np.abs(model - _response(Alignment.LINKWITZ_RILEY, order, CORNER)))
        < 1e-4
    )


@pytest.mark.parametrize(
    "alignment, order, knee_per_order",
    [
        (Alignment.BUTTERWORTH, 2, 2.0),
        (Alignment.BUTTERWORTH, 4, 2.0),
        (Alignment.BUTTERWORTH, 8, 2.0),
        (Alignment.LINKWITZ_RILEY, 2, 1.0),
        (Alignment.LINKWITZ_RILEY, 4, 1.0),
        (Alignment.LINKWITZ_RILEY, 8, 1.0),
    ],
)
def test_fit_recovers_corner_slope_and_alignment(
    alignment: Alignment, order: int, knee_per_order: float
) -> None:
    fit = fit_rolloff(_response(alignment, order, CORNER), FREQS, FIT_BAND)

    assert fit.corner_hz == pytest.approx(CORNER, abs=1e-3)
    assert fit.implied_order == pytest.approx(order, abs=1e-3)
    assert fit.knee == pytest.approx(knee_per_order * order, rel=1e-3)
    assert fit.residual_db < 1e-4

    identified = identify(fit)
    assert identified is not None
    assert identified.alignment is alignment
    assert identified.order == order
    assert identified.corner_hz == pytest.approx(CORNER, abs=1e-3)


def test_knee_separates_alignments_that_slope_alone_cannot() -> None:
    """Butterworth and Linkwitz-Riley of the same order have identical slopes."""
    butterworth = fit_rolloff(
        _response(Alignment.BUTTERWORTH, 4, CORNER), FREQS, FIT_BAND
    )
    linkwitz = fit_rolloff(
        _response(Alignment.LINKWITZ_RILEY, 4, CORNER), FREQS, FIT_BAND
    )
    assert butterworth.slope_db_per_octave == pytest.approx(
        linkwitz.slope_db_per_octave, rel=1e-4
    )
    assert butterworth.knee == pytest.approx(2.0 * linkwitz.knee, rel=1e-3)


@pytest.mark.parametrize("order", [2, 4, 8])
def test_bessel_is_declined_rather_than_misidentified(order: int) -> None:
    """§2.5. An alignment the model cannot represent must not come back as one it can."""
    fit = fit_rolloff(_response(Alignment.BESSEL_PHASE, order, CORNER), FREQS, FIT_BAND)
    assert fit.residual_db > 1e-2, "an unrepresentable rolloff must leave a residual"
    assert identify(fit) is None


def test_residual_separates_representable_from_unrepresentable() -> None:
    """The residual, not the section count, is what says whether the fit means anything."""
    representable = fit_rolloff(
        _response(Alignment.LINKWITZ_RILEY, 4, CORNER), FREQS, FIT_BAND
    ).residual_db
    unrepresentable = fit_rolloff(
        _response(Alignment.BESSEL_PHASE, 4, CORNER), FREQS, FIT_BAND
    ).residual_db
    assert unrepresentable > 100.0 * max(representable, 1e-9)


def test_noise_degrades_to_abstention_not_to_a_wrong_answer() -> None:
    """The expensive failure is confidently wrong, not silent (§2.3, §2.5)."""
    rng = np.random.default_rng(0)
    clean = _response(Alignment.BUTTERWORTH, 4, CORNER)
    wrong = 0
    corners = []
    for _ in range(60):
        fit = fit_rolloff(clean + rng.normal(0.0, 2.0, clean.shape), FREQS, FIT_BAND)
        corners.append(fit.corner_hz)
        identified = identify(fit)
        if identified is not None and (
            identified.alignment is not Alignment.BUTTERWORTH or identified.order != 4
        ):
            wrong += 1

    assert wrong == 0
    assert np.mean(corners) == pytest.approx(CORNER, abs=0.5)


def test_corner_is_reported_not_clamped_when_it_falls_outside_the_usual_range() -> None:
    """§2.1 — a 55 Hz rolloff is unusual, never unrepresentable."""
    fit = fit_rolloff(_response(Alignment.BUTTERWORTH, 4, 55.0), FREQS, (20.0, 500.0))
    assert fit.corner_hz == pytest.approx(55.0, abs=1e-2)
