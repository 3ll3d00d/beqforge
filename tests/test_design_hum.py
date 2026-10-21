"""A hum-removal comb is a repair, not programme texture (Glory, 2026-10)."""

import numpy as np
from scipy import signal

from beqforge.diagnose import mean_spectrum
from beqforge.material import Material
from beqforge.pipeline import (
    DESIGN_GRID,
    PipelineParams,
    _flat_deficit,
    fill_hum_notches,
    hum_notches,
    mains_hum_notches,
    passband_ripple_db,
)

FS = 1000


def _programme(notch_hz: float | None, seed: int = 3) -> Material:
    """Broadband noise high-passed at 30 Hz, optionally combed at every harmonic of `notch_hz`.

    The comb is constant-bandwidth (2 Hz at -3 dB), as a hum filter is: Glory's notches are
    2-3.4 Hz wide at -6 dB at 60, 120 and 180 Hz alike.
    """
    rng = np.random.default_rng(seed)
    samples = signal.sosfilt(
        signal.butter(4, 30.0, btype="high", fs=FS, output="sos"),
        rng.standard_normal(240 * FS),
    )
    if notch_hz is not None:
        for harmonic in np.arange(notch_hz, 200.0 + 1e-9, notch_hz):
            b, a = signal.iirnotch(harmonic, harmonic / 2.0, fs=FS)
            samples = signal.filtfilt(b, a, samples)
    return Material("hum", FS, samples * 0.01, {}, "complete_programme")


def test_a_comb_at_every_mains_harmonic_is_found():
    material = _programme(60.0)
    freqs, response = mean_spectrum(material.mono_mix, FS)
    assert mains_hum_notches(freqs, response, 40.0, 200.0) == (
        (57.5, 62.5),
        (117.5, 122.5),
        (177.5, 182.5),
    )


def test_programme_without_a_comb_has_none():
    for seed in range(1, 6):
        material = _programme(None, seed)
        freqs, response = mean_spectrum(material.mono_mix, FS)
        assert mains_hum_notches(freqs, response, 40.0, 200.0) == ()


def test_one_notched_harmonic_is_not_a_comb():
    material = _programme(None)
    b, a = signal.iirnotch(60.0, 30.0, fs=FS)  # 2 Hz wide
    notched = Material(
        "hum", FS, signal.filtfilt(b, a, material.mono_mix), {}, material.coverage
    )
    freqs, response = mean_spectrum(notched.mono_mix, FS)
    assert mains_hum_notches(freqs, response, 40.0, 200.0) == ()


def test_a_comb_does_not_read_as_ripple():
    params = PipelineParams()
    clean = passband_ripple_db(_programme(None), params)
    combed = passband_ripple_db(_programme(60.0), params)
    assert clean is not None and combed is not None
    assert abs(combed[0] - clean[0]) < 1.5


def _notched(material: Material, *harmonics: float) -> Material:
    samples = material.mono_mix
    for harmonic in harmonics:
        b, a = signal.iirnotch(harmonic, harmonic / 2.0, fs=FS)
        samples = signal.filtfilt(b, a, samples)
    return Material("hum", FS, samples, {}, material.coverage)


def test_one_notched_harmonic_is_found_on_its_own():
    """A single repair is enough to fill (TODO 29, F11): Bonnie and Clyde's 120 Hz had no 60."""
    freqs, response = mean_spectrum(_notched(_programme(None), 120.0).mono_mix, FS)
    assert hum_notches(freqs, response, 40.0, 200.0) == ((117.5, 122.5),)


def test_programme_without_a_notch_has_none_on_its_own():
    for seed in range(1, 6):
        freqs, response = mean_spectrum(_programme(None, seed).mono_mix, FS)
        assert hum_notches(freqs, response, 40.0, 200.0) == ()


def test_a_notch_on_a_falling_passband_is_found():
    """Measured about the surround's trend, not its floor, which a slope drags down.

    White Heat's 100 Hz notch sits where the passband falls away and scored 0.61 against the
    floor; a low-pass at 90 Hz puts this one on the same kind of slope.
    """
    falling = Material(
        "hum",
        FS,
        signal.sosfilt(
            signal.butter(4, 90.0, btype="low", fs=FS, output="sos"),
            _programme(None).mono_mix,
        ),
        {},
        "complete_programme",
    )
    freqs, response = mean_spectrum(_notched(falling, 100.0).mono_mix, FS)
    assert (97.5, 102.5) in hum_notches(freqs, response, 40.0, 200.0)


def test_a_filled_notch_reads_as_its_surround():
    freqs, response = mean_spectrum(_notched(_programme(None), 60.0).mono_mix, FS)
    filled = fill_hum_notches(freqs, response, 40.0, 200.0)
    inner = np.abs(freqs - 60.0) <= 2.5
    beside = (np.abs(freqs - 60.0) <= 10.0) & ~inner
    assert np.min(response[inner]) < np.min(response[beside]) - 6.0
    assert np.min(filled[inner]) >= np.min(response[beside])
    assert np.array_equal(filled[~inner], response[~inner])


def test_the_deficit_does_not_ask_to_lift_a_notch():
    """What every strategy's target is capped by reads a notch as the programme beside it."""
    params = PipelineParams()
    clean = _flat_deficit(_programme(None), params)
    notched = _flat_deficit(_notched(_programme(None), 60.0, 120.0), params)
    assert clean is not None and notched is not None
    near = (DESIGN_GRID > 50.0) & (DESIGN_GRID < 130.0)
    assert np.max(np.abs(notched[4][near] - clean[4][near])) < 1.0
