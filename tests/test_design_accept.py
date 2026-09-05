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


def test_spread_is_judged_against_the_material_not_a_constant() -> None:
    """A smooth cascade cannot flatten wobble the mean spectrum already has.

    All three real titles depart from a smooth trend by 5.8-6.7 dB, so an absolute limit near
    6 dB sits on the floor of what is achievable and fails correct answers.
    """
    from beqanalyser.design.accept import spectral_roughness

    def wobble(f):
        return 3.2 * np.sin(np.log2(f / 5.0) * 4.0)

    # the same quality of correction, applied to smooth and to rough material. Centred so the
    # wobble stays inside the level envelope, or this measures the extent clause instead.
    rough = correction(lambda f: -13.0 + wobble(f), lambda f: 1.5 + wobble(f))
    smooth = correction(lambda f: -13.0, lambda f: 1.5)

    assert spectral_roughness(rough) > 5.0
    assert spectral_roughness(smooth) < 0.5
    assert rough.spread_db > 6.0  # would fail any absolute limit near 6 dB

    specs = [BiquadSpec("low_shelf", 17.0, 11.5, 0.73)]
    assert assess(specs, rough, noise_floor_hz=float("nan")).passed
    assert assess(specs, smooth, noise_floor_hz=float("nan")).passed


def test_drift_is_measured_over_publication_rounding_not_one_point() -> None:
    """A cancelling cascade can measure well at the optimiser's exact output and badly once
    published. Two shelves that do not fight each other must stay tight under the same jitter.
    """
    from beqanalyser.design.filters import drift_distribution
    from beqanalyser.design.filters import Realisation

    grid = np.logspace(np.log10(3.0), np.log10(400.0), 400)
    realisation = Realisation()
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
    fragile = drift_distribution(cancelling, grid, realisation)
    robust = drift_distribution(clean, grid, realisation)
    # the fragile cascade's spread is the signal; a point estimate cannot see it
    assert fragile.max() > 5.0 * fragile.min()
    assert np.percentile(fragile, 90) > np.percentile(robust, 90)
    assert robust.max() < fragile.max()


def test_a_turnover_is_rejected_though_the_overall_tilt_looks_fine() -> None:
    """ "Too much too soon and then a rolloff" — full boost reached above the band's bottom.

    The third title's design measured -0.72 dB/octave over 5-45 Hz, which reads as mildly
    rising, while falling at +4.11 below its peak at 18 Hz. A single fit across the band
    averages the rise above the peak against the fall below it and sees neither.
    """
    from beqanalyser.design.accept import turnover_db_per_octave

    # peaks near 18 Hz, falls away below it, rises toward the reference above
    def after(f):
        # a V in log-frequency: falls away below 18 Hz, and rises above it steeply enough
        # that a single fit across the whole band nets out to almost nothing
        return (
            6.0 - 4.2 * abs(np.log2(f / 18.0))
            if f < 18.0
            else 6.0 - 3.4 * np.log2(f / 18.0)
        )

    turning = correction(
        lambda f: -20.0 + 14.0 * np.log2(f / 5.0) / np.log2(9.0), after
    )
    slope, peak = turnover_db_per_octave(turning, AcceptParams())
    assert slope > 2.0
    assert 14.0 < peak < 24.0
    assert abs(turning.tilt_db_per_octave) < 2.0  # the overall fit does not see it

    verdict = assess(
        [BiquadSpec("low_shelf", 20.0, 19.0, 0.86)],
        turning,
        noise_floor_hz=float("nan"),
    )
    assert not verdict.passed
    assert any("too much too soon" in f for f in verdict.failures)


def test_a_monotone_correction_has_no_turnover() -> None:
    from beqanalyser.design.accept import turnover_db_per_octave

    flat = correction(lambda f: -13.0, lambda f: -1.0 - 0.4 * np.log2(f / 5.0))
    slope, _ = turnover_db_per_octave(flat, AcceptParams())
    assert slope <= 0.0


def test_under_correction_is_not_reported_as_a_turnover() -> None:
    """A peak at the band's top edge is plain under-correction, which tilt already reports."""
    from beqanalyser.design.accept import turnover_db_per_octave

    sagging = correction(lambda f: -16.0, lambda f: 2.0 - 2.5 * np.log2(45.0 / f))
    slope, _ = turnover_db_per_octave(sagging, AcceptParams())
    assert slope == 0.0
    verdict = assess(
        [BiquadSpec("low_shelf", 20.0, 8.0, 0.7)], sagging, noise_floor_hz=float("nan")
    )
    assert not any("too much too soon" in f for f in verdict.failures)
    assert any("under-corrected" in f for f in verdict.failures)


def test_bin_noise_does_not_terminate_the_extent() -> None:
    """A flat correction scatters below an absolute line; that is the material, not the filter.

    A hand-built design that is flat to +-1.5 dB across 5-40 Hz still put 17 of 164 bins below
    -3 dB, worst -3.9, in runs up to 0.7 Hz wide. Stopping at the first of them reported the
    correction as reaching only 25.9 Hz and rejected a filter a person judged correct.
    """
    rng = np.random.default_rng(0)
    noise = rng.normal(0.0, 1.1, len(FREQS))
    flat = correction(lambda f: -18.0, lambda f: -1.3)
    speckled = Correction(
        freqs=FREQS,
        before_db=flat.before_db + noise,
        after_db=flat.after_db + noise,
        band_hz=BAND,
    )
    assert (speckled.after_db < -3.0).sum() > 5  # genuinely dips out, in single bins
    assert corrected_extent_hz(speckled, AcceptParams()) <= BAND[0] * 1.05


def test_a_correction_that_genuinely_stops_is_still_caught() -> None:
    """The clause exists for gross failure: 13 dB out, not 0.9."""
    stopping = correction(lambda f: -13.0, lambda f: -1.5 if f >= 14.0 else -13.0)
    assert 12.0 < corrected_extent_hz(stopping, AcceptParams()) < 16.0


def test_a_correction_below_the_level_independence_floor_is_noted_not_failed() -> None:
    """R2 is a confidence claim, not a bound.

    Title 2's accepted design boosts through the region where the LFE's attenuation stops
    being level-independent, and is right to — the content there is real, just reproduced
    14 dB down. What was missing was anything in the output saying which part of a
    correction rests on a measured filter and which part is shaping.
    """
    flat = correction(lambda f: -12.0 + 6.0 * np.log2(f / 5.0), lambda f: 0.0)
    shelf = [BiquadSpec("low_shelf", 20.0, 12.0, 0.7)]

    silent = assess(shelf, flat, float("nan"))
    noted = assess(shelf, flat, float("nan"), filter_floor_hz=19.5)

    assert not any("shaping" in n for n in silent.notes)
    assert any("shaping" in n for n in noted.notes)
    assert noted.passed == silent.passed, "R2 must not change the verdict"


def test_a_correction_entirely_above_the_floor_is_not_noted() -> None:
    """The note has to mean something, so it only fires where the boost actually is."""
    flat = correction(lambda f: -12.0 + 6.0 * np.log2(f / 5.0), lambda f: 0.0)
    shelf = [BiquadSpec("low_shelf", 20.0, 12.0, 0.7)]
    assert not any(
        "shaping" in n
        for n in assess(shelf, flat, float("nan"), filter_floor_hz=3.5).notes
    )


def test_flatness_does_not_re_charge_a_correction_for_its_tilt() -> None:
    """`spread` includes the trend; `roughness` removes one. That is not like for like.

    A perfectly smooth corrected curve rising within the tilt clause's own limits scores a
    large spread purely from the tilt, so the flatness clause was mostly re-reading a
    judgement the tilt clause had already made — and on material with real wobble the two
    together could reject a correction neither objected to on its own.
    """
    from beqanalyser.design.accept import corrected_wobble, spectral_roughness

    smooth_rise = correction(lambda f: -13.0, lambda f: -1.7 * np.log2(f / 15.0))
    assert smooth_rise.spread_db > 4.0, "the tilt alone should span several dB"
    assert corrected_wobble(smooth_rise) < 0.5, "but it carries no wobble at all"
    assert abs(smooth_rise.tilt_db_per_octave) < 2.5, "and the tilt itself is allowed"

    verdict = assess(
        [BiquadSpec("low_shelf", 17.0, 11.5, 0.73)],
        smooth_rise,
        noise_floor_hz=float("nan"),
    )
    assert not any("expected flat" in f for f in verdict.failures), verdict.failures
    assert spectral_roughness(smooth_rise) < 0.5


def test_the_turnover_peak_is_located_on_a_smoothed_curve() -> None:
    """A single noisy bin must not decide which segment the turnover is measured over.

    The extent clause was already fixed for exactly this — the material scatters by ~6 dB and
    a raw `argmax` locates a bin rather than a peak. On the third title's corrected curve the
    raw argmax read the turnover as +0.00 dB/oct and the smoothed one as +1.70.
    """
    from beqanalyser.design.accept import turnover_db_per_octave

    # a genuine turnover: rising to a peak at ~18 Hz, then falling away below it
    shape = curve(lambda f: -4.0 * abs(np.log2(f / 18.0)))
    spike = np.zeros_like(shape)
    spike[np.argmin(np.abs(FREQS - 40.0))] = 9.0  # one bin of scatter near the band top

    clean = Correction(
        freqs=FREQS, before_db=curve(lambda f: -13.0), after_db=shape, band_hz=BAND
    )
    speckled = Correction(
        freqs=FREQS,
        before_db=curve(lambda f: -13.0),
        after_db=shape + spike,
        band_hz=BAND,
    )

    slope, peak = turnover_db_per_octave(clean, AcceptParams())
    spiked_slope, spiked_peak = turnover_db_per_octave(speckled, AcceptParams())
    assert slope > 2.0, "the turnover is real and should be caught"
    assert spiked_slope > 2.0, "one bin must not hide it"
    assert abs(np.log2(spiked_peak / peak)) < 0.5, (
        f"peak moved from {peak:.1f} to {spiked_peak:.1f} Hz on one bin"
    )


def test_a_turnover_the_material_already_has_is_not_the_correction_s() -> None:
    """The peak a corrected curve falls away from may be one the filter never touched.

    Title 1's mix is +8.6 dB at 20 Hz against its own 40 Hz level — an authored hump, +14.2 dB
    in the LFE — so `flatten` correctly asks for no boost across 12-31 Hz. The hump survives
    into the corrected curve as its in-band peak, and everything below it reads as falling
    away from it. The input turns over at +12.23 dB/oct unaided; the candidate left +3.2 and
    was rejected for a fourfold improvement.
    """
    humped = correction(
        lambda f: 8.0 * np.exp(-((np.log2(f / 20.0) / 0.45) ** 2)) - 14.0 * (f < 14.0),
        lambda f: 8.0 * np.exp(-((np.log2(f / 20.0) / 0.45) ** 2)),
    )
    shelf = [BiquadSpec("low_shelf", 12.0, 14.0, 0.7)]
    verdict = assess(shelf, humped, noise_floor_hz=float("nan"))
    assert verdict.turnover_before > 4.0, "the fixture's material should turn over"
    assert verdict.turnover_after < verdict.turnover_before
    assert not any("too much too soon" in f for f in verdict.failures), verdict.failures


def test_a_turnover_the_correction_creates_is_still_rejected() -> None:
    """Flat material, so the tolerance collapses to the old absolute limit.

    Title 3's input turns over at +0.00 dB/oct, and its parametric candidate at +4.1 fails
    exactly as it did before the clause became comparative.
    """
    turning = correction(lambda f: 0.0, lambda f: -4.0 * abs(np.log2(f / 18.0)))
    verdict = assess(
        [BiquadSpec("low_shelf", 18.0, 10.0, 0.7)], turning, noise_floor_hz=float("nan")
    )
    assert verdict.turnover_before < 1.0
    assert verdict.turnover_after > 2.0
    assert any("too much too soon" in f for f in verdict.failures)
