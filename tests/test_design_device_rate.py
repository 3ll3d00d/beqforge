"""R7: independent device-rate waveform, spectrum and headroom simulations."""

import numpy as np
import pytest
from scipy import signal

from beqanalyser.design import BiquadSpec, DESIGN_GRID
from beqanalyser.design.filters import (
    Realisation,
    biquad_sos,
    magnitude_db,
    publication_filters,
)
from beqanalyser.design.verify import device_waveform, waveform_peak, verify, _mean_db

FS = 1000


def programme():
    t = np.arange(8000) / FS
    # Deterministic, phase-sensitive multi-tone events, including the high-corner cases.
    envelope = np.exp(-(((t - 2) / 0.3) ** 2)) + 0.6 * np.exp(-(((t - 5) / 0.06) ** 2))
    return (
        envelope
        * sum(
            np.cos(2 * np.pi * f * t + phase)
            for f, phase in (
                (7, 0.3),
                (30, 1.2),
                (100, -0.7),
                (200, 0.9),
                (350, 1.4),
                (430, -0.1),
            )
        )
        / 6
    )


def reference(filters, samples, device, tail=0):
    """Run the published quantised SOS at the actual device rate, with sinc reconstruction."""
    ratio = int(device.fs / FS)
    padded = np.pad(samples, (FS, tail + FS))
    kernel = signal.firwin(2 * 64 * ratio + 1, 1 / ratio, window=("kaiser", 12))
    up = signal.resample_poly(padded, ratio, 1, window=kernel)
    actual = signal.sosfilt(
        device.quantise(biquad_sos(publication_filters(filters), device.fs)), up
    )
    return actual[FS * ratio : (FS + len(samples) + tail) * ratio]


@pytest.mark.parametrize("device_fs", [48000, 96000])
@pytest.mark.parametrize(
    "kind,corner,q",
    [
        ("low_shelf", 30, 0.707),
        ("low_shelf", 100, 0.707),
        ("low_shelf", 200, 0.707),
        ("peaking_eq", 200, 3),
        ("peaking_eq", 350, 1),
    ],
)
def test_complex_waveform_and_peak_match_device_rate_simulation(
    device_fs, kind, corner, q
):
    device = Realisation(fs=device_fs)
    filters = [BiquadSpec(kind, corner, 20, q)]
    samples = programme()
    expected = reference(filters, samples, device)
    actual = device_waveform(filters, samples, FS, device)
    ratio = int(device_fs / FS)
    # Phase matters: compare samples, not just magnitude or RMS levels.
    assert np.max(np.abs(actual - expected[::ratio])) / np.max(np.abs(expected)) < 2e-4
    peak_error_db = 20 * np.log10(waveform_peak(actual) / np.max(np.abs(expected)))
    assert abs(peak_error_db) < 0.05  # below the 0.1 dB acceptance decision quantum


def test_verify_spectrum_matches_device_rate_simulation():
    rng = np.random.default_rng(740)
    samples = signal.sosfilt(
        signal.butter(8, 400, fs=FS, output="sos"), rng.normal(size=30000)
    )
    samples *= signal.windows.tukey(len(samples), 0.25)
    filters = [
        BiquadSpec("low_shelf", 200, 20, 0.707),
        BiquadSpec("peaking_eq", 120, -8, 2),
    ]
    device = Realisation()
    expected = reference(filters, samples, device)[::96]
    freqs, expected_db = _mean_db(expected, FS)
    _, before_db = _mean_db(samples, FS)
    correction = verify(filters, samples, FS, realisation=device)
    band = (freqs >= 5) & (freqs <= 400)
    measured_gain = correction.after_db - correction.before_db
    np.testing.assert_allclose(
        measured_gain[band], (expected_db - before_db)[band], atol=0.01
    )


def test_high_corner_discrepancy_fixture_is_preserved():
    differences = []
    for corner in (30, 100, 200):
        filters = [BiquadSpec("low_shelf", corner, 20, 0.707)]
        differences.append(
            np.max(
                np.abs(
                    magnitude_db(biquad_sos(filters, FS), DESIGN_GRID, FS)
                    - magnitude_db(biquad_sos(filters, 96000), DESIGN_GRID, 96000)
                )
            )
        )
    np.testing.assert_allclose(differences, [0.0586, 0.6387, 2.3960], atol=0.001)


def test_headroom_uses_published_device_phase_quantisation_and_ringout(monkeypatch):
    from beqanalyser.design import pipeline
    from beqanalyser.design.material import Material

    samples = programme() * 8
    filters = [BiquadSpec("low_shelf", 200.004, 20.0004, 0.70704)]
    material = Material("peaks", FS, samples, {"L": samples}, "complete_programme")
    monkeypatch.setattr(pipeline, "bass_managed_sum", lambda *args, **kwargs: samples)
    offsets = []
    for device in (Realisation(fs=48000), Realisation(fs=96000, coefficient_bits=20)):
        expected = reference(filters, samples, device, tail=FS)
        offset = pipeline.required_gain_reduction_db(
            material, filters, pipeline.PipelineParams(realisation=device)
        )
        assert offset == pytest.approx(
            min(-20 * np.log10(np.max(np.abs(expected))), 0), abs=0.05
        )
        offsets.append(offset)
    assert abs(offsets[0] - offsets[1]) > 0.01


def test_unstable_device_cannot_supply_headroom():
    from beqanalyser.design.pipeline import PipelineParams, required_gain_reduction_db
    from beqanalyser.design.material import Material

    filters = [
        BiquadSpec(
            "low_shelf", 6.137080501313293, 20.453528341353397, 1.7655313695442572
        )
    ]
    samples = programme()
    with pytest.raises(ValueError, match="unstable"):
        device_waveform(filters, samples, FS)
    material = Material("unstable", FS, samples, {"L": samples}, "complete_programme")
    assert np.isnan(required_gain_reduction_db(material, filters, PipelineParams()))


def test_peak_interpolation_is_independent_of_block_boundaries():
    samples = np.zeros(140000)
    t = np.arange(-1000, 1000) / FS
    pulse = np.exp(-((t / 0.1) ** 2)) * np.cos(2 * np.pi * 430 * t + 0.7)
    peaks = []
    for centre in (65536, 66000):
        samples[:] = 0
        samples[centre - 1000 : centre + 1000] = pulse
        peaks.append(waveform_peak(samples))
    assert peaks[0] == pytest.approx(peaks[1], abs=1e-12)


def test_waveform_retains_filter_ringout_and_zero_padding_prevents_wrap():
    samples = programme()[-1000:].copy()
    samples[:] = 0
    t = np.arange(200) / FS
    samples[-200:] = np.sin(2 * np.pi * 30 * t) * signal.windows.tukey(200, 0.25)
    filters = [BiquadSpec("peaking_eq", 30, 30, 8)]
    device = Realisation(fs=48000)
    actual = device_waveform(filters, samples, FS, device, include_tail=True)
    expected = reference(filters, samples, device, tail=FS)[::48]
    assert len(actual) > len(samples)
    assert np.max(np.abs(actual[len(samples) :])) > 0.1
    np.testing.assert_allclose(actual[: len(expected)], expected, atol=2e-4)
    assert np.max(np.abs(actual[:100])) < 2e-4


def test_record_curves_use_declared_device_and_mark_unstable_waveforms():
    from beqanalyser.design import record
    from beqanalyser.design.charts import programme_levels_db
    from beqanalyser.design.material import Material

    samples = programme()
    material = Material("record", FS, samples, {"L": samples}, "complete_programme")
    device = Realisation(fs=48000)
    filters = [BiquadSpec("low_shelf", 200, 20, 0.707)]
    curves = record.curves_from(material, {"test": filters}, ["L"], device)
    expected = reference(filters, samples, device)[::48]
    before = programme_levels_db(samples, FS)
    levels = programme_levels_db(expected, FS, frame_index=before.loudest_index)
    np.testing.assert_allclose(
        curves["filtered"]["test"]["mono"]["average"], levels.average, atol=0.01
    )
    np.testing.assert_allclose(
        curves["filtered"]["test"]["mono"]["peak"], levels.peak, atol=0.01
    )
    assert curves["realisation"]["fs"] == 48000
    fragile = [
        BiquadSpec(
            "low_shelf", 6.137080501313293, 20.453528341353397, 1.7655313695442572
        )
    ]
    unstable = record.curves_from(material, {"unstable": fragile}, [], Realisation())
    assert not unstable["filtered"]
    assert "no finite waveform" in unstable["unavailable"]["unstable"]


def test_direct_charts_forward_the_device(tmp_path, monkeypatch):
    from beqanalyser.design import charts
    from beqanalyser.design.material import Material

    samples = programme()
    material = Material("chart", FS, samples, {}, "complete_programme")
    device = Realisation(fs=48000)
    seen = []

    def waveform(filters, samples, fs, realisation):
        seen.append(realisation)
        return samples

    monkeypatch.setattr(charts, "device_waveform", waveform)
    charts.render(
        "rate",
        [BiquadSpec("low_shelf", 200, 20, 0.707)],
        material,
        [],
        tmp_path,
        device,
    )
    assert seen == [device]
