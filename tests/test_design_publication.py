"""Exact publication precision, distinct from hypothetical drift samples."""

from dataclasses import asdict
import gzip
import json

import numpy as np
import pytest

from beqanalyser.design import BiquadSpec, DESIGN_GRID
from beqanalyser.design.accept import assess
from beqanalyser.design.beqd import _section, export
from beqanalyser.design.filters import (
    Realisation,
    biquad_sos,
    magnitude_db,
    publication_filters,
    unstable_sections,
    _publishable,
    _Escalation,
    FitRequest,
)
from beqanalyser.design.verify import Correction, verify

FRAGILE = BiquadSpec(
    "low_shelf", 6.137080501313293, 20.453528341353397, 1.7655313695442572
)


def test_review_shelf_fails_after_actual_export_rounding():
    device = Realisation()
    original = device.quantise(biquad_sos([FRAGILE], device.fs))
    assert original[0, 3:].sum() == 2**-23
    encoded = _section(FRAGILE, device.fs)
    published = BiquadSpec("low_shelf", encoded["fc"], encoded["gain"], encoded["q"])
    assert published == BiquadSpec("low_shelf", 6.14, 20.454, 1.7655)
    assert device.quantise(biquad_sos([published], device.fs))[0, 3:].sum() == 0
    response = magnitude_db(original, DESIGN_GRID, device.fs)
    correction = Correction(
        freqs=DESIGN_GRID,
        before_db=-response,
        after_db=np.zeros_like(response),
        band_hz=(5.0, 45.0),
    )
    verdict = assess([FRAGILE], correction, float("nan"), target_db=response)
    assert not verdict.passed
    assert any("not stable" in f for f in verdict.failures)
    assert not _publishable([FRAGILE], 0.0, DESIGN_GRID, device, None)


def test_verify_uses_export_parameters():
    specs = [BiquadSpec("low_shelf", 25.1378, 10.34567, 0.707123)]
    samples = np.random.default_rng(31).normal(size=20000)
    actual = verify(specs, samples, 1000)
    expected = verify(publication_filters(specs), samples, 1000)
    np.testing.assert_array_equal(actual.after_db, expected.after_db)


@pytest.mark.parametrize(
    "device", [Realisation(), Realisation(fs=48000, coefficient_bits=32)]
)
def test_export_round_trip_checks_declared_device(tmp_path, device):
    specs = publication_filters([BiquadSpec("low_shelf", 25.1378, 10.34567, 0.707123)])
    candidate = {
        "label": "test",
        "filters": [asdict(s) for s in specs],
        "verdict": {"passed": True, "failures": [], "notes": []},
        "target_notes": [],
        "mv_adjust_db": 0.0,
    }
    record = {
        "material": {"name": "test", "fs": 1000},
        "accepted": "test",
        "publication": {"realisation": asdict(device)},
        "curves": {
            "freqs": [10.0, 20.0],
            "unfiltered": {"mono": {"average": [-30.0, -20.0], "peak": [-10.0, -5.0]}},
        },
        "candidates": [candidate],
    }
    path = export(tmp_path / "test.beq", record)
    with gzip.open(path) as handle:
        section = json.load(handle)[0]["filter"]["filters"][0]
    assert section["fs"] == device.fs
    decoded = BiquadSpec("low_shelf", section["fc"], section["gain"], section["q"])
    assert decoded == specs[0]
    assert not unstable_sections([decoded], device)
    candidate["filters"] = [asdict(FRAGILE)]
    record["publication"]["realisation"] = asdict(Realisation())
    with pytest.raises(ValueError, match="unstable at publication"):
        export(tmp_path / "bad.beq", record)
    assert not (tmp_path / "bad.beq").exists()


def test_fitter_fallback_keeps_failed_candidate_for_diagnosis():
    state = _Escalation(FitRequest(np.zeros_like(DESIGN_GRID)))
    state.screened = [([FRAGILE], 0.1, False)]
    state.finish()
    assert state.answer == ([FRAGILE], 0.1)
    assert unstable_sections(state.answer[0], Realisation())


def test_pipeline_records_the_parameters_it_judges(monkeypatch):
    from types import SimpleNamespace

    from beqanalyser.design import pipeline, record

    original = [BiquadSpec("low_shelf", 25.1378, 10.34567, 0.707123)]
    published = publication_filters(original)
    samples = np.random.default_rng(71).normal(size=20000)
    material = SimpleNamespace(mono_mix=samples, fs=1000)
    diagnosis = SimpleNamespace(
        noise_floor_hz=float("nan"), filter_floor_hz=float("nan")
    )
    monkeypatch.setattr(pipeline, "judged_band_hz", lambda *args: (5.0, 45.0))
    monkeypatch.setattr(pipeline, "required_gain_reduction_db", lambda *args: 0.0)
    candidate = pipeline._judge(
        "test", original, None, 0.1, material, diagnosis, pipeline.PipelineParams()
    )
    assert candidate.filters == published
    assert candidate.optimiser_filters == original
    expected = verify(published, samples, 1000, band_hz=(5.0, 45.0))
    np.testing.assert_array_equal(candidate.correction.after_db, expected.after_db)
    encoded = record._candidate(candidate)
    assert encoded["filters"] == [asdict(s) for s in published]
    assert encoded["optimiser_filters"] == [asdict(s) for s in original]
