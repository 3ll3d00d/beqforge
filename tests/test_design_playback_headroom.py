"""R11: clipping outputs carry the playback assumptions they actually measured."""

from dataclasses import replace, asdict
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import signal

from beqforge import BiquadSpec, DESIGN_GRID, pipeline, record
from beqforge.filters import Realisation, biquad_sos, magnitude_db
from beqforge.material import Material, PlaybackParams, bass_managed_sum
from tests.test_design_device_rate import programme, reference
from tools.design_beq import _headroom
from tools.render_ledger import title_entry

FILTERS = [BiquadSpec("low_shelf", 100, 20, 0.707)]


def subject():
    main = programme() * 8
    lfe = np.roll(main, 3) * 0.8
    return Material(
        "headroom-model",
        1000,
        main + lfe,
        {"L": main, "LFE": lfe},
        "complete_programme",
    )


def independent_sub(material, model):
    def lp(values, corner):
        sos = signal.butter(2, corner, fs=1000, btype="low", output="sos")
        return signal.sosfilt(np.concatenate([sos, sos]), values)

    output = lp(material.channels["L"], model.crossover_hz) * 10 ** (
        model.main_gain_db / 20
    )
    output += material.channels["LFE"] * 10 ** (model.lfe_gain_db / 20)
    corner = (
        model.crossover_hz
        if model.sub_lowpass_hz == "crossover"
        else model.sub_lowpass_hz
    )
    if corner is not None:
        output = lp(output, corner)
    return output * 10 ** (model.sub_gain_db / 20)


@pytest.mark.parametrize(
    "model",
    [
        PlaybackParams(),
        PlaybackParams(crossover_hz=120),
        PlaybackParams(main_gain_db=-6),
        PlaybackParams(lfe_gain_db=-2),
        PlaybackParams(sub_gain_db=6),
        PlaybackParams(sub_lowpass_hz=None),
        PlaybackParams(sub_lowpass_hz=140),
    ],
)
@pytest.mark.parametrize(
    "device", [Realisation(fs=48000), Realisation(fs=96000, coefficient_bits=24)]
)
def test_clipping_agrees_with_independent_waveform_for_each_assumption(model, device):
    material = subject()
    sub = independent_sub(material, model)
    np.testing.assert_array_equal(sub, bass_managed_sum(material, playback=model))
    expected = reference(FILTERS, sub, device, tail=1000)
    result = pipeline.measure_headroom(
        material, FILTERS, pipeline.PipelineParams(playback=model, realisation=device)
    )
    offset = min(-20 * np.log10(np.max(np.abs(expected))), 0)
    assert result.offset_db == pytest.approx(offset, abs=0.05)
    assert 20 * np.log10(result.peak / np.max(np.abs(expected))) == pytest.approx(
        0, abs=0.05
    )
    assert result.playback == model
    assert result.realisation == device
    assert result.unavailable_reason is None
    assert "assumed sub-feed model" in result.summary()
    assert "unity full scale" in result.assumptions()
    assert f"{device.fs:g} Hz" in result.assumptions()


def test_output_gain_changes_clipping_cost_but_not_peak_filter_gain(monkeypatch):
    material = subject()
    low = pipeline.measure_headroom(material, FILTERS, pipeline.PipelineParams())
    high = pipeline.measure_headroom(
        material,
        FILTERS,
        pipeline.PipelineParams(playback=PlaybackParams(sub_gain_db=6)),
    )
    assert low.offset_db < 0
    assert high.offset_db == pytest.approx(low.offset_db - 6, abs=1e-10)
    from tests.test_design_playback import material as broadband
    from beqforge.diagnose import Diagnosis

    monkeypatch.setattr(pipeline, "judged_band_hz", lambda *args: (5, 200))
    candidate = pipeline._judge(
        "peak",
        FILTERS,
        None,
        0,
        broadband(),
        Diagnosis(DESIGN_GRID, np.zeros_like(DESIGN_GRID), {}),
        pipeline.PipelineParams(),
    )
    assert (
        replace(candidate, headroom=low).peak_gain_db
        == replace(candidate, headroom=high).peak_gain_db
    )
    device = low.realisation
    expected = magnitude_db(
        device.quantise(biquad_sos(FILTERS, device.fs)), DESIGN_GRID, device.fs
    ).max()
    assert candidate.peak_gain_db == pytest.approx(expected)
    assert (
        candidate.mv_adjust_db == candidate.peak_gain_db
    )  # legacy alias is only filter gain


def test_missing_unstable_and_nonfinite_measurements_report_the_actual_reason():
    material = subject()
    params = pipeline.PipelineParams()
    missing = pipeline.measure_headroom(replace(material, channels={}), FILTERS, params)
    assert np.isnan(missing.offset_db)
    assert missing.peak is None
    assert "no channel decomposition" in _headroom(missing.offset_db, missing)
    fragile = [
        BiquadSpec(
            "low_shelf", 6.137080501313293, 20.453528341353397, 1.7655313695442572
        )
    ]
    unstable = pipeline.measure_headroom(material, fragile, params)
    assert np.isnan(unstable.offset_db)
    assert "unstable" in _headroom(unstable.offset_db, unstable)
    bad = pipeline.measure_headroom(
        material, FILTERS, params, sub_samples=np.full(1000, np.nan)
    )
    assert np.isnan(bad.offset_db)
    assert "non-finite" in bad.unavailable_reason


def test_zero_cost_is_qualified_in_cli_and_legacy_output():
    material = subject()
    silence = replace(material, channels={"LFE": np.zeros_like(material.mono_mix)})
    result = pipeline.measure_headroom(silence, FILTERS, pipeline.PipelineParams())
    assert result.offset_db == 0
    assert "assumed sub-feed model" in _headroom(0, result)
    assert "model unspecified" in _headroom(0)


def test_record_and_ledger_preserve_assumptions_without_upgrading_legacy(
    monkeypatch, tmp_path
):
    from tests.test_design_playback import material
    from beqforge.diagnose import Diagnosis

    model = PlaybackParams(crossover_hz=120, sub_lowpass_hz=None, sub_gain_db=6)
    params = pipeline.PipelineParams(playback=model, realisation=Realisation(fs=48000))
    monkeypatch.setattr(pipeline, "judged_band_hz", lambda *args: (5, 200))
    candidate = pipeline._judge(
        "recorded",
        FILTERS,
        None,
        0,
        material(),
        Diagnosis(DESIGN_GRID, np.zeros_like(DESIGN_GRID), {}),
        params,
    )
    payload = record._candidate(candidate)
    measurement = payload["headroom"]
    assert measurement["playback"] == asdict(model)
    assert measurement["realisation"]["fs"] == 48000
    assert measurement["full_scale"] == 1
    assert measurement["peak"] == candidate.headroom.peak
    assert measurement["offset_db"] == candidate.verdict.required_offset_db
    document = {
        "material": {"name": "demo", "duration_s": 1},
        "fingerprint": {"material_path": "demo.npz"},
        "candidates": [payload],
        "accepted": None,
    }
    entry = title_entry(document)
    assert entry["headroom_summary"] == measurement["summary"]
    assert entry["headroom_assumptions"] == measurement["assumptions"]
    del payload["headroom"]
    legacy = title_entry(document)
    assert "model unspecified" in legacy["headroom_summary"]
    assert "headroom" not in payload


def test_cli_forwards_playback_and_device_settings(monkeypatch):
    from tools import design_beq

    seen = []
    material = subject()
    monkeypatch.setattr(design_beq, "load", lambda _: material)

    def run(material, params, **kwargs):
        seen.append(params)
        return SimpleNamespace(
            diagnosis=SimpleNamespace(channels={}), candidates=[], accepted=None
        )

    monkeypatch.setattr(design_beq, "run", run)
    for name in (
        "show_channels",
        "show_floors",
        "show_identification",
        "show_candidates",
        "show_result",
        "show_cost",
    ):
        monkeypatch.setattr(design_beq, name, lambda *args: None)
    monkeypatch.setattr(
        "sys.argv",
        [
            "design_beq",
            "unused.npz",
            "--no-record",
            "--no-cache",
            "--crossover",
            "120",
            "--sub-lowpass",
            "off",
            "--main-gain-db",
            "-6",
            "--lfe-gain-db",
            "-2",
            "--sub-gain-db",
            "4",
            "--device-rate",
            "48000",
            "--coefficient-bits",
            "24",
            "--integer-bits",
            "5",
        ],
    )
    assert design_beq.main() == 1
    assert seen[0].playback == PlaybackParams(
        crossover_hz=120,
        sub_lowpass_hz=None,
        main_gain_db=-6,
        lfe_gain_db=-2,
        sub_gain_db=4,
    )
    assert seen[0].realisation == Realisation(fs=48000, coefficient_bits=24)
