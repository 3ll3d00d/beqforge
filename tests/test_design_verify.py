"""Applying the design and measuring what it did — AUTOMATED_DESIGN.md §6.2.

The residual says the cascade matches the target it was handed. It cannot say the target was
right. This is the check that catches the difference, and the criterion is the one a person
uses: a correct rolloff correction leaves the low end flat, or mildly rising at the bottom.
"""

import numpy as np
import pytest

from beqanalyser.design import Alignment, BiquadSpec, HighPass
from beqanalyser.design.filters import invert_to_shelves
from beqanalyser.design.harness import SyntheticProfile, apply_high_pass, synthesise
from beqanalyser.design.verify import verify

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
    correction = verify(exact, rolled_off, FS, band_hz=(6.0, 16.0))

    assert correction.improvement_db > 10.0
    assert abs(correction.tilt_db_per_octave) < 2.0
    assert correction.concerns() == []


def test_doing_nothing_is_reported_as_under_corrected(rolled_off: np.ndarray) -> None:
    nothing = [BiquadSpec("peaking_eq", 30.0, 0.0, 1.0)]
    correction = verify(nothing, rolled_off, FS, band_hz=(6.0, 16.0))

    assert correction.tilt_db_per_octave > 2.0
    assert any("under-corrected" in c for c in correction.concerns())


def test_over_correction_is_reported_as_over_corrected(rolled_off: np.ndarray) -> None:
    """The failure the residual is blindest to: a filter that fits its target and overshoots."""
    too_much = invert_to_shelves(
        HighPass(Alignment.LINKWITZ_RILEY, 4, 55.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 4.0),
    )
    correction = verify(too_much, rolled_off, FS, band_hz=(6.0, 16.0))

    # tilt saturates near -1.5 dB/oct however far the corner is overshot, because the inverse
    # of a much higher corner is flat across this band; only the level runs away
    assert correction.level_db > 8.0
    assert abs(correction.tilt_db_per_octave) < 2.0
    assert any("over-corrected" in c for c in correction.concerns())


def test_improvement_is_negative_when_the_filter_makes_things_worse(
    rolled_off: np.ndarray,
) -> None:
    wrong_way = [BiquadSpec("low_shelf", 12.0, -18.0, 0.7)]
    correction = verify(wrong_way, rolled_off, FS, band_hz=(6.0, 16.0))

    assert correction.improvement_db < 0.0
    assert any("less flat" in c for c in correction.concerns())
