"""The acceptance model.

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

    The clause is comparative, so the same corrected curve is asked twice: against material
    that is flat below the peak, where the fall is the filter's doing and is rejected, and
    against material already falling faster than that over the same segment, where it is not.
    The second case is what the fixture used to assert the opposite of — its material rises
    14 dB across the band, which *is* a fall of 4.41 dB/octave toward the bottom, and the
    candidate leaving 4.19 there was being rejected for very slightly improving on it.
    """
    from beqanalyser.design.accept import turnover_db_per_octave

    # peaks near 18 Hz, falls away below it, and falls again above it steeply enough that a
    # single fit across the whole band nets out to almost nothing
    def after(f):
        return (
            6.0 - 4.2 * abs(np.log2(f / 18.0))
            if f < 18.0
            else 6.0 - 3.4 * np.log2(f / 18.0)
        )

    turning = correction(lambda f: -13.0, after)
    slope, material, peak = turnover_db_per_octave(turning, AcceptParams())
    assert slope > 2.0
    assert abs(material) < 0.5, "flat material gives the absolute limit back"
    assert 14.0 < peak < 24.0
    assert abs(turning.tilt_db_per_octave) < 2.0  # the overall fit does not see it

    verdict = assess(
        [BiquadSpec("low_shelf", 20.0, 19.0, 0.86)],
        turning,
        noise_floor_hz=float("nan"),
    )
    assert not verdict.passed
    assert any("too much too soon" in f for f in verdict.failures)

    # the same correction, over material that already falls faster than it does
    steep = correction(lambda f: -20.0 + 14.0 * np.log2(f / 5.0) / np.log2(9.0), after)
    steep_slope, steep_material, _ = turnover_db_per_octave(steep, AcceptParams())
    assert steep_slope == pytest.approx(slope), "the corrected curve is unchanged"
    assert steep_material > steep_slope, "the material falls faster over that segment"
    assert not any(
        "too much too soon" in f
        for f in assess(
            [BiquadSpec("low_shelf", 20.0, 19.0, 0.86)],
            steep,
            noise_floor_hz=float("nan"),
        ).failures
    )


def test_a_monotone_correction_has_no_turnover() -> None:
    from beqanalyser.design.accept import turnover_db_per_octave

    flat = correction(lambda f: -13.0, lambda f: -1.0 - 0.4 * np.log2(f / 5.0))
    slope, _, _ = turnover_db_per_octave(flat, AcceptParams())
    assert slope <= 0.0


def test_under_correction_is_not_reported_as_a_turnover() -> None:
    """A peak at the band's top edge is plain under-correction, which tilt already reports."""
    from beqanalyser.design.accept import turnover_db_per_octave

    sagging = correction(lambda f: -16.0, lambda f: 2.0 - 2.5 * np.log2(45.0 / f))
    slope, _, _ = turnover_db_per_octave(sagging, AcceptParams())
    assert slope == 0.0
    verdict = assess(
        [BiquadSpec("low_shelf", 20.0, 8.0, 0.7)], sagging, noise_floor_hz=float("nan")
    )
    assert not any("too much too soon" in f for f in verdict.failures)
    assert any("tilts" in f and "was intended" in f for f in verdict.failures)


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

    slope, _, peak = turnover_db_per_octave(clean, AcceptParams())
    spiked_slope, _, spiked_peak = turnover_db_per_octave(speckled, AcceptParams())
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


def test_the_material_baseline_survives_a_peak_at_the_band_s_top_edge() -> None:
    """A mix rising to its plateau must still supply a baseline, not a silent 0.0.

    The regression this pins: the baseline used to be the slope below the *material's own*
    peak, and a mix rises toward its plateau, so that peak sits within half an octave of the
    band's top edge — on seven of the eight titles measured. The interior guard then returned
    0.0 and the clause became the absolute 2.0 dB/octave test it was written to replace.
    Nocturnal Animals' restored candidate was rejected on that reading, at 2.31 against a
    material that falls 5.27 dB/octave over the same segment.
    """
    from beqanalyser.design.accept import turnover_db_per_octave

    # material rising monotonically to the top of the band: its own argmax is the last bin
    rising = correction(
        lambda f: -16.0 + 5.2 * np.log2(f / 5.0),
        # corrected: flat above 18 Hz, falling away below it at ~2.3 dB/octave
        lambda f: -1.0 if f >= 18.0 else -1.0 - 2.3 * np.log2(18.0 / f),
    )
    slope, material, peak = turnover_db_per_octave(rising, AcceptParams())
    assert 14.0 < peak < 24.0, "the segment comes from the corrected curve"
    assert slope > 2.0, "the corrected curve does fall away below its peak"
    assert material > 4.0, (
        f"the material falls faster over that same segment, measured {material:.2f}; a "
        "baseline of 0.0 here is the bug"
    )

    verdict = assess(
        [BiquadSpec("low_shelf", 18.0, 6.0, 0.7)], rising, noise_floor_hz=float("nan")
    )
    assert not any("too much too soon" in f for f in verdict.failures), verdict.failures


def test_headroom_is_the_clipping_it_causes_not_the_gain_it_asks_for() -> None:
    """§4.2's headroom is reported, never gated — §14.3: headroom is output-only.

    A BEQ runs post bass management on the sub channel only, so a boost costs no master volume —
    what it can cost is clipping the sub feed. The caller measures that and passes it in, because
    only the caller has the signal. The cascade's peak *magnitude* is not a substitute: measured
    against the real quantity it is close to inverted, with +45.7 dB filters needing 0.00 dB of
    reduction and +18.2 dB ones needing 4.4.

    §14.3: whether a given gain reduction is acceptable depends on the playback chain, which is
    a choice for the caller, not the designer — the contract's §2 is explicit that headroom is
    output-only. So this is carried through to `Verdict.required_offset_db` and reported, and
    never fails a candidate on its own, however large.
    """
    flat = correction(lambda f: -12.0, lambda f: 0.0)
    big = [BiquadSpec("low_shelf", 20.0, 24.0, 0.7)]

    # a large boost that happens to clip nothing is fine, however large
    free = assess(big, flat, noise_floor_hz=float("nan"), required_offset_db=0.0)
    assert not any("clipping" in f for f in free.failures), free.failures
    assert free.required_offset_db == 0.0

    # one that needs a large gain reduction is reported, not rejected for it
    clipping = assess(big, flat, noise_floor_hz=float("nan"), required_offset_db=-4.4)
    assert not any("clipping" in f for f in clipping.failures), clipping.failures
    assert clipping.passed, clipping.failures
    assert clipping.required_offset_db == -4.4


def test_a_band_too_short_to_carry_a_slope_is_said_so_once() -> None:
    """Blazing Saddles leaves 0.42 octaves above its own noise floor.

    Over that span its candidate reads -7.32 dB/octave to 45 Hz and -0.02 to 80 Hz, so every
    clause downstream of tilt is reporting where the band stopped. One stated reason beats five
    numbers measured on nothing.
    """
    narrow = correction(lambda f: -12.0, lambda f: 0.0, band=(33.7, 45.0))
    verdict = assess(
        [BiquadSpec("low_shelf", 20.0, 12.0, 0.7)], narrow, noise_floor_hz=33.7
    )
    assert not verdict.passed
    assert len(verdict.failures) == 1, verdict.failures
    assert "octaves left to judge" in verdict.failures[0]

    wide = correction(lambda f: -12.0, lambda f: 0.0, band=(5.0, 45.0))
    assert not any(
        "octaves left to judge" in f
        for f in assess(
            [BiquadSpec("low_shelf", 20.0, 12.0, 0.7)],
            wide,
            noise_floor_hz=float("nan"),
        ).failures
    )


def test_a_section_must_earn_its_slot_inside_the_judged_band() -> None:
    """A bass correction's correction is in the bass.

    Measured across the whole 3-400 Hz design grid, a cascade can spend sections on the midrange
    and be credited for it: Nocturnal Animals' `flatten` candidate passed with peaking sections
    at 214 and 341 Hz, Q 6.0, worth 1.94 and 1.72 dB over the grid and 0.00 dB over the band the
    result is judged on. That became reachable when the placement ceiling opened to
    `WIDEN_OCTAVES`, so the two checks belong together.
    """
    flat = correction(lambda f: -13.0, lambda f: -1.5)
    useful = [BiquadSpec("low_shelf", 17.0, 11.5, 0.73)]
    assert assess(useful, flat, noise_floor_hz=float("nan")).passed

    parked = useful + [BiquadSpec("peaking_eq", 341.0, -1.7, 6.0)]
    verdict = assess(parked, flat, noise_floor_hz=float("nan"))
    assert not verdict.passed
    earned = [f for f in verdict.failures if "earned its slot" in f]
    assert earned, verdict.failures
    assert "341" in earned[0] and "5-45 Hz" in earned[0], earned[0]


def test_boosting_below_the_noise_floor_is_caught() -> None:
    """The one clause that looks below where the judged band starts.

    The band starts at `noise_floor_hz` because a correction is not expected to have achieved
    anything underneath it — but a low shelf acts there regardless, and nothing else was looking.
    Blazing Saddles has no programme content below 33.7 Hz and a candidate that lifted 5-20 Hz by
    +5 to +11 dB passed every other clause for exactly that reason.
    """
    # flat material from 20 Hz up, a deep hole below it, and a filter that fills the hole in
    lifted = Correction(
        freqs=FREQS,
        before_db=curve(lambda f: -1.0 if f >= 20.0 else -21.0),
        after_db=curve(lambda f: -1.0 if f >= 20.0 else 11.0),
        band_hz=(20.0, 60.0),
    )
    verdict = assess(
        [BiquadSpec("low_shelf", 24.0, 24.0, 0.7)], lifted, noise_floor_hz=20.0
    )
    assert not verdict.passed
    assert any("not content" in f for f in verdict.failures), verdict.failures


def test_an_authored_hump_is_not_an_overshoot() -> None:
    """The bar is the material's own level where that is higher than the request.

    Title 1's mix is +5.8 dB at 20 Hz — an authored feature — and its filter leaves +5.0 there.
    The filter did not put it there and must not be charged for it.
    """
    humped = correction(
        lambda f: 5.8 if 17.0 <= f <= 24.0 else -13.0,
        lambda f: 5.0 if 17.0 <= f <= 24.0 else -1.5,
    )
    verdict = assess(
        [BiquadSpec("low_shelf", 17.0, 11.5, 0.73)], humped, noise_floor_hz=float("nan")
    )
    assert not any("not content" in f for f in verdict.failures), verdict.failures


@pytest.mark.parametrize("corner_hz, stable", [(5.0, False), (15.0, True)])
def test_device_stability_is_required_even_when_the_corrected_shape_passes(
    corner_hz, stable
) -> None:
    from scipy import signal

    from beqanalyser.design.filters import Realisation, biquad_sos
    from beqanalyser.design.verify import verify

    filters = [BiquadSpec("low_shelf", corner_hz, 20.0, 0.7)]
    device = Realisation()
    sos = biquad_sos(filters, 1000)
    inverse = sos[:, [3, 4, 5, 0, 1, 2]].copy()
    inverse[:, :3] /= inverse[:, 3:4]
    inverse[:, 4:] /= inverse[:, 3:4]
    inverse[:, 3] = 1.0
    samples = signal.sosfilt(
        inverse, np.random.default_rng(42).normal(size=300000)
    )
    corrected = verify(filters, samples, 1000, realisation=device)
    verdict = assess(filters, corrected, float("nan"), realisation=device)
    rounded = device.quantise(biquad_sos(filters, device.fs))
    if not stable:
        assert rounded[0, 3:].sum() == 0.0
        assert rounded[0, :3].sum() != 0.0
        assert not verdict.passed
        assert any("not stable" in failure for failure in verdict.failures)
        assert all("not stable" in failure for failure in verdict.failures)
    else:
        assert verdict.passed, verdict.failures
