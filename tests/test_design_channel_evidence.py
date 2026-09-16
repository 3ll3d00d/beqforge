"""R4/R5 contracts: coherent sums, channel-local support, and non-causal features."""

from dataclasses import replace

import numpy as np
import pytest
from scipy import signal

from beqforge import DESIGN_GRID
from beqforge.diagnose import (
    DiagnoseParams,
    coherent_shares,
    diagnose,
    mean_spectrum,
    plateau_reference,
    stratified_response,
    supported_mix_change,
)
from beqforge.pipeline import (
    PipelineParams,
    correction_evidence_score,
    counterfactual_target,
)
from tests.test_design_design import envelopes_with_margin
from tests.test_design_diagnose import material_from, scened_noise, high_passed


def test_coherent_cancellation_has_signed_contributions_and_uncertainty():
    source = scened_noise(231, 240000)
    material = material_from({"L": source, "R": -0.75 * source})
    shares, errors = coherent_shares(material)
    np.testing.assert_allclose(shares["L"], 4, atol=1e-12)
    np.testing.assert_allclose(shares["R"], -3, atol=1e-12)
    np.testing.assert_allclose(shares["L"] + shares["R"], 1, atol=1e-12)
    assert np.isfinite(errors["L"]).all()
    assert np.max(errors["L"]) < 1e-12


def test_contribution_switches_with_frequency():
    source = scened_noise(232, 240000)
    low = signal.sosfilt(signal.butter(6, 30, fs=1000, output="sos"), source)
    high = high_passed(source, 30, 6)
    material = material_from({"L": low, "R": high})
    shares, _ = coherent_shares(material)
    freqs, _ = mean_spectrum(source, 1000)
    assert np.median(shares["L"][(freqs > 5) & (freqs < 10)]) > 0.95
    assert np.median(shares["R"][(freqs > 80) & (freqs < 100)]) > 0.95


def test_mix_floor_is_measured_on_mix_not_walled_lfe():
    source = scened_noise(233, 240000)
    material = material_from({"L": source, "LFE": high_passed(source, 25, 10)})
    result = diagnose(material)
    params = DiagnoseParams()
    _, plateau = plateau_reference(result.mix_db, result.freqs, params)
    axis, strata = stratified_response(material.mono_mix, 1000, params, plateau)
    expected = np.interp(
        result.freqs, axis, np.ptp(np.vstack(list(strata.values())), axis=0)
    )
    np.testing.assert_allclose(result.level_spread_db, expected)
    # Full-range mains supply real power below the LFE wall, whatever old-band dominance.
    bottom = (result.freqs > 5) & (result.freqs < 8)
    assert np.median(result.channels["L"].share[bottom]) > 0.9
    assert np.median(result.channels["LFE"].share[bottom]) < 0.1


def test_noisy_restored_channel_cannot_borrow_clean_neighbours_allowance():
    source = scened_noise(234, 240000)
    material = material_from({"L": source, "LFE": high_passed(source, 25, 10) * 0.01})
    result = diagnose(material)
    walled = result.channels["LFE"]
    # Measured failure is local to the formerly quiet channel; clean mix support is irrelevant.
    failed = replace(
        walled,
        contrast_db=np.ones_like(result.freqs),
        contrast_se_db=np.ones_like(result.freqs) * 2,
        tracking=np.ones_like(result.freqs),
    )
    clean = replace(
        failed,
        contrast_db=np.ones_like(result.freqs) * 60,
        contrast_se_db=np.zeros_like(result.freqs),
    )
    other = replace(result.channels["L"], is_filtered=False)
    bad = replace(result, channels={"L": other, "LFE": failed})
    good = replace(result, channels={"L": other, "LFE": clean})
    assert np.max(counterfactual_target(material, bad, 40, PipelineParams())) == 0
    assert np.max(counterfactual_target(material, good, 40, PipelineParams())) > 0
    assert np.max(replace(clean, contrast_se_db=None).boost_allowance(1.645, 0.5)) == 0


def test_changed_mix_uncertainty_is_recomputed_and_missing_is_not_zero():
    source = scened_noise(235, 240000)
    _, gain = supported_mix_change(source, source * 2, 1000, 1.645)
    np.testing.assert_allclose(gain, 20 * np.log10(2), atol=1e-12)
    # Fewer than two temporal blocks: no supported change despite a large raw ratio.
    _, gain = supported_mix_change(source[:4096], source[:4096] * 10, 1000, 1.645)
    assert np.max(gain) == 0


def test_correction_score_does_not_penalise_partial_recovery():
    env = envelopes_with_margin(20)
    target = np.where(DESIGN_GRID < 40, 12.0, 0.0)
    score = correction_evidence_score(target, env, 1.645)
    assert score > 0
    assert correction_evidence_score(target / 2, env, 1.645) == pytest.approx(score)
    assert np.isnan(correction_evidence_score(target * 0, env, 1.645))
    assert (
        correction_evidence_score(target, replace(env, margin_se_db=None), 1.645) == 0
    )
    assert (
        correction_evidence_score(
            target, replace(env, margin_se_db=np.full_like(env.freqs, np.inf)), 1.645
        )
        == 0
    )


def test_spectral_gain_cancels_temporal_contrast():
    env = envelopes_with_margin(20)
    gain = np.linspace(0, 35, len(env.freqs))
    changed = replace(env, peak_db=env.peak_db + gain, quiet_db=env.quiet_db + gain)
    np.testing.assert_allclose(changed.margin_db, env.margin_db)


def test_level_invariance_cannot_distinguish_natural_colouring_from_mastering():
    source = scened_noise(236, 240000)
    # Same waveform, distinct provenance: no statistic of it can distinguish these causes.
    naturally_coloured = high_passed(source, 20, 6)
    injected = high_passed(source, 20, 6)
    _, natural = stratified_response(
        naturally_coloured, 1000, DiagnoseParams(), (40, 80)
    )
    _, mastering = stratified_response(injected, 1000, DiagnoseParams(), (40, 80))
    for key in natural:
        np.testing.assert_array_equal(natural[key], mastering[key])


def test_actual_noisy_channel_has_no_allowance_despite_clean_mix_events():
    from beqforge.harness import evidence_cases
    from beqforge.extraction import extract

    case = next(evidence_cases(101))
    rng = np.random.default_rng(237)
    material = material_from(
        {
            "L": case.content + case.noise,
            "LFE": 0.0001 * high_passed(case.content, 25, 10)
            + 0.00002 * rng.standard_normal(len(case.content)),
        }
    )
    result = diagnose(material)
    assert np.max(extract(material.mono_mix, 1000).boost_ceiling(1.645)) > 0
    assert np.max(result.channels["L"].boost_allowance(1.645, 0.5)) > 0
    assert np.max(result.channels["LFE"].boost_allowance(1.645, 0.5)) == 0
