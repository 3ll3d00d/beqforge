"""R6: measure the sub output without treating bass management as a content deficit."""

from dataclasses import replace

import numpy as np
import pytest
from scipy import signal

from beqforge import BiquadSpec, DESIGN_GRID, pipeline, record
from beqforge.accept import assess
from beqforge.diagnose import Diagnosis, plateau_reference, DiagnoseParams
from beqforge.filters import Realisation, biquad_sos, magnitude_db
from beqforge.material import (
    Material,
    PlaybackParams,
    bass_managed_sum,
    MAIN_GAIN,
    LFE_GAIN,
)
from beqforge.verify import verify, device_waveform, _mean_db


def material(phase=0.0):
    rng = np.random.default_rng(812)
    main = rng.normal(size=15000) * signal.windows.tukey(15000, 0.1)
    lfe = 0.8 * np.real(signal.hilbert(main) * np.exp(1j * phase))
    return Material(
        "playback",
        1000,
        MAIN_GAIN * main + LFE_GAIN * lfe,
        {"L": main, "LFE": lfe},
        "complete_programme",
    )


def reference_sub(subject, crossover):
    # Independently spell out the declared topology, including its two distinct LP stages.
    section = signal.butter(2, crossover, fs=1000, btype="low", output="sos")
    lp = np.concatenate([section, section])
    main = signal.sosfilt(lp, subject.channels["L"]) * 10 ** (-20.2 / 20)
    lfe = subject.channels["LFE"] * 10 ** (-10.2 / 20)
    return signal.sosfilt(lp, main + lfe)


@pytest.mark.parametrize("corner", [20.0, 80.0, 160.0])
@pytest.mark.parametrize("phase", [0.0, np.pi / 2, np.pi])
def test_sub_verification_below_around_and_above_crossover(corner, phase):
    from tests.test_design_device_rate import reference

    subject = material(phase)
    filters = [BiquadSpec("low_shelf", corner, 8, 0.707)]
    model = PlaybackParams()
    sub = bass_managed_sum(subject, model.crossover_hz)
    np.testing.assert_array_equal(sub, reference_sub(subject, 80))
    correction = verify(
        filters,
        sub,
        1000,
        band_hz=(5, 200),
        reference_samples=subject.mono_mix,
        playback_model=model.description(),
    )
    freqs, before = _mean_db(sub, 1000)
    expected = reference(filters, sub, Realisation())[::96]
    _, after = _mean_db(expected, 1000)
    used = (freqs >= 5) & (freqs <= 200)
    np.testing.assert_allclose(
        correction.playback_after_db[used], after[used], atol=0.01
    )
    np.testing.assert_array_equal(correction.playback_before_db, before)
    _, programme = _mean_db(subject.mono_mix, 1000)
    level, _ = plateau_reference(programme, freqs, DiagnoseParams())
    np.testing.assert_allclose(correction.before_db, programme - level, atol=1e-12)
    np.testing.assert_allclose(
        correction.after_db + correction.playback_baseline_db + level,
        correction.playback_after_db,
        atol=1e-12,
    )
    assert correction.signal_domain == "sub_output_relative_to_playback"
    assert "sub output" in correction.playback_model
    # The measured sub output is materially different from filtering the full-band mix.
    _, naive = _mean_db(device_waveform(filters, subject.mono_mix, 1000), 1000)
    assert abs(np.interp(160, freqs, correction.playback_after_db - naive)) > 6


def test_playback_baseline_is_fixed_before_correction_and_preserves_crossover():
    subject = material()
    sub = bass_managed_sum(subject)
    a = verify(
        [BiquadSpec("low_shelf", 20, 0, 0.707)],
        sub,
        1000,
        reference_samples=subject.mono_mix,
        band_hz=(5, 200),
    )
    filters = [BiquadSpec("high_shelf", 80, 30, 0.707)]
    b = verify(filters, sub, 1000, reference_samples=subject.mono_mix, band_hz=(5, 200))
    np.testing.assert_array_equal(a.playback_baseline_db, b.playback_baseline_db)
    assert np.interp(160, a.freqs, a.playback_baseline_db) < -20
    # Giving the judge the same (wrong) target cannot license flattening the crossover.
    target = magnitude_db(biquad_sos(filters, 96000), DESIGN_GRID, 96000)
    verdict = assess(filters, b, float("nan"), target_db=target)
    assert not verdict.passed
    assert any("above anything" in reason for reason in verdict.failures)


def test_pipeline_records_actual_playback_domain(monkeypatch):
    subject = material(np.pi / 2)
    params = pipeline.PipelineParams(playback=PlaybackParams(crossover_hz=120))
    monkeypatch.setattr(pipeline, "judged_band_hz", lambda *args: (5, 200))
    candidate = pipeline._judge(
        "playback",
        [BiquadSpec("low_shelf", 20, 6, 0.707)],
        None,
        0.0,
        subject,
        Diagnosis(DESIGN_GRID, np.zeros_like(DESIGN_GRID), {}),
        params,
    )
    payload = record._candidate(candidate)["correction"]
    assert payload["signal_domain"] == "sub_output_relative_to_playback"
    assert "120 Hz" in payload["playback_model"]
    assert payload["playback_before_db"] is not None
    assert payload["playback_after_db"] is not None
    assert payload["playback_baseline_db"] is not None
    assert any("sub output" in note for note in candidate.verdict.notes)


def test_mono_only_abstains_with_unavailable_playback_reason(monkeypatch):
    from tests.test_design_evidence import envelopes_with_margin

    subject = replace(material(), channels={})
    monkeypatch.setattr(pipeline, "extract", lambda *args: envelopes_with_margin(12))
    monkeypatch.setattr(pipeline, "identify_rolloff", lambda *args: None)
    report = pipeline.run(subject)
    assert not report.candidates
    assert any(
        "playback verification unavailable" in note for note in report.evidence_notes
    )


def test_silent_sub_feed_cannot_supply_verification():
    subject = material()
    with pytest.raises(ValueError, match="silent sub feed"):
        verify(
            [],
            np.zeros_like(subject.mono_mix),
            1000,
            reference_samples=subject.mono_mix,
        )
