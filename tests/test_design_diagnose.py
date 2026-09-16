"""Per-channel spectral and temporal features; no causal mastering classification."""

import numpy as np
import pytest
from scipy import signal

from beqanalyser.design.diagnose import (
    DiagnoseParams,
    band_slope,
    band_tracking,
    diagnose,
    mix_shares,
    steepest_slope,
    stratified_response,
)
from beqanalyser.design.material import Material

FS = 1000.0
DURATION_S = 600.0
PARAMS = DiagnoseParams()

REFERENCE_HZ = (22.0, 35.0)
"""Reference band for the synthetic cases, which are built with a known passband.

Real material derives this per channel via `plateau_reference`; stating it here keeps these
tests about the statistic under test rather than about the reference."""


def scened_noise(seed: int, samples: int) -> np.ndarray:
    """Broadband noise with scene-scale level variation, so strata are not all alike."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(samples)
    scenes = rng.standard_normal(samples // int(FS * 10) + 1).repeat(int(FS * 10))
    envelope = 10.0 ** (2.0 * scenes[:samples] / 20.0 * 6.0)
    return noise * envelope


def high_passed(samples: np.ndarray, corner_hz: float, order: int = 8) -> np.ndarray:
    sos = signal.butter(order, corner_hz, btype="high", fs=FS, output="sos")
    return signal.sosfilt(sos, samples)


def test_common_envelope_source_remains_level_independent_after_filtering() -> None:
    """This particular source has a common spectral envelope in every stratum."""
    signal_in = scened_noise(0, int(FS * DURATION_S))
    freqs, responses = stratified_response(
        high_passed(signal_in, 20.0), FS, PARAMS, REFERENCE_HZ
    )
    stacked = np.vstack(list(responses.values()))
    band = (freqs >= 6.0) & (freqs <= 16.0)
    assert np.max(np.ptp(stacked, axis=0)[band]) < PARAMS.level_tolerance_db


def test_a_stationary_floor_is_not_level_independent() -> None:
    """A fixed floor under varying content reads as a varying attenuation, and should."""
    samples = int(FS * DURATION_S)
    rng = np.random.default_rng(1)
    content = high_passed(scened_noise(2, samples), 20.0, order=10)
    floor = rng.standard_normal(samples) * np.sqrt(np.mean(content**2)) * 0.004
    freqs, responses = stratified_response(content + floor, FS, PARAMS, REFERENCE_HZ)
    stacked = np.vstack(list(responses.values()))
    band = (freqs >= 6.0) & (freqs <= 16.0)
    assert np.max(np.ptp(stacked, axis=0)[band]) > PARAMS.level_tolerance_db


def test_band_tracking_separates_content_from_a_stationary_floor() -> None:
    samples = int(FS * DURATION_S)
    rng = np.random.default_rng(3)
    content = scened_noise(4, samples)
    tracked = band_tracking(content, FS, (7.0, 13.0), PARAMS, REFERENCE_HZ)
    floor = rng.standard_normal(samples)
    mixed = high_passed(content, 25.0, order=10) + floor * 0.002 * np.std(content)
    untracked = band_tracking(mixed, FS, (7.0, 13.0), PARAMS, REFERENCE_HZ)
    assert tracked > PARAMS.tracking_floor
    assert untracked < tracked


def test_steepest_slope_finds_a_wall_a_band_slope_misses() -> None:
    freqs = np.logspace(np.log10(4.0), np.log10(200.0), 400)
    wall = np.where(freqs >= 20.0, 0.0, -60.0 * np.log2(20.0 / np.maximum(freqs, 1e-9)))
    wall = np.maximum(wall, -45.0)
    steep, at = steepest_slope(wall, freqs, (4.0, 200.0))
    assert steep > 40.0
    assert 12.0 < at < 21.0
    assert abs(band_slope(wall, freqs, 4.0, 200.0)) < steep / 2.0


def material_from(channels: dict[str, np.ndarray]) -> Material:
    from beqanalyser.design.material import LFE_GAIN, MAIN_GAIN

    mix = sum(
        (LFE_GAIN if name == "LFE" else MAIN_GAIN) * data
        for name, data in channels.items()
    )
    return Material(
        name="synthetic",
        fs=int(FS),
        mono_mix=np.asarray(mix),
        channels=channels,
        coverage="complete_programme",
    )


def test_mix_shares_sum_to_one() -> None:
    samples = int(FS * 120.0)
    material = material_from(
        {
            "L": scened_noise(5, samples),
            "C": scened_noise(6, samples),
            "LFE": scened_noise(7, samples),
        }
    )
    shares = mix_shares(material)
    assert sum(shares.values()) == pytest.approx(
        np.ones(len(next(iter(shares.values())))), abs=0.02
    )


def test_diagnose_finds_the_filtered_channel_and_leaves_the_others() -> None:
    """The second title's structure: one walled channel among unfiltered mains."""
    samples = int(FS * DURATION_S)
    material = material_from(
        {
            "L": scened_noise(8, samples),
            "C": scened_noise(9, samples),
            "LFE": high_passed(scened_noise(10, samples), 20.0, order=10),
        }
    )
    result = diagnose(material)
    assert result.filtered_channels == ["LFE"]
    assert not result.channels["L"].is_filtered
    assert not result.channels["C"].is_filtered
    # the lower edge of the steepest half-octave; for a maximally flat wall it sits below
    # the corner, where the stopband is steepening, not at the corner itself
    assert 8.0 < result.channels["LFE"].max_slope_hz < 22.0


def test_original_quietness_does_not_gate_a_channel_proposal() -> None:
    """An originally quiet channel must supply its own support if restored."""
    samples = int(FS * DURATION_S)
    quiet_surround = high_passed(scened_noise(11, samples), 22.0, order=10) * 0.03
    material = material_from(
        {
            "L": scened_noise(12, samples),
            "C": scened_noise(13, samples),
            "LFE": high_passed(scened_noise(14, samples), 20.0, order=10),
            "Ls": quiet_surround,
        }
    )
    result = diagnose(material)
    assert result.channels["Ls"].max_slope_db_per_octave > 20.0
    assert result.channels["Ls"].passband_share < 0.05
    assert result.filtered_channels == ["LFE", "Ls"]
    assert np.max(result.channels["Ls"].boost_allowance(1.645, 0.5)) == 0


def test_the_filter_floor_is_searched_down_from_the_passband() -> None:
    """Above the passband strata diverge on content, which must not stop the search.

    A top-down search returns the top of the spectrum on both real titles, because loud
    scenes have a different content spectrum up there. The floor is only meaningful below
    the passband.
    """
    samples = int(FS * DURATION_S)
    walled = high_passed(scened_noise(15, samples), 20.0, order=10)
    material = material_from(
        {
            "L": scened_noise(16, samples),
            "C": scened_noise(17, samples),
            "LFE": walled,
        }
    )
    result = diagnose(material)
    # The combined source changes shape across strata despite the fixed LFE filter.
    from beqanalyser.design.diagnose import plateau_reference

    _, plateau = plateau_reference(result.mix_db, result.freqs, PARAMS)
    assert result.filter_floor_hz <= plateau[0]


def test_the_plateau_reference_follows_the_channel_not_a_constant() -> None:
    """Two channels filtered at different corners get different references.

    The band this replaced was fixed at 22-35 Hz, which on real material sat on one title's
    knee and understated its mains by 13-17 dB. The reference has to move with the channel.
    """
    low_corner = high_passed(scened_noise(80, int(FS * 180)), 12.0, order=6)
    high_corner = high_passed(scened_noise(80, int(FS * 180)), 45.0, order=6)
    result = diagnose(material_from({"C": low_corner, "LFE": high_corner}))
    assert (
        result.channels["LFE"].plateau_hz[0] > result.channels["C"].plateau_hz[0] * 1.5
    )


def test_the_plateau_reference_clears_the_knee() -> None:
    """The reference must sit above the corner, or attenuation is measured against itself."""
    material = material_from(
        {"C": high_passed(scened_noise(81, int(FS * 180)), 30.0, order=8)}
    )
    channel = diagnose(material).channels["C"]
    assert channel.plateau_hz[0] > 30.0
    # and the response it produces is referenced there, so 30 Hz reads as attenuated
    freqs = diagnose(material).freqs
    assert np.interp(30.0, freqs, channel.response_db) < 0.0
    assert np.interp(15.0, freqs, channel.response_db) < -20.0


def test_the_passband_envelope_is_the_same_however_it_is_obtained() -> None:
    """`diagnose` computes it once and hands it to every band; a lone call computes its own.

    Both have to be the same number, or hoisting it changed the measurement rather than
    just when it was taken.
    """
    from beqanalyser.design.diagnose import band_tracking, scene_envelope

    samples = scened_noise(7, int(FS * 120.0))
    params = DiagnoseParams()
    reference_hz = (30.0, 80.0)
    band_hz = (8.0, 16.0)

    computed_inside = band_tracking(samples, FS, band_hz, params, reference_hz)
    hoisted = band_tracking(
        samples,
        FS,
        band_hz,
        params,
        reference_hz,
        reference=scene_envelope(samples, FS, reference_hz, params),
    )
    assert computed_inside == hoisted


def test_shares_are_the_same_whether_or_not_the_spectra_are_supplied() -> None:
    """`diagnose` already has every channel's spectrum; taking it twice was half its Welch."""
    from beqanalyser.design.diagnose import mean_spectrum, mix_shares

    material = material_from(
        {
            "L": scened_noise(11, int(FS * 60.0)),
            "LFE": high_passed(scened_noise(12, int(FS * 60.0)), 20.0, order=6),
        }
    )
    spectra = {
        name: mean_spectrum(samples, material.fs)[1]
        for name, samples in material.channels.items()
    }
    on_its_own = mix_shares(material)
    supplied = mix_shares(material, spectra)
    assert set(on_its_own) == set(supplied)
    for name in on_its_own:
        assert np.array_equal(on_its_own[name], supplied[name])


def test_the_moving_average_matches_the_convolution_it_replaces() -> None:
    """A prefix-sum difference is the same quantity, computed 64x faster and less exactly.

    Asserted to a tolerance rather than to the bit, because it genuinely is not bit-identical:
    the prefix sum accumulates rounding over the whole signal where the convolution accumulates
    it over one window. The bound here is what that costs on a realistic length.
    """
    from beqanalyser.design.diagnose import _moving_average

    rng = np.random.default_rng(0)
    for length, width in ((10_000, 400), (250_000, 4_000)):
        values = (
            rng.random(length) ** 2
        )  # positive, like the squared samples it averages
        expected = np.convolve(values, np.ones(width) / width, mode="valid")
        assert np.allclose(_moving_average(values, width), expected, rtol=0, atol=1e-12)


def test_the_moving_average_handles_degenerate_widths() -> None:
    from beqanalyser.design.diagnose import _moving_average

    values = np.arange(5.0)
    assert np.array_equal(_moving_average(values, 1), values)
    assert np.array_equal(_moving_average(values, 99), values)
    assert _moving_average(values, 5) == pytest.approx([2.0])
