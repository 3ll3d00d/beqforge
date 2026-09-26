"""R1: missing measurements cannot become correction permission."""

from dataclasses import replace

import numpy as np
import pytest
from scipy import signal

from beqforge import BiquadSpec, DESIGN_GRID
from beqforge.accept import confidence_from_evidence
from beqforge.design import DesignParams, _noise_ceiling, design
from beqforge.diagnose import Diagnosis
from beqforge.extraction import ExtractionParams, _block_bootstrap_se, extract
from beqforge.filters import biquad_sos
from beqforge.material import Material
from beqforge.pipeline import PipelineParams, priced_by_evidence, run
from tests.test_design_design import envelopes_with_margin, identified_rolloff


def test_stationary_noise_abstains_and_records_why(tmp_path):
    from beqforge import record

    samples = (
        signal.sosfilt(
            biquad_sos([BiquadSpec("low_shelf", 30.0, -12.0, 0.707)], 1000.0),
            np.random.default_rng(127).standard_normal(300_000),
        )
        * 0.01
    )
    material = Material("stationary", 1000, samples, {}, "excerpt")
    params = PipelineParams(strategies=("flatten",), max_sections=2)
    report = run(material, params)
    assert report.accepted is None
    assert not report.candidates
    assert any("no qualifying loud" in n for n in report.evidence_notes)
    assert any("excerpt" in n for n in report.evidence_notes)
    source = tmp_path / "material.npz"
    np.savez(source, mono_mix=samples)
    path = record.write(tmp_path / "run.json.gz", report, params, source)
    assert record.read(path)["evidence_notes"] == list(report.evidence_notes)


@pytest.mark.parametrize("missing", ["se", "envelopes", "omitted"])
@pytest.mark.parametrize("floor", [float("nan"), 20.0])
def test_removing_measurements_never_expands_allowance(missing, floor):
    env = envelopes_with_margin(12.0)
    mask = DESIGN_GRID < 15
    if missing == "se":
        less = replace(env, margin_se_db=np.where(mask, np.inf, 0.0))
    elif missing == "envelopes":
        less = replace(env, peak_db=np.where(mask, np.nan, env.peak_db))
    else:
        less = replace(env, confidence_computed=~mask)
    diagnosis = Diagnosis(
        DESIGN_GRID, np.zeros_like(DESIGN_GRID), {}, noise_floor_hz=floor
    )
    target = np.full_like(DESIGN_GRID, 20.0)
    before, _ = priced_by_evidence(target, env, diagnosis, PipelineParams())
    after, notes = priced_by_evidence(target, less, diagnosis, PipelineParams())
    assert np.all(after <= before)
    assert np.all(after[mask] == 0)
    assert notes
    _, ceiling = _noise_ceiling(less, identified_rolloff().fit, DesignParams())
    assert np.all(ceiling[mask] == 0)


def test_failed_and_unavailable_and_omitted_are_distinct():
    env = envelopes_with_margin(12.0)
    peak = env.peak_db.copy()
    peak[:2] = [0.0, np.nan]
    computed = np.ones(DESIGN_GRID.size, dtype=bool)
    computed[2] = False
    env = replace(env, peak_db=peak, confidence_computed=computed)
    assert list(env.evidence_states(1.645)[:4]) == [
        "failure",
        "unavailable",
        "omitted",
        "support",
    ]


@pytest.mark.parametrize(
    "n_boot, mask", [(10, [True, True, False, False]), (1, [True, False, True, False])]
)
def test_insufficient_bootstrap_runs_or_replicates_are_unavailable(n_boot, mask):
    se = _block_bootstrap_se(
        np.ones((1, 4)),
        np.array([0]),
        np.array(mask),
        95,
        n_boot,
        np.random.default_rng(1),
    )
    assert np.isinf(se).all()


def test_parametric_declines_without_evidence():
    env = envelopes_with_margin(12.0)
    env = replace(env, margin_se_db=np.full_like(DESIGN_GRID, np.inf))
    result = design(identified_rolloff(), env)
    assert not result.filters
    assert result.decline_reason == "evidence_unavailable"


def test_unknown_confidence_inputs_cannot_improve_score():
    score = confidence_from_evidence(0.7, 0.3)
    assert score > 0
    for recovered, shaping in [(np.nan, 0.3), (0.7, np.nan), (np.nan, np.nan)]:
        assert confidence_from_evidence(recovered, shaping) == 0


def test_profiling_omissions_are_preserved_in_cache():
    from beqforge.cache import Analysis, analysis_from_json, analysis_to_json

    samples = np.random.default_rng(1).normal(size=20_000)
    env = extract(samples, 1000, ExtractionParams(confidence_bins=2))
    diagnosis = Diagnosis(DESIGN_GRID, np.zeros_like(DESIGN_GRID), {})
    loaded = analysis_from_json(
        analysis_to_json(Analysis(diagnosis, env, None))
    ).envelopes
    assert np.all(loaded.evidence_states(1.645)[2:] == "omitted")
    assert np.all(loaded.boost_ceiling(1.645)[2:] == 0)


@pytest.mark.parametrize(
    "coverage, channels, reason",
    [
        ("excerpt", {"L": np.ones(1000)}, "excerpt"),
        ("complete_programme", {}, "channel evidence unavailable"),
    ],
)
def test_coverage_and_channel_policies_apply_even_with_measured_mix_support(
    monkeypatch, coverage, channels, reason
):
    from beqforge import pipeline

    env = envelopes_with_margin(12.0)
    monkeypatch.setattr(pipeline, "extract", lambda *args: env)
    monkeypatch.setattr(
        pipeline,
        "diagnose",
        lambda *args: Diagnosis(DESIGN_GRID, np.zeros_like(DESIGN_GRID), {}),
    )
    monkeypatch.setattr(
        pipeline, "identify_rolloff", lambda *args: identified_rolloff()
    )
    material = Material("policy", 1000, np.ones(1000), channels, coverage)
    report = run(material)
    assert report.accepted is None
    assert any(reason in note for note in report.evidence_notes)


def test_every_target_is_held_below_the_floor_and_capped_at_the_deficit():
    """IMPROVEMENT_PLAN E3: one evidence rule for every strategy, not only `flatten`.

    A model inversion that keeps climbing below the tracking floor used to reach the fitter
    unheld: on 28 Years Later the parametric and counterfactual targets asked for 16.4 and
    15.5 dB below the floor where `flatten` asked 6.4, and the parametric cascade won at
    +18.7 dB. On Send Help a parametric target reached 1.54 times the measured deficit.
    """
    env = envelopes_with_margin(40.0)  # contrast licenses far more than either rule allows
    diagnosis = Diagnosis(
        DESIGN_GRID, np.zeros_like(DESIGN_GRID), {}, noise_floor_hz=20.0
    )
    climbing = np.clip(30.0 - 10.0 * np.log2(DESIGN_GRID / 5.0), 0.0, None)
    at_floor = float(np.interp(20.0, DESIGN_GRID, climbing))

    held, notes = priced_by_evidence(climbing, env, diagnosis, PipelineParams())
    below = DESIGN_GRID < 20.0
    assert np.allclose(held[below], at_floor)
    assert any("noise floor binds" in n for n in notes)

    deficit = np.full_like(DESIGN_GRID, 8.0)
    capped, notes = priced_by_evidence(
        climbing, env, diagnosis, PipelineParams(), deficit
    )
    assert capped.max() <= 8.0 + 1e-9
    assert any("deficit cap binds" in n for n in notes)


def test_every_strategy_prices_with_the_measured_deficit(monkeypatch):
    """The cap only works if every caller hands it over — `flatten` is capped by
    construction, so it is the other two that must not forget."""
    import types

    from beqforge import pipeline
    from beqforge.diagnose import diagnose
    from tests.test_design_diagnose import FS, high_passed, material_from
    from tests.test_design_pipeline import scened_noise

    samples = int(FS * 300.0)
    material = material_from(
        {
            "L": scened_noise(20, samples),
            "LFE": high_passed(scened_noise(22, samples), 22.0, order=6),
        }
    )
    diagnosis = diagnose(material)
    envelopes = extract(material.mono_mix, float(material.fs))
    params = PipelineParams()
    handed: list = []
    real = pipeline.priced_by_evidence

    def recording(target, envelopes, diagnosis, params, deficit_db=None):
        handed.append(deficit_db)
        return real(target, envelopes, diagnosis, params, deficit_db)

    monkeypatch.setattr(pipeline, "priced_by_evidence", recording)

    assert diagnosis.filtered_channels, "the high-passed LFE should read as filtered"
    pipeline.counterfactual_targets(material, diagnosis, envelopes, None, params)
    assert handed and all(d is not None for d in handed), "counterfactual"

    handed.clear()

    def fake_design(identification, envelopes, params, price_target):
        price_target(np.full_like(DESIGN_GRID, 5.0))
        return types.SimpleNamespace(filters=[], decline_reason="test")

    monkeypatch.setattr(pipeline, "design", fake_design)
    detected = types.SimpleNamespace(detected=True)
    pipeline.parametric_targets(material, diagnosis, envelopes, detected, params)
    assert handed and handed[0] is not None, "parametric"
