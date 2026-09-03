"""Per-channel diagnostics of AUTOMATED_DESIGN.md §3.1 and §6.4 R2.

The level-independence test is the one with real content: it is the measurement that separates
"a filter was applied" from "the content is quieter down there", and it is the only thing in
the system that can make that distinction without a prior about what noise looks like. It is
testable against synthetic ground truth because both cases can be *constructed* — unlike
coherence (§11), which cannot.
"""

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


def test_a_fixed_filter_is_level_independent() -> None:
    """The defining property: a linear filter's relative response cannot vary with level."""
    signal_in = scened_noise(0, int(FS * DURATION_S))
    freqs, responses = stratified_response(high_passed(signal_in, 20.0), FS, PARAMS)
    stacked = np.vstack(list(responses.values()))
    band = (freqs >= 6.0) & (freqs <= 16.0)
    assert np.max(np.ptp(stacked, axis=0)[band]) < PARAMS.level_tolerance_db


def test_a_stationary_floor_is_not_level_independent() -> None:
    """A fixed floor under varying content reads as a varying attenuation, and should."""
    samples = int(FS * DURATION_S)
    rng = np.random.default_rng(1)
    content = high_passed(scened_noise(2, samples), 20.0, order=10)
    floor = rng.standard_normal(samples) * np.sqrt(np.mean(content**2)) * 0.004
    freqs, responses = stratified_response(content + floor, FS, PARAMS)
    stacked = np.vstack(list(responses.values()))
    band = (freqs >= 6.0) & (freqs <= 16.0)
    assert np.max(np.ptp(stacked, axis=0)[band]) > PARAMS.level_tolerance_db


def test_band_tracking_separates_content_from_a_stationary_floor() -> None:
    samples = int(FS * DURATION_S)
    rng = np.random.default_rng(3)
    content = scened_noise(4, samples)
    tracked = band_tracking(content, FS, (7.0, 13.0), PARAMS)
    floor = rng.standard_normal(samples)
    mixed = high_passed(content, 25.0, order=10) + floor * 0.002 * np.std(content)
    untracked = band_tracking(mixed, FS, (7.0, 13.0), PARAMS)
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
    freqs = np.linspace(5.0, 100.0, 50)
    shares = mix_shares(material, freqs)
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


def test_a_steep_but_inaudible_channel_is_not_the_rolloff() -> None:
    """The surrounds case: steep because they carry no bass, not because of a filter.

    Both real titles have surrounds falling away at 24-34 dB/octave while supplying 1-2% of
    passband power. Restoring one by tens of dB would invent content, so a slope alone must
    not be enough to call a channel filtered.
    """
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
    assert result.channels["Ls"].passband_share < DiagnoseParams().min_passband_share
    assert result.filtered_channels == ["LFE"]


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
    # a real filter is level-independent to the bottom of the band, not to 500 Hz
    assert result.filter_floor_hz <= 10.0
