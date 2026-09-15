"""R9: effective settings, cache identity and parametric correction intent."""

from dataclasses import replace
import importlib

import numpy as np
import pytest

from beqanalyser.design import DESIGN_GRID, BiquadSpec
from beqanalyser.design import cache, pipeline, record
from beqanalyser.design.accept import assess
from beqanalyser.design.diagnose import Diagnosis
from beqanalyser.design.filters import Realisation
from beqanalyser.design.material import Material
from beqanalyser.design.verify import Correction
from tests.test_design_design import identified_rolloff, envelopes_with_margin

D = importlib.import_module("beqanalyser.design.design")


def inputs():
    samples = np.random.default_rng(43).normal(scale=0.01, size=10000)
    material = Material("r9", 1000, samples, {"L": samples}, "complete_programme")
    diagnosis = Diagnosis(DESIGN_GRID, np.zeros_like(DESIGN_GRID), {})
    envelopes = replace(
        envelopes_with_margin(6.0), margin_se_db=np.ones_like(DESIGN_GRID)
    )
    return material, diagnosis, envelopes, identified_rolloff()


def test_nondefault_shared_settings_reach_both_fit_paths(monkeypatch):
    params = pipeline.PipelineParams(
        max_sections=2,
        residual_target_db=0.8,
        residual_band_hz=(6.0, 250.0),
        max_gain_db=15.0,
        confidence_z=2.5,
        lowest_frequency_hz=7.0,
        fit_seeds=(4, 8),
        realisation=Realisation(fs=48000),
        parametric_max_boost_db=12.0,
        accept=replace(pipeline.PipelineParams().accept, max_drift_db=4.5),
    )
    calls = []

    def fit(target, grid, fs, budget, tolerance, **kwargs):
        calls.append((target.copy(), budget, tolerance, kwargs))
        return [BiquadSpec("low_shelf", 20.0, 3.0, 0.707)], 0.1

    monkeypatch.setattr(D, "fit_minimal_biquads", fit)
    (proposal,) = pipeline.parametric_targets(*inputs(), params)
    effective = pipeline.STRATEGIES["parametric"].effective_params(params)
    assert effective.max_boost_db == 12.0
    assert effective.confidence_z == 2.5
    assert effective.lowest_frequency_hz == 7.0
    assert effective.section_gain_db == 15.0
    np.testing.assert_array_equal(proposal.target_db, calls[0][0])
    assert proposal.target_db.max() == pytest.approx(3.5)
    assert proposal.unpriced_target_db.max() > proposal.target_db.max()
    assert proposal.method == "fitted"
    assert proposal.notes
    assert proposal.effective_params == repr(effective)

    def fit_all(requests, grid, fs, budget, tolerance, **kwargs):
        return [
            fit(r.target_db, grid, fs, budget, tolerance, **kwargs) for r in requests
        ]

    monkeypatch.setattr(pipeline, "fit_minimal_biquads_all", fit_all)
    pipeline._fit_all([replace(proposal, filters=None)], params)
    for _, budget, tolerance, kwargs in calls:
        assert budget == 2
        assert tolerance == 0.8
        assert kwargs["band_hz"] == (6.0, 250.0)
        assert kwargs["max_gain_db"] == 15.0
        assert kwargs["realisation"] == params.realisation
        assert kwargs["seeds"] == (4, 8)
        assert kwargs["max_drift_db"] == 4.5
    assert calls[0][3]["placement_band_hz"][0] >= 7.0


@pytest.mark.parametrize(
    "changed",
    [
        {"fit_seeds": (7,)},
        {"confidence_z": 2.0},
        {"lowest_frequency_hz": 8.0},
        {"residual_target_db": 0.9},
        {"residual_band_hz": (6.0, 180.0)},
        {"max_gain_db": 18.0},
        {"parametric_max_boost_db": 10.0},
        {"max_sections": 2},
        {"realisation": Realisation(fs=48000)},
        {"accept": replace(pipeline.PipelineParams().accept, max_drift_db=4.5)},
    ],
)
def test_consumed_settings_change_the_strategy_key(changed):
    params = pipeline.PipelineParams()
    strategy = pipeline.STRATEGIES["parametric"]
    material = inputs()[0]
    first = cache.key_for(
        "parametric",
        strategy.cache_modules,
        material,
        strategy.effective_params(params),
    )
    second = cache.key_for(
        "parametric",
        strategy.cache_modules,
        material,
        strategy.effective_params(replace(params, **changed)),
    )
    assert first != second


def test_cached_run_matches_fresh_and_seed_change_reuses_analysis(
    tmp_path, monkeypatch
):
    material, diagnosis, envelopes, identification = inputs()
    counts = dict(diagnose=0, extract=0, identify=0, design=0)

    def measured(name, value):
        def call(*args):
            counts[name] += 1
            return value

        return call

    monkeypatch.setattr(pipeline, "diagnose", measured("diagnose", diagnosis))
    monkeypatch.setattr(pipeline, "extract", measured("extract", envelopes))
    monkeypatch.setattr(
        pipeline, "identify_rolloff", measured("identify", identification)
    )
    real_design = pipeline.design

    def design(*args, **kwargs):
        counts["design"] += 1
        return real_design(*args, **kwargs)

    monkeypatch.setattr(pipeline, "design", design)
    params = pipeline.PipelineParams(
        strategies=("parametric",), max_sections=1, confidence_z=2.0, fit_seeds=(3,)
    )
    path = tmp_path / "stages.json.gz"
    first = pipeline.run(material, params, cache_path=path)
    hit = pipeline.run(material, params, cache_path=path)
    assert counts == dict(diagnose=1, extract=1, identify=1, design=1)
    assert len(first.candidates) == len(hit.candidates) == 1
    # This compares actual published filters, targets, verdicts and method/settings metadata.
    assert record._candidate(first.candidates[0]) == record._candidate(
        hit.candidates[0]
    )
    np.testing.assert_array_equal(
        first.candidates[0].target_db, hit.candidates[0].target_db
    )
    np.testing.assert_array_equal(
        first.candidates[0].unpriced_target_db, hit.candidates[0].unpriced_target_db
    )
    assert hit.candidates[0].method == "fitted"
    assert hit.candidates[0].target_notes
    changed = replace(params, fit_seeds=(8,))
    moved = pipeline.run(material, changed, cache_path=path)
    assert counts == dict(diagnose=1, extract=1, identify=1, design=2)
    fresh = pipeline.run(material, changed, cache_path=path, fresh=True)
    assert counts == dict(diagnose=2, extract=2, identify=2, design=3)
    assert record._candidate(moved.candidates[0]) == record._candidate(
        fresh.candidates[0]
    )


def test_partial_parametric_intent_is_judged_without_weakening_wrong_filter_checks(
    monkeypatch,
):
    material, diagnosis, envelopes, identification = inputs()
    params = pipeline.PipelineParams(max_sections=1)
    (proposal,) = pipeline.parametric_targets(
        material, diagnosis, envelopes, identification, params
    )
    # Exact achievement of a limited target still leaves an unrecovered 10 dB deficit.
    before = -proposal.target_db - 10.0
    correction = Correction(
        DESIGN_GRID, before, before + proposal.target_db, (5.0, 45.0)
    )
    seen = []

    def verify(*args, **kwargs):
        seen.append(kwargs["priced_target_db"])
        return correction

    monkeypatch.setattr(pipeline, "verify", verify)
    monkeypatch.setattr(pipeline, "judged_band_hz", lambda *args: (5.0, 45.0))
    candidate = pipeline._judge(
        proposal.label,
        proposal.filters,
        proposal.target_db,
        proposal.residual_db,
        material,
        diagnosis,
        params,
        proposal.notes,
        proposal.unpriced_target_db,
        proposal.method,
        proposal.effective_params,
    )
    np.testing.assert_array_equal(seen[0], proposal.target_db)
    assert not any(
        "level" in f or "under-corrected" in f or "corrected only" in f
        for f in candidate.verdict.failures
    )
    without_intent = assess(
        candidate.filters, correction, float("nan"), params.accept, params.realisation
    )
    assert any("level" in f for f in without_intent.failures)
    # An erroneous target cannot license overshoot by making the fit residual zero.
    wrong_target = proposal.target_db + 30.0
    wrong = replace(correction, after_db=before + wrong_target)
    verdict = assess(
        candidate.filters,
        wrong,
        float("nan"),
        params.accept,
        params.realisation,
        target_db=wrong_target,
    )
    assert not verdict.passed
    assert any("above anything the material" in f for f in verdict.failures)


@pytest.mark.parametrize("aligned", [True, False])
def test_design_retains_the_actual_target_on_each_route(aligned):
    found = identified_rolloff()
    if not aligned:
        found = replace(found, rolloff=None)
    result = D.design(
        found, envelopes_with_margin(40.0), D.DesignParams(max_sections=2)
    )
    assert result.method == ("exact" if aligned else "fitted")
    assert result.target_db is not None
    assert result.unpriced_target_db is not None
    np.testing.assert_array_equal(result.target_db, result.unpriced_target_db)
    assert not result.noise_ceiling_binds


def test_closed_form_respects_the_effective_section_budget(monkeypatch):
    calls = []

    def fit(target, grid, fs, budget, *args, **kwargs):
        calls.append(budget)
        return [BiquadSpec("low_shelf", 20.0, 10.0, 0.707)], 0.1

    monkeypatch.setattr(D, "fit_minimal_biquads", fit)
    result = D.design(
        identified_rolloff(),
        envelopes_with_margin(40.0),
        D.DesignParams(max_sections=1),
    )
    assert calls == [1]
    assert result.method == "fitted"
    assert len(result.filters) == 1
