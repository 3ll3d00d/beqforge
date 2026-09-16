"""Applying the design and measuring what it did.

The residual says the cascade matches the target it was handed. It cannot say the target was
right. This is the check that catches the difference, and the criterion is the one a person
uses: a correct rolloff correction leaves the low end flat, or mildly rising at the bottom.
"""

import numpy as np
import pytest

from beqanalyser.design import Alignment, BiquadSpec, HighPass
from beqanalyser.design.filters import invert_to_shelves
from beqanalyser.design.harness import SyntheticProfile, apply_high_pass, synthesise
from beqanalyser.design.verify import Correction, verify

FS = 1000.0


@pytest.fixture(scope="module")
def rolled_off() -> np.ndarray:
    source = synthesise(
        SyntheticProfile(duration_s=1200.0, event_rate_hz=0.08), FS, seed=17
    )
    return apply_high_pass(source, HighPass(Alignment.LINKWITZ_RILEY, 4, 18.0), FS)


def test_the_exact_inverse_leaves_the_low_end_flat(rolled_off: np.ndarray) -> None:
    exact = invert_to_shelves(
        HighPass(Alignment.LINKWITZ_RILEY, 4, 18.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 4.0),
    )
    correction = verify(exact, rolled_off, FS, band_hz=(6.0, 45.0))

    assert correction.improvement_db > 10.0
    assert abs(correction.tilt_db_per_octave) < 2.0
    assert correction.concerns() == []


def test_doing_nothing_is_reported_as_under_corrected(rolled_off: np.ndarray) -> None:
    nothing = [BiquadSpec("peaking_eq", 30.0, 0.0, 1.0)]
    correction = verify(nothing, rolled_off, FS, band_hz=(6.0, 45.0))

    assert correction.tilt_db_per_octave > 2.0
    assert any("under-corrected" in c for c in correction.concerns())


def test_over_correction_is_reported_as_over_corrected(rolled_off: np.ndarray) -> None:
    """The failure the residual is blindest to: a filter that fits its target and overshoots."""
    too_much = invert_to_shelves(
        HighPass(Alignment.LINKWITZ_RILEY, 4, 55.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 4.0),
    )
    correction = verify(too_much, rolled_off, FS, band_hz=(6.0, 45.0))

    assert correction.tilt_db_per_octave < -2.0
    assert correction.level_db > 8.0
    assert any("over-corrected" in c for c in correction.concerns())


def test_level_catches_an_overshoot_that_tilt_alone_would_miss(
    rolled_off: np.ndarray,
) -> None:
    """Over a band narrower than the correction, tilt saturates and only level moves.

    Measured across 6-16 Hz, inverting an 18 Hz rolloff as if its corner were anywhere from 34
    to 70 Hz gives a tilt of a couple of dB/oct — the inverse is at its plateau there, so the
    shape barely changes however far the overshoot goes. The level does not saturate: it runs to
    nearly 40 dB. Widening the band is the better fix and is now the default, but the metric
    earns its place for any caller that narrows it again.

    The tilt figure moved from ~1.2 to ~2.8 dB/oct when `verify` began reporting the curve the
    *device* realises rather than the one the optimiser designed. This cascade is the extreme
    case for that — `invert_to_shelves` puts sections at a 4 Hz protective corner, where
    `1+a1+a2` is a fraction of one quantisation step — so it is a fair illustration of why
    coefficient rounding is judged at all, and it leaves the point of this test untouched.
    """
    too_much = invert_to_shelves(
        HighPass(Alignment.LINKWITZ_RILEY, 4, 55.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 4.0),
    )
    narrow = verify(too_much, rolled_off, FS, band_hz=(6.0, 16.0))

    assert abs(narrow.tilt_db_per_octave) < 3.0
    assert narrow.level_db > 8.0
    assert any("above the shape asked for" in c for c in narrow.concerns())


def test_improvement_is_negative_when_the_filter_makes_things_worse(
    rolled_off: np.ndarray,
) -> None:
    wrong_way = [BiquadSpec("low_shelf", 12.0, -18.0, 0.7)]
    correction = verify(wrong_way, rolled_off, FS, band_hz=(6.0, 45.0))

    assert correction.improvement_db < 0.0
    assert any("less flat" in c for c in correction.concerns())


GRID = np.logspace(np.log10(4.0), np.log10(60.0), 240)
JUDGED = (5.0, 45.0)


def _flat(after_db: float, before_db: float = -12.0) -> Correction:
    """A perfectly smooth corrected curve at a chosen level. Isolates level from wobble."""
    return Correction(
        freqs=GRID,
        before_db=np.full_like(GRID, before_db),
        after_db=np.full_like(GRID, after_db),
        band_hz=JUDGED,
    )


def test_the_smoke_test_takes_its_thresholds_from_the_acceptance_model() -> None:
    """It has to agree with `accept`, and a private copy of three numbers is not agreement.

    `concerns` used to restate `spread_margin_db`, `max_tilt_db` and `level_range_db` as its own
    defaults, so tuning the model would have left this warning about shapes the model accepts.
    """
    import dataclasses

    from beqanalyser.design.accept import AcceptParams

    hot = _flat(2.5)
    assert not any("above the shape asked for" in c for c in hot.concerns())
    narrowed = dataclasses.replace(AcceptParams(), level_tolerance_db=1.0)
    assert any("above the shape asked for" in c for c in hot.concerns(narrowed))


def test_flatness_sees_a_level_error_that_wobble_cannot() -> None:
    """The ranking statistic. Two smooth curves, one on plateau and one 4 dB hot."""
    on_level = _flat(-0.4)
    hot = _flat(3.7)
    assert on_level.wobble_db(on_level.after_db) == pytest.approx(
        hot.wobble_db(hot.after_db), abs=1e-9
    ), "wobble cannot tell these apart, which is the whole problem"
    assert on_level.departure_db() < hot.departure_db()
    # and against a request the hot one matches, the ordering reverses
    assert hot.departure_db(2.0) < on_level.departure_db(2.0)
