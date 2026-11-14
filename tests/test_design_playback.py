"""R6: measure the sub output without treating bass management as a content deficit."""

from dataclasses import replace

import numpy as np
import pytest
from scipy import signal

from beqforge import DESIGN_GRID, BiquadSpec, pipeline, record
from beqforge.accept import assess
from beqforge.diagnose import DiagnoseParams, Diagnosis, plateau_reference
from beqforge.filters import Realisation, biquad_sos, magnitude_db
from beqforge.material import (
    LFE_GAIN,
    MAIN_GAIN,
    Material,
    PlaybackParams,
    bass_managed_sum,
)
from beqforge.verify import _mean_db, device_waveform, verify


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
    # the over-lift bar catches it, at the bass ceiling where the shelf rises above it
    assert any(
        "above anything" in reason or "bass ceiling" in reason
        for reason in verdict.failures
    )


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


def test_one_lowpass_on_every_channel_is_the_bus_lowpass_alone():
    """beqdesigner's "Before": an LR4 on each channel, LFE included, then the sum (TODO 1)."""
    subject = material()
    model = PlaybackParams(
        mains_lowpass_hz=None, main_gain_db=-18.24, lfe_gain_db=-8.24
    )
    section = signal.butter(2, 80, fs=1000, btype="low", output="sos")
    lp = np.concatenate([section, section])
    before = signal.sosfilt(lp, subject.channels["L"]) * 10 ** (-18.24 / 20)
    before += signal.sosfilt(lp, subject.channels["LFE"]) * 10 ** (-8.24 / 20)
    np.testing.assert_allclose(
        bass_managed_sum(subject, playback=model), before, atol=1e-12
    )


def test_no_lowpass_at_all_is_the_weighted_sum():
    subject = material()
    model = PlaybackParams(mains_lowpass_hz=None, sub_lowpass_hz=None)
    expected = subject.channels["L"] * 10 ** (-20.2 / 20) + subject.channels[
        "LFE"
    ] * 10 ** (-10.2 / 20)
    np.testing.assert_allclose(bass_managed_sum(subject, playback=model), expected)


@pytest.mark.parametrize(
    "filters",
    [
        [],
        [BiquadSpec("low_shelf", 20, 12, 0.707)],
        # unstable at the published coefficients: the magnitude path, not a waveform
        [BiquadSpec("low_shelf", 6.137080501313293, 20.453528341353397, 1.77)],
    ],
)
@pytest.mark.parametrize("reference", [True, False])
def test_unfiltered_spectra_measured_once_verify_as_if_remeasured(filters, reference):
    """`run` measures the candidate-independent spectra once (`measure_unfiltered`)."""
    from beqforge.verify import measure_unfiltered

    subject = material()
    sub = bass_managed_sum(subject)
    kwargs = {
        "band_hz": (5, 140),
        "diagnose_params": DiagnoseParams(),
        "exclude_bands_hz": ((150.0, 160.0),),
        "reference_samples": subject.mono_mix if reference else None,
    }
    shared = measure_unfiltered(
        sub,
        1000,
        kwargs["diagnose_params"],
        kwargs["exclude_bands_hz"],
        kwargs["reference_samples"],
    )
    alone = verify(filters, sub, 1000, **kwargs)
    given = verify(filters, sub, 1000, **kwargs, unfiltered=shared)
    for name in (
        "freqs",
        "before_db",
        "after_db",
        "playback_before_db",
        "playback_after_db",
        "playback_baseline_db",
    ):
        a, b = getattr(alone, name), getattr(given, name)
        assert (a is None) == (b is None), name
        if a is not None:
            np.testing.assert_array_equal(a, b)
    assert alone.reference_level_db == given.reference_level_db


def test_unfiltered_spectra_of_other_signals_are_refused():
    from beqforge.verify import measure_unfiltered

    subject = material()
    sub = bass_managed_sum(subject)
    shared = measure_unfiltered(sub, 1000, reference_samples=subject.mono_mix)
    for changed in (
        {"samples": sub.copy()},
        {"reference_samples": None},
        {"exclude_bands_hz": ((150.0, 160.0),)},
        {"diagnose_params": DiagnoseParams(reference_percentile=80.0)},
    ):
        kwargs = {"samples": sub, "reference_samples": subject.mono_mix} | changed
        with pytest.raises(ValueError, match="different signals"):
            verify([], fs=1000, band_hz=(5, 140), unfiltered=shared, **kwargs)


@pytest.mark.parametrize("tail", [False, True])
def test_a_cascades_transfer_built_once_filters_as_if_built_per_signal(tail):
    """`device_transfer` is `device_waveform`'s cascade half: sharing it changes no sample."""
    from beqforge.verify import device_transfer

    subject = material()
    device = Realisation(fs=48000)
    for filters in (
        [BiquadSpec("low_shelf", 20, 12, 0.707)],
        [BiquadSpec("low_shelf", 8, 9, 0.707), BiquadSpec("peaking_eq", 30, 6, 2.0)],
    ):
        shared = device_transfer(filters, len(subject.mono_mix), 1000, device)
        for samples in (subject.mono_mix, *subject.channels.values()):
            np.testing.assert_array_equal(
                device_waveform(filters, samples, 1000, device, include_tail=tail),
                device_waveform(
                    filters, samples, 1000, device, include_tail=tail, transfer=shared
                ),
            )


def test_a_transfer_built_for_something_else_is_refused():
    from beqforge.verify import device_transfer

    subject = material()
    n = len(subject.mono_mix)
    filters = [BiquadSpec("low_shelf", 20, 12, 0.707)]
    device = Realisation(fs=48000)
    shared = device_transfer(filters, n, 1000, device)
    for samples, fs, realisation in (
        (subject.mono_mix[:-1], 1000, device),
        (subject.mono_mix, 500, device),
        (subject.mono_mix, 1000, Realisation(fs=96000)),
    ):
        with pytest.raises(ValueError, match="another signal length"):
            device_waveform(filters, samples, fs, realisation, transfer=shared)
    # an empty cascade has no transfer and passes the signal through, as it did
    assert device_transfer([], n, 1000, device) is None
    np.testing.assert_array_equal(
        device_waveform([], subject.mono_mix, 1000, device), subject.mono_mix
    )
    with pytest.raises(ValueError, match="device rate must cover"):
        device_transfer(filters, n, 1000, Realisation(fs=500))
    fragile = [
        BiquadSpec(
            "low_shelf", 6.137080501313293, 20.453528341353397, 1.7655313695442572
        )
    ]
    with pytest.raises(ValueError, match="unstable"):
        device_transfer(fragile, n, 1000, Realisation())


def test_record_curves_build_each_cascades_transfer_once_for_all_its_signals(
    monkeypatch,
):
    """`curves_from` filters every charted signal through one transfer a candidate."""
    from beqforge import verify
    from beqforge.charts import programme_levels_db

    subject = material()
    cascades = {
        "a": [BiquadSpec("low_shelf", 20, 12, 0.707)],
        "none": [],
        "b": [BiquadSpec("peaking_eq", 30, 6, 2.0)],
    }
    built = []
    real = verify.device_transfer

    def counted(filters, *args, **kwargs):
        built.append(len(filters))  # an empty cascade has no transfer to share
        return real(filters, *args, **kwargs)

    monkeypatch.setattr(verify, "device_transfer", counted)
    curves = record.curves_from(subject, cascades, ["L", "LFE"], Realisation())
    assert sum(1 for n in built if n) == 2
    monkeypatch.undo()
    signals = {"mono": subject.mono_mix, **subject.channels}
    for label, specs in cascades.items():
        for name, samples in signals.items():
            levels = programme_levels_db(
                device_waveform(specs, samples, 1000.0, Realisation()),
                1000.0,
                frame_index=curves["unfiltered"][name]["loudest_index"],
            )
            got = curves["filtered"][label][name]
            for key in ("peak", "average", "loudest_second"):
                assert got[key] == record._arr(getattr(levels, key)), (
                    label,
                    name,
                )
