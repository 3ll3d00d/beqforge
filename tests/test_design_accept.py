"""The acceptance model of AUTOMATED_DESIGN.md §6.4.

R1's cliff clause is the one worth pinning down. Every aggregate the pipeline already had —
spread, tilt, level — scores a notch-filling design well, and the design is wrong. These tests
construct that case directly rather than relying on real material to produce it.
"""

import numpy as np
import pytest

from beqanalyser.design import BiquadSpec
from beqanalyser.design.accept import (
    AcceptParams,
    assess,
    corrected_extent_hz,
    worst_gradient,
)
from beqanalyser.design.verify import Correction

FREQS = np.logspace(np.log10(4.0), np.log10(60.0), 240)
BAND = (5.0, 45.0)


def curve(shape) -> np.ndarray:
    return np.array([shape(f) for f in FREQS])


def correction(before, after, band=BAND) -> Correction:
    return Correction(
        freqs=FREQS, before_db=curve(before), after_db=curve(after), band_hz=band
    )


def test_worst_gradient_finds_a_step_a_mean_slope_hides() -> None:
    """A cliff is local; a band-wide fit averages it away."""
    step = curve(lambda f: 0.0 if f >= 14.0 else -9.0)
    gradient, at = worst_gradient(FREQS, step, BAND, 0.25)
    assert gradient > 20.0
    assert 12.0 < at < 15.0
    # the same curve fitted across the band reads as a gentle slope
    octaves = np.log2(FREQS / FREQS[0])
    in_band = (FREQS >= BAND[0]) & (FREQS <= BAND[1])
    assert abs(np.polyfit(octaves[in_band], step[in_band], 1)[0]) < 5.0


def test_a_smooth_shelf_has_no_cliff() -> None:
    """No local excess: the worst window matches the curve's own slope everywhere."""
    gradient, _ = worst_gradient(
        FREQS, curve(lambda f: -6.0 + 2.0 * np.log2(f)), BAND, 0.25
    )
    assert gradient == pytest.approx(2.0, abs=0.05)


def test_extent_stops_where_the_curve_leaves_the_envelope() -> None:
    """Flat down to 14 Hz then falling away is corrected to 14 Hz, not to 5."""
    partial = correction(lambda f: -14.0, lambda f: -1.0 if f >= 14.0 else -14.0)
    assert 12.0 < corrected_extent_hz(partial, AcceptParams()) < 16.0


def test_extent_reaches_the_bottom_when_the_whole_band_is_flat() -> None:
    full = correction(lambda f: -14.0, lambda f: -1.0)
    assert corrected_extent_hz(full, AcceptParams()) <= BAND[0] * 1.05


def test_relocating_a_cliff_is_rejected() -> None:
    """The notch-filling design of §11: flat over what it covers, cliff moved down."""
    before = lambda f: 0.0 if f >= 23.0 else -13.0  # noqa: E731
    after = lambda f: -1.5 if f >= 14.0 else -13.0  # noqa: E731
    verdict = assess(
        [BiquadSpec("low_shelf", 18.0, 6.0, 1.0)],
        correction(before, after),
        noise_floor_hz=float("nan"),
    )
    assert not verdict.passed
    assert any("cliff" in f or "corrected only down to" in f for f in verdict.failures)


def test_removing_a_cliff_is_accepted() -> None:
    before = lambda f: 0.0 if f >= 23.0 else -13.0  # noqa: E731
    verdict = assess(
        [BiquadSpec("low_shelf", 17.0, 11.5, 0.73)],
        correction(before, lambda f: -1.5),
        noise_floor_hz=float("nan"),
    )
    assert verdict.passed, verdict.failures


def test_under_correction_is_rejected_on_tilt() -> None:
    verdict = assess(
        [BiquadSpec("low_shelf", 17.0, 4.0, 0.7)],
        correction(lambda f: -14.0, lambda f: -10.0 + 3.0 * np.log2(f / 5.0)),
        noise_floor_hz=float("nan"),
    )
    assert not verdict.passed


def test_a_no_op_section_has_not_earned_its_slot() -> None:
    """§5.1 parsimony, as a check rather than a fitting heuristic."""
    verdict = assess(
        [
            BiquadSpec("low_shelf", 17.0, 11.5, 0.73),
            BiquadSpec("peaking_eq", 105.0, 0.02, 1.0),
        ],
        correction(lambda f: -13.0, lambda f: -1.5),
        noise_floor_hz=float("nan"),
    )
    assert not verdict.passed
    assert any("earned its slot" in f for f in verdict.failures)


def test_high_q_is_noted_but_not_a_failure() -> None:
    """Q is downstream of the target (§11); it warrants a note, never a rejection."""
    verdict = assess(
        [BiquadSpec("low_shelf", 17.0, 11.5, 4.6)],
        correction(lambda f: -13.0, lambda f: -1.5),
        noise_floor_hz=float("nan"),
    )
    assert verdict.notes and "Q above 4" in verdict.notes[0]
    assert not any("Q" in f for f in verdict.failures)


def test_a_correction_stopping_above_the_content_is_rejected() -> None:
    """R1's extent clause: flat down to 20 Hz is not enough when content runs to 5."""
    partial = correction(lambda f: -13.0, lambda f: -1.5 if f >= 20.0 else -13.0)
    verdict = assess(
        [BiquadSpec("low_shelf", 22.0, 11.0, 0.7)], partial, noise_floor_hz=float("nan")
    )
    assert not verdict.passed
    assert any("content continues to" in f for f in verdict.failures)


def test_the_same_correction_is_fine_when_content_stops_there() -> None:
    """Nothing below 20 Hz to recover, so stopping at 20 Hz is the right answer."""
    partial = correction(lambda f: -13.0, lambda f: -1.5 if f >= 20.0 else -13.0)
    verdict = assess(
        [BiquadSpec("low_shelf", 22.0, 11.0, 0.7)], partial, noise_floor_hz=20.0
    )
    assert not any("content continues to" in f for f in verdict.failures)


def test_a_lumpy_correction_is_rejected_on_spread() -> None:
    """Flat is part of R1. Without this a +6 dB mid-band lump passed with no objection."""
    lumpy = correction(
        lambda f: -13.0,
        lambda f: -1.0 + 7.0 * np.exp(-(((np.log2(f / 22.0)) / 0.25) ** 2)),
    )
    verdict = assess(
        [BiquadSpec("low_shelf", 21.0, 12.0, 1.0)], lumpy, noise_floor_hz=float("nan")
    )
    assert not verdict.passed
    assert any("expected flat" in f for f in verdict.failures)


def test_drift_is_measured_over_publication_rounding_not_one_point() -> None:
    """A cancelling cascade can measure well at the optimiser's exact output and badly once
    published. Two shelves that do not fight each other must stay tight under the same jitter.
    """
    from beqanalyser.design.accept import drift_distribution
    from beqanalyser.design.filters import Realisation

    grid = np.logspace(np.log10(3.0), np.log10(400.0), 400)
    params, realisation = AcceptParams(), Realisation()
    cancelling = [
        BiquadSpec("low_shelf", 10.59, 14.36, 0.945),
        BiquadSpec("peaking_eq", 8.36, 1.29, 4.110),
        BiquadSpec("peaking_eq", 7.17, -0.85, 5.688),
        BiquadSpec("peaking_eq", 10.59, -3.63, 5.349),
    ]
    clean = [
        BiquadSpec("low_shelf", 19.74, 2.32, 2.495),
        BiquadSpec("low_shelf", 16.23, 10.93, 0.744),
    ]
    fragile = drift_distribution(cancelling, grid, params, realisation)
    robust = drift_distribution(clean, grid, params, realisation)
    # the fragile cascade's spread is the signal; a point estimate cannot see it
    assert fragile.max() > 5.0 * fragile.min()
    assert np.percentile(fragile, 90) > np.percentile(robust, 90)
    assert robust.max() < fragile.max()
