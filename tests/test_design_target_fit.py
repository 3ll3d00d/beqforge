"""TODO 14: what the published cascade, as the device plays it, delivers against its target."""

import math

import numpy as np
import pytest

from beqforge import DESIGN_GRID, BiquadSpec
from beqforge import explain, record
from beqforge.filters import Realisation, biquad_sos, magnitude_db
from beqforge.pipeline import target_fit

DEVICE = Realisation()
BAND = (5.0, 200.0)
SHELF = [BiquadSpec("low_shelf", 20.0, 10.0, 0.707)]


def _plays(filters: list[BiquadSpec]) -> np.ndarray:
    sos = DEVICE.quantise(biquad_sos(filters, DEVICE.fs))
    return magnitude_db(sos, DESIGN_GRID, DEVICE.fs)


def test_a_target_the_device_delivers_exactly_has_no_error():
    found = target_fit(SHELF, _plays(SHELF), DEVICE, BAND, 0.5)
    assert found.max_error_db == pytest.approx(0.0, abs=1e-9)
    assert found.rms_db == pytest.approx(0.0, abs=1e-9)
    assert found.within_tolerance == pytest.approx(1.0)
    assert found.band_hz == BAND
    assert found.tolerance_db == 0.5


def test_a_shortfall_is_signed_located_and_weighted():
    # asked for 1 dB more than it delivers, wherever it delivers a boost at all
    delivered = _plays(SHELF)
    target = np.where(delivered > 0.0, delivered + 1.0, delivered)
    found = target_fit(SHELF, target, DEVICE, BAND, 0.5)
    assert found.max_error_db == pytest.approx(1.0)
    assert not found.over
    assert BAND[0] <= found.at_hz <= BAND[1]
    # every boosted bin is 1 dB short: the weighted RMS is that 1 dB, and none is within 0.5
    assert found.rms_db == pytest.approx(1.0, abs=1e-6)
    assert found.within_tolerance == pytest.approx(0.0)


def test_the_share_within_tolerance_never_rounds_above_one():
    # every boost it asks for is met; the bins it asks to cut are missed but weigh nothing,
    # and over the old denominator they rounded this share to 1.0000000000000002
    inside = (DESIGN_GRID >= BAND[0]) & (DESIGN_GRID <= BAND[1])
    rng = np.random.default_rng(2)
    asked = rng.uniform(0.0, 0.5, inside.sum())
    asked[rng.random(inside.sum()) < 0.3] = -5.0
    target = np.zeros_like(DESIGN_GRID)
    target[inside] = asked
    assert target_fit([], target, DEVICE, BAND, 0.5).within_tolerance == 1.0


def test_an_unrequested_boost_has_a_worst_error_but_no_weighted_one():
    found = target_fit(SHELF, np.zeros_like(DESIGN_GRID), DEVICE, BAND, 0.5)
    assert found.over
    assert found.max_error_db == pytest.approx(10.0, abs=0.5)
    assert math.isnan(found.rms_db)
    assert math.isnan(found.within_tolerance)


def test_only_the_scored_band_is_measured():
    stray = [*SHELF, BiquadSpec("peaking_eq", 350.0, 6.0, 8.0)]
    target = _plays(SHELF)
    assert target_fit(stray, target, DEVICE, BAND, 0.5).max_error_db < 0.5
    wide = target_fit(stray, target, DEVICE, (5.0, float(DESIGN_GRID[-1])), 0.5)
    assert wide.max_error_db == pytest.approx(6.0, abs=0.3)
    assert wide.over
    assert wide.at_hz == pytest.approx(350.0, rel=0.05)


def test_an_unstable_cascade_has_no_fit(monkeypatch):
    import beqforge.pipeline as P

    monkeypatch.setattr(P, "unstable_sections", lambda *a: [0])
    assert target_fit(SHELF, _plays(SHELF), DEVICE, BAND, 0.5) is None


def test_explain_says_which_way_and_that_it_is_a_match_to_the_target():
    from dataclasses import replace

    from tests.test_design_designer import _FIT, _candidate

    sentence = explain.fit(_candidate())
    assert "0.1 dB RMS over 5.0-212.0 Hz" in sentence
    assert "96% of that boost within ±0.5 dB" in sentence
    assert "short of it at 9.0 Hz" in sentence
    assert "not a measure of whether the target is right" in sentence
    unweighted = replace(_FIT, rms_db=math.nan, within_tolerance=math.nan, over=True)
    assert "asks for no boost" in explain.fit(_candidate(target_fit=unweighted))
    assert explain.fit(_candidate(target_fit=None)) == "fit: not measured"


def test_every_run_candidate_is_measured_over_the_band_its_fit_was_scored_on(
    monkeypatch,
):
    import beqforge.pipeline as P
    from tests.test_design_strategy_config import inputs

    material, diagnosis, envelopes, identification = inputs()
    monkeypatch.setattr(P, "diagnose", lambda *a: diagnosis)
    monkeypatch.setattr(P, "extract", lambda *a: envelopes)
    monkeypatch.setattr(P, "identify_rolloff", lambda *a: identification)
    monkeypatch.setattr(P, "passband_ripple_db", lambda *a, **k: None)
    params = P.PipelineParams(strategies=("parametric", "flatten"), max_sections=1)
    report = P.run(material, params)
    labels = {c.label for c in report.candidates}
    assert "parametric" in labels
    for candidate in report.candidates:
        fit = candidate.target_fit
        assert fit is not None
        if candidate.label == "parametric":
            # `design` scored it on its own residual band
            assert fit.band_hz == params.residual_band_hz
        else:
            # `_fit_all`'s shared band: never narrower than the nominal one
            assert fit.band_hz[0] == params.residual_band_hz[0]
            assert fit.band_hz[1] >= params.residual_band_hz[1]
        written = record._candidate(candidate)["target_fit"]
        assert written["max_error_db"] == pytest.approx(fit.max_error_db)
        assert list(written["band_hz"]) == list(fit.band_hz)
