"""R10: authored omissions cannot supply reference, evidence or a fictitious band."""

import importlib

import numpy as np
import pytest

from beqforge import BiquadSpec, DESIGN_GRID
from beqforge.diagnose import (
    DiagnoseParams,
    Diagnosis,
    plateau_reference,
    smooth_unexcluded,
    unexcluded,
)
from beqforge.material import Material
from beqforge import pipeline

BANDS = ((65.0, 75.0), (90.0, 95.0))


def spectrum(peak):
    freqs = np.arange(0.25, 500.25, 0.25)
    values = np.where(freqs < 30, -12.0, 0.0)
    values[freqs > 120] = -20.0
    values[~unexcluded(freqs, BANDS)] = peak
    return freqs, values


def test_multiple_exclusions_split_plateau_without_moving_level():
    results = []
    for peak in (0.0, 50.0):
        freqs, values = spectrum(peak)
        results.append(plateau_reference(values, freqs, DiagnoseParams(), BANDS))
    assert results[0] == results[1]
    level, (low, high) = results[0]
    assert level == 0
    assert 30 <= low < high < 65


def test_excluded_peak_cannot_move_flatten_target_judged_extent_or_verification(
    monkeypatch,
):
    verification = importlib.import_module("beqforge.verify")
    material = Material("omissions", 1000, np.ones(5000), {}, "complete_programme")
    params = pipeline.PipelineParams(exclude_bands_hz=BANDS)
    monkeypatch.setattr(
        pipeline, "priced_by_evidence", lambda target, *args: (target, [])
    )
    results = []
    for peak in (0.0, 60.0):
        freqs, values = spectrum(peak)
        monkeypatch.setattr(pipeline, "mean_spectrum", lambda *args: (freqs, values))
        monkeypatch.setattr(verification, "_mean_db", lambda *args: (freqs, values))
        diagnosis = Diagnosis(freqs, values, {})
        target = pipeline.flatten_targets(material, diagnosis, None, None, params)[
            0
        ].target_db
        band = pipeline.judged_band_hz(material, diagnosis, params)
        correction = verification.verify(
            [BiquadSpec("low_shelf", 30, 0, 0.707)],
            material.mono_mix,
            1000,
            band_hz=band,
            exclude_bands_hz=BANDS,
        )
        results.append((target, band, correction.before_db))
    np.testing.assert_array_equal(results[0][0], results[1][0])
    assert results[0][1] == results[1][1]
    np.testing.assert_array_equal(results[0][2], results[1][2])


def test_smoothing_does_not_bridge_excluded_intervals():
    freqs = np.arange(1.0, 21.0)
    values = np.where(freqs < 10, 10.0, 100.0)
    bands = ((10.0, 12.0),)
    actual = smooth_unexcluded(values, freqs, bands, 15)
    assert np.all(actual[~unexcluded(freqs, bands)] == 0)
    assert np.max(actual[freqs < 10]) <= 10
    changed = values.copy()
    changed[~unexcluded(freqs, bands)] = 1e9
    np.testing.assert_array_equal(actual, smooth_unexcluded(changed, freqs, bands, 15))


def test_no_reference_and_fragmented_judgement_are_explicit():
    freqs, values = spectrum(0)
    assert np.isnan(plateau_reference(values, freqs, DiagnoseParams(), ((4, 200),))[0])
    verification = importlib.import_module("beqforge.verify")
    with pytest.raises(ValueError, match="fragment"):
        verification.verify([], np.ones(5000), 1000, exclude_bands_hz=((12, 20),))


def test_excluded_power_cannot_choose_scenes_or_coherence(monkeypatch):
    extraction = importlib.import_module("beqforge.extraction")
    freqs = np.arange(5.0, 151.0)
    rng = np.random.default_rng(14)
    power = np.exp(rng.normal(size=(len(freqs), 100)))
    power[:, 40:60] *= 1e7
    params = extraction.ExtractionParams(
        exclude_bands_hz=BANDS, confidence_bootstraps=2
    )
    results = []
    for scale in (1.0, 1e10):
        changed = power.copy()
        changed[~unexcluded(freqs, BANDS)] *= scale
        monkeypatch.setattr(extraction, "_spectrogram", lambda *args: (freqs, changed))
        results.append(extraction.extract(np.ones(5000), 1000, params))
    a, b = results
    assert a.loud_frames == b.loud_frames
    assert a.quiet_frames == b.quiet_frames
    np.testing.assert_array_equal(a.coherence, b.coherence)
    np.testing.assert_array_equal(a.boost_ceiling(2), b.boost_ceiling(2))
    assert np.all(a.evidence_states(2)[~unexcluded(freqs, BANDS)] == "omitted")


def test_pipeline_abstains_on_fragmented_judged_band(monkeypatch):
    from tests.test_design_evidence import envelopes_with_margin

    freqs, values = spectrum(0)
    material = Material(
        "omissions", 1000, np.ones(5000), {"L": np.ones(5000)}, "complete_programme"
    )
    monkeypatch.setattr(pipeline, "mean_spectrum", lambda *args: (freqs, values))
    monkeypatch.setattr(
        pipeline, "diagnose", lambda *args: Diagnosis(freqs, values, {})
    )
    monkeypatch.setattr(pipeline, "extract", lambda *args: envelopes_with_margin(12))
    monkeypatch.setattr(pipeline, "identify_rolloff", lambda *args: None)
    report = pipeline.run(
        material, pipeline.PipelineParams(exclude_bands_hz=((12, 20),))
    )
    assert not report.candidates
    assert any("fragment" in note for note in report.evidence_notes)


def test_pricing_licenses_zero_in_exclusions():
    from tests.test_design_evidence import envelopes_with_margin

    params = pipeline.PipelineParams(exclude_bands_hz=BANDS)
    target, _ = pipeline.priced_by_evidence(
        np.ones_like(DESIGN_GRID) * 5,
        envelopes_with_margin(12),
        Diagnosis(DESIGN_GRID, np.zeros_like(DESIGN_GRID), {}),
        params,
    )
    assert np.all(target[~unexcluded(DESIGN_GRID, BANDS)] == 0)


def test_sub_bin_exclusion_still_splits_reference():
    freqs = np.geomspace(4, 200, 400)
    level, (low, high) = plateau_reference(
        np.zeros_like(freqs), freqs, DiagnoseParams(), ((50.001, 50.002),)
    )
    assert level == 0
    assert high < 50.001 or low > 50.002


def test_counterfactual_does_not_restore_an_excluded_feature():
    from dataclasses import replace
    from beqforge.diagnose import ChannelDiagnosis, mean_spectrum

    rng = np.random.default_rng(80)
    samples = rng.normal(size=10000)
    material = Material(
        "counterfactual", 1000, samples, {"L": samples}, "complete_programme"
    )
    freqs, mix = mean_spectrum(samples, 1000)
    response = np.where(freqs < 100, -12.0, 0.0)
    channel = ChannelDiagnosis(
        "L", response, np.ones_like(freqs), 30, 30, 1, True, (100, 120)
    )
    params = pipeline.PipelineParams(exclude_bands_hz=BANDS)
    targets = []
    for level in (-60, 60):
        changed = response.copy()
        changed[~unexcluded(freqs, BANDS)] = level
        diagnosis = Diagnosis(freqs, mix, {"L": replace(channel, response_db=changed)})
        targets.append(pipeline.counterfactual_target(material, diagnosis, 20, params))
    np.testing.assert_array_equal(*targets)
    assert np.all(targets[0][~unexcluded(DESIGN_GRID, BANDS)] == 0)


def test_effective_exclusions_reach_cached_analysis(tmp_path, monkeypatch):
    from tests.test_design_evidence import envelopes_with_margin

    seen = []
    freqs, values = spectrum(0)
    material = Material(
        "cache", 1000, np.ones(5000), {"L": np.ones(5000)}, "complete_programme"
    )
    monkeypatch.setattr(pipeline, "mean_spectrum", lambda *args: (freqs, values))

    def diagnosis(material, params, extraction_params):
        assert extraction_params.exclude_bands_hz == params.exclude_bands_hz
        seen.append(params.exclude_bands_hz)
        return Diagnosis(freqs, values, {})

    monkeypatch.setattr(pipeline, "diagnose", diagnosis)
    monkeypatch.setattr(pipeline, "extract", lambda *args: envelopes_with_margin(12))
    monkeypatch.setattr(pipeline, "identify_rolloff", lambda *args: None)
    cache_path = tmp_path / "cache.gz"
    for bands in (((12.0, 20.0),), ((12.0, 20.0),), ((13.0, 21.0),)):
        pipeline.run(
            material,
            pipeline.PipelineParams(exclude_bands_hz=bands),
            cache_path=cache_path,
        )
    assert seen == [((12.0, 20.0),), ((13.0, 21.0),)]
