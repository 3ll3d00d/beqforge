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


def test_independent_delay_and_clock_drift(stimulus):
    x, metadata = stimulus
    delay = 300
    reference = np.pad(x[:-delay], (delay, 0))
    measured_delay, drift = reference_delay(x, reference, 48000)
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
