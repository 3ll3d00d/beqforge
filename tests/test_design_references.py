"""R8: a reference is one broad, flat region shared by construction and judging."""

import numpy as np
import pytest

from beqanalyser.design.diagnose import DiagnoseParams, plateau_reference


def test_disjoint_plateaus_do_not_bridge_valley():
    freqs = np.geomspace(4, 200, 4000)
    curve = np.full_like(freqs, -30)
    curve[((freqs >= 10) & (freqs <= 20)) | ((freqs >= 80) & (freqs <= 110))] = 0
    level, (low, high) = plateau_reference(curve, freqs, DiagnoseParams())
    assert level == 0
    assert 10 <= low < high <= 20


def test_narrow_authored_peak_does_not_replace_broad_plateau():
    freqs = np.geomspace(4, 200, 4000)
    curve = np.full_like(freqs, -30)
    curve[(freqs >= 30) & (freqs <= 100)] = 0
    curve[(freqs >= 15) & (freqs <= 15.5)] = 20
    level, (low, high) = plateau_reference(curve, freqs, DiagnoseParams())
    assert level == 0
    assert 30 <= low < high <= 100


@pytest.mark.parametrize(
    "curve", [lambda f: 12 * np.log2(f), lambda f: np.full_like(f, np.nan)]
)
def test_no_usable_plateau_is_explicit(curve):
    freqs = np.geomspace(4, 200, 4000)
    level, region = plateau_reference(curve(freqs), freqs, DiagnoseParams())
    assert np.isnan(level)
    assert np.isnan(region).all()


def test_reference_level_is_median_of_selected_log_region():
    freqs = np.geomspace(4, 200, 400)
    curve = np.where((freqs >= 20) & (freqs <= 80), np.log2(freqs / 20), -30)
    level, (low, high) = plateau_reference(curve, freqs, DiagnoseParams())
    assert level == pytest.approx(np.median(curve[(freqs >= low) & (freqs <= high)]))


def test_construction_and_verification_share_reference(monkeypatch):
    import importlib
    from beqanalyser.design import pipeline
    from beqanalyser.design.material import Material

    verification = importlib.import_module("beqanalyser.design.verify")
    freqs = np.linspace(0.25, 500, 2000)
    curve = np.where(freqs < 30, -12.0, 0.0)
    curve[freqs > 120] = -20.0
    monkeypatch.setattr(pipeline, "mean_spectrum", lambda *args: (freqs, curve))
    monkeypatch.setattr(verification, "_mean_db", lambda *args: (freqs, curve))
    monkeypatch.setattr(
        pipeline, "priced_by_evidence", lambda target, *args: (target, [])
    )
    material = Material("reference", 1000, np.ones(5000), {}, "complete_programme")
    from beqanalyser.design.diagnose import Diagnosis

    diagnosis = Diagnosis(freqs, curve, {})
    proposals = pipeline.flatten_targets(
        material, diagnosis, None, None, pipeline.PipelineParams()
    )
    from beqanalyser.design import BiquadSpec

    correction = verification.verify(
        [BiquadSpec("low_shelf", 30, 0, 0.707)], material.mono_mix, 1000
    )
    assert np.interp(10, pipeline.DESIGN_GRID, proposals[0].target_db) == pytest.approx(
        12
    )
    assert np.interp(10, correction.freqs, correction.before_db) == pytest.approx(-12)
