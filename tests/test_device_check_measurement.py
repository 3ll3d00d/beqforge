import numpy as np
import pytest
from scipy.signal import resample_poly, sosfilt

from beqforge import BiquadSpec
from beqforge_device_check.coefficients import coefficients, response
from beqforge_device_check.measurement import (
    SweepSettings,
    capture_quality,
    recover,
    reference_delay,
    sweep,
)


@pytest.fixture(scope="module")
def stimulus():
    pytest.importorskip("pyfar")
    return sweep(SweepSettings(rate=48000, low_hz=5, duration_s=8, tail_s=8))


@pytest.mark.parametrize(
    "sections",
    [
        [],
        [BiquadSpec("peaking_eq", 10, 12, 6)],
        [BiquadSpec("low_shelf", 20, 9, 0.707), BiquadSpec("low_shelf", 20, -9, 0.707)],
    ],
)
def test_known_transfer_recovery_is_independent_of_prediction(stimulus, sections):
    x, metadata = stimulus
    sos = coefficients(sections, 48000)
    y = sosfilt(sos, x.astype(float)) if sections else x.astype(float)
    result = recover(x, y, metadata)
    assert result["valid"]
    expected = response(sos, result["frequencies"], 48000)
    mask = result["mask"]
    assert np.mean(mask) > 0.99
    error = 20 * np.log10(np.abs(result["response"][mask] / expected[mask]))
    assert np.max(np.abs(error)) < 0.002


def test_capture_quality_rejects_failure_modes(stimulus):
    x, metadata = stimulus
    assert "missing/truncated samples" in capture_quality(x[:-1], len(x))
    clipped = x.copy()
    clipped[10] = 1
    assert "capture clipping" in capture_quality(clipped, len(x))
    assert not recover(x, x, metadata, statuses=["input overflow"])["valid"]
    assert "silent capture" in capture_quality(np.zeros_like(x), len(x))


def test_a_device_that_saturates_below_full_scale_is_caught_by_its_flat_top():
    """A 2x4 HD clipped at 0.9986, under the 0.999 full-scale test, and went unnoticed."""
    rate, low = 48000, 5
    t = np.arange(rate * 2) / rate
    clean = 0.9986 * np.sin(2 * np.pi * low * t)
    assert capture_quality(clean, len(t), rate=rate, low_hz=low) == []
    clipped = np.clip(1.12 * np.sin(2 * np.pi * low * t), -0.9986, 0.9986)
    failures = capture_quality(clipped, len(t), rate=rate, low_hz=low)
    assert any("flat-topped at -0.012 dBFS" in f for f in failures)
    # Quiet content is held to its own crest, not to full scale.
    assert (
        capture_quality(
            0.003 * np.sin(2 * np.pi * low * t), len(t), rate=rate, low_hz=low
        )
        == []
    )


def test_independent_delay_and_clock_drift(stimulus):
    x, metadata = stimulus
    delay = 300
    reference = np.pad(x[:-delay], (delay, 0))
    measured_delay, drift = reference_delay(x, reference, metadata)
    assert measured_delay == delay and abs(drift) < 0.1
    result = recover(x, reference, metadata, reference=reference)
    assert result["valid"]
    np.testing.assert_allclose(np.abs(result["response"][result["mask"]]), 1, atol=1e-7)
    shifted = resample_poly(x, 10001, 10000)[: len(x)]
    assert not recover(x, shifted, metadata, reference=shifted)["valid"]


def test_noise_masks_under_range_without_fitting_away_gain(stimulus):
    x, metadata = stimulus
    y = x * 0.1 + np.random.default_rng(2).normal(0, 0.003, len(x))
    result = recover(x, y, metadata)
    assert result["valid"]
    assert np.mean(result["mask"]) < 0.5
    clean = recover(x, x * 0.1, metadata)
    np.testing.assert_allclose(np.abs(clean["response"][clean["mask"]]), 0.1, atol=1e-7)


def test_silent_timing_reference_is_named_not_reported_as_drift(stimulus):
    x, metadata = stimulus
    y = x.astype(float)
    # The reference path was never fed: only bench noise, ~90 dB below the sweep.
    silent = np.random.default_rng(3).normal(0, 1e-6, len(x))
    result = recover(x, y, metadata, reference=silent)
    assert not result["valid"]
    assert result["drift_ppm"] is None
    assert any("carries no stimulus" in failure for failure in result["failures"])
    # A fed reference still recovers.
    assert recover(x, y, metadata, reference=y)["valid"]


def test_long_delay_and_drift_on_a_short_low_frequency_sweep():
    pytest.importorskip("pyfar")
    # The bench's own case: a 5 s, 2-200 Hz sweep over a ~190 ms USB round trip.
    # Segment correlation picked lags from 736 to 19244 samples here.
    x, metadata = sweep(SweepSettings())
    delay = 18287
    for ppm in (0.0, 20.0):
        stretched = resample_poly(x.astype(float), 1_000_000 + int(ppm), 1_000_000)
        reference = np.pad(stretched, (delay, 0))[: len(x)]
        measured_delay, drift = reference_delay(x, reference, metadata)
        # Drift also scales frequency, which a log sweep cannot tell from a time shift of
        # L * eps (L = duration / ln(high / low)): about 2 samples at 20 ppm, under half a
        # sample within the 5 ppm a capture is accepted at.
        sweep_constant = 5 / np.log(100)
        allowance = 1 + sweep_constant * ppm * 1e-6 * 96000
        assert abs(measured_delay - delay) <= allowance
        assert drift == pytest.approx(ppm, abs=1.5)
