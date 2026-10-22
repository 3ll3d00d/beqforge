"""The `design(request) -> response` binding against beqdesigner's designer-interface.md v1.0.

`beqforge/designer.py`'s own docstring has the contract summary. These tests avoid a real
fitter run (40-80s a title, AGENTS.md) wherever the logic under test does not need one: the
mapping from `Report`/`Candidate`/`Verdict` to `DesignResponse` is exercised against hand-built
or monkeypatched reports, real dataclasses throughout so a field rename here is caught. The one
real pipeline call (`test_design_declines_with_no_channel_decomposition`) exercises the fast
"missing evidence" abstention path, which never reaches the fitter.
"""

import dataclasses
import math
import os

import numpy as np
import pytest

from beqforge import BiquadSpec
from beqforge.accept import AcceptParams, Verdict
from beqforge.designer import (
    CONTRACT_VERSION,
    DESIGN_VERSION,
    ContractViolation,
    DesignCandidate,
    DesignRequest,
    DesignResponse,
    _candidate_to_json,
    _decline_for_blockers,
    _decline_for_no_passing_candidate,
    _ndarray_from_json,
    _ndarray_to_json,
    _to_design_candidate,
    design,
    design_settings_detail,
    design_settings_digest,
    playback_from_bass_management,
    request_from_json,
    response_to_json,
    validate_response,
)
from beqforge.filters import Realisation
from beqforge.material import PlaybackParams
from beqforge.pipeline import (
    Candidate,
    FitStats,
    PipelineParams,
    Report,
    TargetFit,
    Timings,
)
from beqforge.verify import Correction

FREQS = np.logspace(np.log10(4.0), np.log10(60.0), 240)
BAND = (5.0, 45.0)


def _correction() -> Correction:
    return Correction(
        freqs=FREQS,
        before_db=np.zeros_like(FREQS),
        after_db=np.zeros_like(FREQS),
        band_hz=BAND,
    )


def _verdict(passed: bool, failures: list[str] | None = None) -> Verdict:
    return Verdict(
        passed=passed,
        failures=failures or [],
        notes=[],
        worst_gradient_before=0.0,
        worst_gradient_after=0.0,
        extent_hz=40.0,
        drift_db=0.0,
    )


def _headroom(offset_db: float, unavailable_reason: str | None = None):
    from beqforge.pipeline import Headroom

    return Headroom(
        offset_db=offset_db,
        peak=None,
        playback=PlaybackParams(),
        realisation=Realisation(),
        analysis_fs=1000.0,
        unavailable_reason=unavailable_reason,
    )


_FIT = TargetFit(
    band_hz=(5.0, 212.0),
    max_error_db=0.12,
    at_hz=9.0,
    over=False,
    rms_db=0.05,
    within_tolerance=0.96,
    tolerance_db=0.5,
)


def _candidate(
    label: str = "flatten",
    *,
    passed: bool = True,
    confidence: float = 0.8,
    offset_db: float = -1.2,
    fit_error_db: float = 0.3,
    method: str = "fitted",
    target_fit: TargetFit | None = _FIT,
) -> Candidate:
    return Candidate(
        label=label,
        filters=[BiquadSpec(type="low_shelf", freq_hz=15.81, gain_db=15.918, q=0.7071)],
        target_db=np.zeros_like(FREQS),
        fit_error_db=fit_error_db,
        correction=_correction(),
        verdict=_verdict(passed),
        method=method,
        headroom=_headroom(offset_db),
        correction_support_score=confidence,
        target_fit=target_fit,
    )


def _report(
    candidates: list[Candidate], evidence_notes: tuple[str, ...] = ()
) -> Report:
    return Report(
        material=None,
        diagnosis=None,
        identification=None,
        candidates=candidates,
        timings=Timings(),
        fit_stats=FitStats(),
        accept=AcceptParams(),
        evidence_notes=evidence_notes,
    )


# ---- wire format ----------------------------------------------------------


def test_ndarray_round_trips_through_json() -> None:
    arr = np.array([1.0, -2.5, 3.0], dtype=np.float64)
    assert np.array_equal(_ndarray_from_json(_ndarray_to_json(arr)), arr)


def test_ndarray_from_json_rejects_a_non_float64_dtype() -> None:
    with pytest.raises(ValueError, match="dtype"):
        _ndarray_from_json({"dtype": "float32", "shape": [1], "data_base64": ""})


def test_request_from_json_round_trips_channels_and_bass_management() -> None:
    mono = np.array([0.1, 0.2, 0.3])
    left = np.array([0.05, 0.1, 0.15])
    body = {
        "contract_version": "1.0",
        "fs": 1000,
        "coverage": "complete_programme",
        "mono_mix": _ndarray_to_json(mono),
        "channels": {"L": _ndarray_to_json(left)},
        "bass_management": {
            "lpf_fs": 80.0,
            "lpf_position": "Before",
            "headroom_type": "WCS",
            "clip_before": False,
            "clip_after": False,
        },
    }
    request = request_from_json(body)
    assert request.contract_version == "1.0"
    assert request.fs == 1000
    assert np.array_equal(request.mono_mix, mono)
    assert np.array_equal(request.channels["L"], left)
    assert request.bass_management["lpf_fs"] == 80.0


def test_request_from_json_rejects_channel_length_mismatch() -> None:
    body = {
        "contract_version": "1.0",
        "fs": 1000,
        "coverage": "complete_programme",
        "mono_mix": _ndarray_to_json(np.zeros(8)),
        "channels": {"L": _ndarray_to_json(np.zeros(5))},
    }
    with pytest.raises(ValueError, match=r"channel 'L' has 5 samples; mono_mix has 8"):
        request_from_json(body)


def test_request_from_json_rejects_non_1d_and_non_finite_audio() -> None:
    body = {
        "contract_version": "1.0",
        "fs": 1000,
        "coverage": "complete_programme",
        "mono_mix": _ndarray_to_json(np.zeros((2, 3))),
    }
    with pytest.raises(ValueError, match="mono_mix must be a 1-D"):
        request_from_json(body)

    body["mono_mix"] = _ndarray_to_json(np.array([0.0, np.inf]))
    with pytest.raises(ValueError, match="mono_mix must contain only finite"):
        request_from_json(body)


def test_request_from_json_leaves_absent_fields_none() -> None:
    body = {
        "contract_version": "1.0",
        "fs": 1000,
        "coverage": "excerpt",
        "mono_mix": _ndarray_to_json(np.array([0.0])),
    }
    request = request_from_json(body)
    assert request.channels is None
    assert request.bass_management is None


def test_response_to_json_success_omits_decline_fields() -> None:
    response = DesignResponse(
        contract_version="1.0",
        candidates=[
            DesignCandidate(
                filters=[
                    BiquadSpec(
                        type="low_shelf", freq_hz=15.81, gain_db=15.918, q=0.7071
                    )
                ],
                confidence=0.9,
                mv_adjust_db=15.918,
                method="exact",
            )
        ],
    )
    body = response_to_json(response)
    assert "decline_reason" not in body
    assert body["candidates"][0]["filters"][0]["type"] == "low_shelf"
    assert body["candidates"][0]["method"] == "exact"


def test_response_to_json_decline_omits_candidates() -> None:
    response = DesignResponse(
        contract_version="1.0",
        decline_reason="no_rolloff_detected",
        decline_message="msg",
    )
    body = response_to_json(response)
    assert "candidates" not in body
    assert body["decline_reason"] == "no_rolloff_detected"


# ---- candidate mapping ------------------------------------------------


def test_to_design_candidate_maps_the_expected_fields() -> None:
    candidate = _candidate(confidence=0.62, offset_db=-3.4, fit_error_db=0.3)
    params = PipelineParams()
    mapped = _to_design_candidate(candidate, params, report_gain_reduction=True)
    assert mapped.confidence == pytest.approx(0.62)
    assert mapped.mv_adjust_db == pytest.approx(candidate.mv_adjust_db)
    assert mapped.method == "fitted"
    assert mapped.gain_reduction_db == pytest.approx(-3.4)
    assert mapped.commentary["strategy"] == "flatten"


def test_to_design_candidate_reports_the_published_fit_not_the_fit_objective() -> None:
    """TODO 14: `residual_db` is what plays against its target, over the band actually
    scored — not `fit_error_db` (0.3 here) over the nominal `residual_band_hz`."""
    mapped = _to_design_candidate(
        _candidate(fit_error_db=0.3), PipelineParams(), report_gain_reduction=False
    )
    assert mapped.residual_db == pytest.approx(0.12)
    assert mapped.residual_band_hz == (5.0, 212.0)
    assert mapped.residual_at_hz == pytest.approx(9.0)
    assert mapped.residual_direction == "under"
    assert mapped.residual_rms_db == pytest.approx(0.05)
    assert mapped.residual_within_tolerance == pytest.approx(0.96)
    assert mapped.residual_tolerance_db == pytest.approx(0.5)


def test_to_design_candidate_omits_the_weighted_fit_when_no_boost_was_asked_for() -> (
    None
):
    fit = dataclasses.replace(
        _FIT, rms_db=math.nan, within_tolerance=math.nan, over=True
    )
    mapped = _to_design_candidate(
        _candidate(target_fit=fit), PipelineParams(), report_gain_reduction=False
    )
    assert mapped.residual_db == pytest.approx(0.12)
    assert mapped.residual_direction == "over"
    assert mapped.residual_rms_db is None
    assert mapped.residual_within_tolerance is None
    assert mapped.residual_tolerance_db is None
    validate_response(DesignResponse(contract_version="1.3", candidates=[mapped]))


def test_to_design_candidate_clamps_nan_confidence_to_zero() -> None:
    candidate = _candidate(confidence=math.nan)
    mapped = _to_design_candidate(
        candidate, PipelineParams(), report_gain_reduction=False
    )
    assert mapped.confidence == 0.0


def test_to_design_candidate_omits_gain_reduction_without_bass_management() -> None:
    candidate = _candidate(offset_db=-5.0)
    mapped = _to_design_candidate(
        candidate, PipelineParams(), report_gain_reduction=False
    )
    assert mapped.gain_reduction_db is None


def test_to_design_candidate_omits_gain_reduction_when_unavailable() -> None:
    candidate = dataclasses.replace(
        _candidate(), headroom=_headroom(math.nan, "no channel decomposition")
    )
    mapped = _to_design_candidate(
        candidate, PipelineParams(), report_gain_reduction=True
    )
    assert mapped.gain_reduction_db is None


def test_to_design_candidate_leaves_residual_none_without_a_measured_fit() -> None:
    for fit in (None, dataclasses.replace(_FIT, max_error_db=math.nan)):
        mapped = _to_design_candidate(
            _candidate(target_fit=fit), PipelineParams(), report_gain_reduction=False
        )
        assert mapped.residual_db is None
        assert mapped.residual_band_hz is None
        assert mapped.residual_at_hz is None
        assert mapped.residual_direction is None
        assert mapped.residual_rms_db is None
        assert mapped.residual_within_tolerance is None
        assert mapped.residual_tolerance_db is None


def test_to_design_candidate_output_satisfies_the_response_validator() -> None:
    """Consistency between the two independent things: the mapper and the validator.

    Not a tautology — `validate_response` is a separate re-implementation of beqdesigner's own
    rules (`ContractViolation`'s docstring), so this catches the mapper and the validator
    drifting apart from each other, not just from the contract.
    """
    mapped = _to_design_candidate(
        _candidate(), PipelineParams(), report_gain_reduction=True
    )
    validate_response(
        DesignResponse(contract_version=CONTRACT_VERSION, candidates=[mapped])
    )


# ---- response self-validation --------------------------------------------


def _valid_candidate(**overrides) -> DesignCandidate:
    kwargs = dict(
        filters=[BiquadSpec(type="low_shelf", freq_hz=15.81, gain_db=15.918, q=0.7071)],
        confidence=0.8,
        mv_adjust_db=15.918,
        method="fitted",
    )
    kwargs.update(overrides)
    return DesignCandidate(**kwargs)


def test_validate_response_accepts_a_well_formed_success() -> None:
    validate_response(
        DesignResponse(contract_version="1.0", candidates=[_valid_candidate()])
    )


def test_validate_response_accepts_a_well_formed_decline() -> None:
    validate_response(
        DesignResponse(contract_version="1.0", decline_reason="no_rolloff_detected")
    )


def test_validate_response_rejects_both_candidates_and_decline() -> None:
    with pytest.raises(ContractViolation, match="both"):
        validate_response(
            DesignResponse(
                contract_version="1.0",
                candidates=[_valid_candidate()],
                decline_reason="no_rolloff_detected",
            )
        )


def test_validate_response_rejects_neither_candidates_nor_decline() -> None:
    with pytest.raises(ContractViolation, match="neither"):
        validate_response(DesignResponse(contract_version="1.0"))


def test_validate_response_rejects_an_empty_candidates_list() -> None:
    with pytest.raises(ContractViolation, match="empty candidates"):
        validate_response(DesignResponse(contract_version="1.0", candidates=[]))


def test_validate_response_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ContractViolation, match="confidence"):
        validate_response(
            DesignResponse(
                contract_version="1.0", candidates=[_valid_candidate(confidence=1.5)]
            )
        )


def test_validate_response_rejects_candidates_not_ordered_by_confidence() -> None:
    with pytest.raises(ContractViolation, match="ordered"):
        validate_response(
            DesignResponse(
                contract_version="1.0",
                candidates=[
                    _valid_candidate(confidence=0.4),
                    _valid_candidate(confidence=0.9),
                ],
            )
        )


def test_validate_response_rejects_an_empty_filters_list() -> None:
    with pytest.raises(ContractViolation, match="empty filters"):
        validate_response(
            DesignResponse(
                contract_version="1.0", candidates=[_valid_candidate(filters=[])]
            )
        )


def test_validate_response_rejects_a_positive_gain_reduction() -> None:
    with pytest.raises(ContractViolation, match="gain_reduction_db"):
        validate_response(
            DesignResponse(
                contract_version="1.0",
                candidates=[_valid_candidate(gain_reduction_db=1.0)],
            )
        )


_MEASURED_FIT = dict(
    residual_db=1.1,
    residual_band_hz=(5.0, 212.0),
    residual_at_hz=9.0,
    residual_direction="under",
    residual_rms_db=0.3,
    residual_within_tolerance=0.96,
    residual_tolerance_db=0.5,
)


def test_validate_response_accepts_a_measured_fit() -> None:
    validate_response(
        DesignResponse(
            contract_version="1.3", candidates=[_valid_candidate(**_MEASURED_FIT)]
        )
    )


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"residual_db": None, "residual_band_hz": None}, "without residual_db"),
        ({"residual_at_hz": None}, "come together"),
        ({"residual_direction": "sideways"}, "'over' or 'under'"),
        ({"residual_at_hz": 300.0}, "outside residual_band_hz"),
        ({"residual_rms_db": 1.2}, r"residual_rms_db .* must be in"),
        ({"residual_rms_db": -0.1}, r"residual_rms_db .* must be in"),
        ({"residual_tolerance_db": None}, "come together"),
        ({"residual_rms_db": None}, "share one weighting"),
        ({"residual_within_tolerance": 1.5}, r"must be in \[0, 1\]"),
        ({"residual_tolerance_db": 0.0}, "must be > 0"),
        ({"residual_rms_db": math.nan}, "must be finite"),
    ],
)
def test_validate_response_rejects_an_inconsistent_fit(overrides, match) -> None:
    with pytest.raises(ContractViolation, match=match):
        validate_response(
            DesignResponse(
                contract_version="1.3",
                candidates=[_valid_candidate(**{**_MEASURED_FIT, **overrides})],
            )
        )


def test_response_to_json_carries_the_fit_only_when_measured() -> None:
    measured = _candidate_to_json(_valid_candidate(**_MEASURED_FIT))
    assert measured["residual_at_hz"] == 9.0
    assert measured["residual_direction"] == "under"
    assert measured["residual_rms_db"] == 0.3
    assert measured["residual_within_tolerance"] == 0.96
    assert measured["residual_tolerance_db"] == 0.5
    unmeasured = _candidate_to_json(_valid_candidate())
    assert (
        not {
            "residual_at_hz",
            "residual_direction",
            "residual_rms_db",
            "residual_within_tolerance",
            "residual_tolerance_db",
        }
        & unmeasured.keys()
    )


def test_validate_response_rejects_a_non_publishable_biquad_type() -> None:
    with pytest.raises(ContractViolation, match="not publishable"):
        validate_response(
            DesignResponse(
                contract_version="1.0",
                candidates=[
                    _valid_candidate(
                        filters=[
                            BiquadSpec(
                                type="all_pass", freq_hz=20.0, gain_db=0.0, q=1.0
                            )
                        ]
                    )
                ],
            )
        )


# ---- decline mapping ----------------------------------------------------


def test_decline_for_blockers_matches_the_first_known_prefix() -> None:
    notes = (
        "some unrelated note",
        "channel evidence unavailable; restoration withheld",
    )
    reason, message = _decline_for_blockers(notes)
    assert reason == "channel_evidence_unavailable"
    assert "channel evidence unavailable" in message


def test_decline_for_blockers_falls_back_when_nothing_matches() -> None:
    reason, _ = _decline_for_blockers(("a note not in the known blocker set",))
    assert reason == "restoration_withheld"


def test_decline_for_no_passing_candidate_lists_failures() -> None:
    failing = dataclasses.replace(
        _candidate(passed=False),
        verdict=_verdict(False, ["cliff exceeded", "tilt too steep"]),
    )
    reason, message = _decline_for_no_passing_candidate(_report([failing]))
    assert reason == "no_publishable_candidate"
    assert "cliff exceeded" in message and "tilt too steep" in message


# ---- design() branching (monkeypatched pipeline.run) ---------------------


def test_design_returns_a_single_candidate_when_one_is_accepted(monkeypatch) -> None:
    accepted = _candidate()
    report = _report([accepted])
    monkeypatch.setattr("beqforge.designer.run", lambda material, params, **_: report)

    request = DesignRequest(
        contract_version=CONTRACT_VERSION,
        fs=1000,
        mono_mix=np.zeros(10),
        coverage="complete_programme",
    )
    response = design(request)
    assert response.decline_reason is None
    assert len(response.candidates) == 1
    assert response.candidates[0].method == "fitted"
    assert response.contract_version == CONTRACT_VERSION


def test_design_declines_when_no_candidate_was_built(monkeypatch) -> None:
    report = _report(
        [], evidence_notes=("no usable contiguous mix plateau; restoration withheld",)
    )
    monkeypatch.setattr("beqforge.designer.run", lambda material, params, **_: report)

    request = DesignRequest(
        contract_version=CONTRACT_VERSION,
        fs=1000,
        mono_mix=np.zeros(10),
        coverage="complete_programme",
    )
    response = design(request)
    assert response.candidates is None
    assert response.decline_reason == "no_usable_plateau"


def test_design_declines_when_nothing_passed_acceptance(monkeypatch) -> None:
    failing = dataclasses.replace(
        _candidate(passed=False), verdict=_verdict(False, ["overshoot"])
    )
    report = _report([failing])
    monkeypatch.setattr("beqforge.designer.run", lambda material, params, **_: report)

    request = DesignRequest(
        contract_version=CONTRACT_VERSION,
        fs=1000,
        mono_mix=np.zeros(10),
        coverage="complete_programme",
    )
    response = design(request)
    assert response.decline_reason == "no_publishable_candidate"
    assert "overshoot" in response.decline_message


def test_design_turns_on_gain_reduction_only_with_bass_management(monkeypatch) -> None:
    accepted = _candidate(offset_db=-2.0)
    report = _report([accepted])
    seen_params = {}

    def fake_run(material, params, **_):
        seen_params["playback"] = params.playback
        return report

    monkeypatch.setattr("beqforge.designer.run", fake_run)

    request = DesignRequest(
        contract_version=CONTRACT_VERSION,
        fs=1000,
        mono_mix=np.zeros(10),
        coverage="complete_programme",
        bass_management={
            "lpf_fs": 100.0,
            "lpf_position": "Before",
            "headroom_type": "WCS",
            "clip_before": False,
            "clip_after": False,
        },
    )
    response = design(request)
    assert response.candidates[0].gain_reduction_db == pytest.approx(-2.0)
    playback = seen_params["playback"]
    assert playback.crossover_hz == pytest.approx(100.0)
    # one LR4, on every channel: the bus low-pass, with no second one on the mains
    assert playback.mains_lowpass_corner_hz is None
    assert playback.bus_lowpass_hz == pytest.approx(100.0)


FIVE_ONE = ("L", "R", "C", "LFE", "Ls", "Rs")
SEVEN_ONE = (*FIVE_ONE, "Lb", "Rb")


@pytest.mark.parametrize(
    ("names", "mains_db"),
    [
        (FIVE_ONE, -18.24),  # 20·log10(5 + 10^(10/20))
        (SEVEN_ONE, -20.14),
        (
            ("L", "R"),
            -14.26,
        ),  # the contract counts every key but "LFE", so no LFE is fine
    ],
)
def test_wcs_headroom_is_the_coherent_sum_of_the_channels_sent(names, mains_db) -> None:
    bm = {"lpf_fs": 80.0, "lpf_position": "Before", "headroom_type": "WCS"}
    playback = playback_from_bass_management(bm, names, PlaybackParams())
    assert playback.main_gain_db == pytest.approx(mains_db, abs=0.01)
    assert playback.lfe_gain_db == pytest.approx(mains_db + 10.0, abs=0.01)


def test_a_numeric_headroom_is_its_magnitude_plus_ten_db() -> None:
    bm = {"lpf_fs": 80.0, "lpf_position": "After", "headroom_type": "-5"}
    playback = playback_from_bass_management(bm, FIVE_ONE, PlaybackParams())
    assert (playback.main_gain_db, playback.lfe_gain_db) == (-15.0, -5.0)


def test_lpf_off_low_passes_nothing_but_keeps_the_crossover() -> None:
    bm = {"lpf_fs": 90.0, "lpf_position": "Off", "headroom_type": "WCS"}
    playback = playback_from_bass_management(bm, FIVE_ONE, PlaybackParams())
    assert playback.mains_lowpass_corner_hz is None
    assert playback.bus_lowpass_hz is None
    assert playback.crossover_hz == 90.0


@pytest.mark.parametrize(
    "bm",
    [
        {"lpf_position": "Before"},
        {"lpf_fs": "eighty"},
        {"lpf_fs": 80.0, "lpf_position": "Sideways"},
        {"lpf_fs": 80.0, "headroom_type": "loud"},
    ],
)
def test_a_malformed_bass_management_is_refused(bm) -> None:
    with pytest.raises(ValueError, match="bass_management"):
        playback_from_bass_management(bm, FIVE_ONE, PlaybackParams())


def test_clipping_simulation_is_named_as_not_simulated(monkeypatch) -> None:
    accepted = _candidate(offset_db=-2.0)
    monkeypatch.setattr(
        "beqforge.designer.run", lambda material, params, **_: _report([accepted])
    )
    request = DesignRequest(
        contract_version=CONTRACT_VERSION,
        fs=1000,
        mono_mix=np.zeros(10),
        coverage="complete_programme",
        bass_management={
            "lpf_fs": 80.0,
            "lpf_position": "Before",
            "headroom_type": "WCS",
            "clip_before": False,
            "clip_after": True,
        },
    )
    clipping = design(request).candidates[0].commentary["clipping"]
    assert "clip_after not simulated" in clipping
    assert "clip_before" not in clipping


def test_design_echoes_the_request_contract_version(monkeypatch) -> None:
    report = _report(
        [], evidence_notes=("no qualifying loud events; restoration withheld",)
    )
    monkeypatch.setattr("beqforge.designer.run", lambda material, params, **_: report)

    request = DesignRequest(
        contract_version="1.0",
        fs=1000,
        mono_mix=np.zeros(10),
        coverage="complete_programme",
    )
    response = design(request)
    assert response.contract_version == "1.0"


# ---- one real pipeline call: the fast abstention path --------------------


def test_design_declines_with_no_channel_decomposition() -> None:
    """No `channels` means no sub feed, which `pipeline.run` refuses before any fitting."""
    rng = np.random.default_rng(0)
    mono = rng.normal(scale=0.05, size=1000 * 60)  # one minute at 1 kHz

    request = DesignRequest(
        contract_version=CONTRACT_VERSION,
        fs=1000,
        mono_mix=mono,
        coverage="complete_programme",
    )
    response = design(request)
    assert response.candidates is None
    assert response.decline_reason == "channel_evidence_unavailable"


# ---- provenance (IMPROVEMENT_PLAN R1) --------------------------------------


def _small_request(mono_mix: np.ndarray | None = None) -> DesignRequest:
    return DesignRequest(
        contract_version=CONTRACT_VERSION,
        fs=1000,
        mono_mix=np.zeros(10) if mono_mix is None else mono_mix,
        coverage="complete_programme",
    )


def test_an_accepted_candidate_names_the_build_that_made_it(monkeypatch) -> None:
    report = _report([_candidate()])
    monkeypatch.setattr("beqforge.designer.run", lambda material, params, **_: report)
    monkeypatch.setattr("beqforge.record.revision", lambda: "abc123+src:def456")
    commentary = design(_small_request()).candidates[0].commentary
    assert commentary["beqforge_revision"] == "abc123+src:def456"
    # the plain-language account leads, before the notes and parameters that qualify it
    assert list(commentary)[:5] == [
        "found",
        "correction",
        "clipping",
        "fit",
        "alternatives",
    ]
    assert commentary["strategy"] == "flatten"  # added to, not replaced
    assert "run_record" not in commentary  # nothing asked for one


def test_a_decline_names_the_build_that_made_it(monkeypatch) -> None:
    failing = dataclasses.replace(
        _candidate(passed=False), verdict=_verdict(False, ["overshoot"])
    )
    monkeypatch.setattr(
        "beqforge.designer.run", lambda material, params, **_: _report([failing])
    )
    monkeypatch.setattr("beqforge.record.revision", lambda: "abc123+src:def456")
    response = design(_small_request())
    assert response.decline_message.startswith("flatten: overshoot")
    assert response.decline_message.endswith("[beqforge_revision: abc123+src:def456]")
    assert " | found: reference:" in response.decline_message
    validate_response(response)


def test_a_request_writes_a_replayable_record_named_by_its_audio(tmp_path) -> None:
    """The fast no-channels abstention, through the real pipeline and the real writer."""
    from beqforge import record

    mono = np.random.default_rng(0).normal(scale=0.05, size=1000 * 60)
    request = _small_request(mono_mix=mono)
    response = design(request, record_dir=tmp_path)
    assert response.decline_reason == "channel_evidence_unavailable"

    written = list(tmp_path.glob("designer-*.run.json.gz"))
    assert len(written) == 1
    assert f"run_record: {written[0]}" in response.decline_message
    document = record.read(written[0])
    fingerprint = record.Fingerprint.from_json(document["fingerprint"])
    assert fingerprint.material_path == ""
    assert fingerprint.material_sha256.startswith(written[0].name[9:25])
    assert fingerprint.revision == record.revision()
    assert record.stale_against(fingerprint) == []

    # the same request is the same file; a different mix is a different one
    design(request, record_dir=tmp_path)
    assert len(list(tmp_path.glob("*.run.json.gz"))) == 1
    design(_small_request(mono_mix=mono * 0.5), record_dir=tmp_path)
    assert len(list(tmp_path.glob("*.run.json.gz"))) == 2


def test_an_unwritable_record_dir_does_not_fail_the_design(tmp_path) -> None:
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory")
    mono = np.random.default_rng(0).normal(scale=0.05, size=1000 * 60)
    response = design(_small_request(mono_mix=mono), record_dir=blocked)
    assert response.decline_reason == "channel_evidence_unavailable"
    assert "run_record: not written" in response.decline_message


def test_the_response_joins_candidate_and_run_notes_once() -> None:
    """The contract has no run-level field, so the candidate's commentary carries both."""
    candidate = dataclasses.replace(
        _candidate(), target_notes=("boost cap binds", "shared")
    )
    mapped = _to_design_candidate(
        candidate,
        PipelineParams(),
        report_gain_reduction=False,
        run_notes=("shared", "mix reference"),
    )
    assert mapped.commentary["target_notes"] == "boost cap binds; shared; mix reference"


def test_the_judges_own_notes_reach_the_response() -> None:
    """IMPROVEMENT_PLAN E6: a correction resting below the level-invariance floor says so."""
    shaping = (
        "13.1 dB of the correction is claimed below 22.7 Hz, where the attenuation stops "
        "being level-invariant; this shaping diagnostic does not identify the cause (R2)"
    )
    candidate = _candidate()
    candidate.verdict.notes.append(shaping)
    mapped = _to_design_candidate(
        candidate, PipelineParams(), report_gain_reduction=False
    )
    assert shaping in mapped.commentary["verdict_notes"]


def test_the_response_says_the_fractions_in_words_not_bare_numbers(monkeypatch) -> None:
    """'Recovered fraction 0.981' meant nothing to a reviewer; the sentence has to carry it."""
    monkeypatch.setattr(
        "beqforge.designer.run", lambda material, params, **_: _report([_candidate()])
    )
    commentary = design(_small_request()).candidates[0].commentary
    assert "recovered_fraction" not in commentary
    assert "shaping_fraction" not in commentary


def test_the_clipping_line_says_whether_to_turn_the_sub_down() -> None:
    """Headroom is reported, never gated; the line has to say what to do and on what model."""
    import dataclasses as dc

    from beqforge import explain

    clean = dc.replace(_headroom(0.0), peak=0.42)
    clips = dc.replace(_headroom(-1.29), peak=1.16)
    quiet = dc.replace(_candidate(), headroom=clean)
    loud = dc.replace(_candidate(), headroom=clips)

    text = explain.clipping(quiet, from_request=False)
    assert (
        "the assumed bass management (LR4 mains low-pass at 80 Hz and on the sub bus at "
        "80 Hz, mains -20.2 dB, LFE -10.2 dB)" in text
    )
    assert "42% of full scale" in text and "does not clip" in text

    text = explain.clipping(loud, from_request=True)
    assert text.startswith("with your bass management")
    assert "turn the sub channel down by 1.3 dB to avoid clipping" in text

    unmeasured = dc.replace(
        _candidate(), headroom=_headroom(0.0, "no channel decomposition")
    )
    assert explain.clipping(unmeasured, from_request=False) == (
        "clipping: not measured (no channel decomposition)"
    )


# ---- 1.1: rejected designs, for review only ---------------------------------


def _failing(label: str, *failures: str, confidence: float = 0.8) -> Candidate:
    return dataclasses.replace(
        _candidate(label, passed=False, confidence=confidence),
        verdict=_verdict(False, list(failures)),
    )


def _design_with(monkeypatch, report: Report) -> DesignResponse:
    monkeypatch.setattr("beqforge.designer.run", lambda material, params, **_: report)
    return design(
        DesignRequest(
            contract_version=CONTRACT_VERSION,
            fs=1000,
            mono_mix=np.zeros(10),
            coverage="complete_programme",
        )
    )


def test_an_accepted_answer_carries_the_designs_that_failed(monkeypatch) -> None:
    """Beside the answer, not in `candidates`: only `candidates[0]` is ever acted on."""
    response = _design_with(
        monkeypatch,
        _report([_candidate(), _failing("counterfactual/25dB", "introduces a cliff")]),
    )
    validate_response(response)
    assert [c.commentary["strategy"] for c in response.candidates] == ["flatten"]
    assert response.candidates[0].rejection_reasons is None
    (rejected,) = response.rejected
    assert rejected.commentary["strategy"] == "counterfactual/25dB"
    assert rejected.rejection_reasons == ["introduces a cliff"]
    # the reviewer reads what it would have done beside why it was refused
    assert "section(s)" in rejected.commentary["correction"]
    assert "clipping" in rejected.commentary


def test_a_decline_carries_its_rejected_designs_nearest_to_acceptable_first(
    monkeypatch,
) -> None:
    response = _design_with(
        monkeypatch,
        _report(
            [
                _failing("flatten", "tilt", "cliff", "extent"),
                _failing("parametric", "cliff"),
            ]
        ),
    )
    validate_response(response)
    assert response.decline_reason == "no_publishable_candidate"
    assert response.candidates is None
    assert [c.commentary["strategy"] for c in response.rejected] == [
        "parametric",
        "flatten",
    ]


def test_only_loadable_rejections_are_returned(monkeypatch) -> None:
    """A passing loser was not rejected; a design with no sections cannot be loaded."""
    empty = dataclasses.replace(_failing("counterfactual/35dB", "unstable"), filters=[])
    response = _design_with(
        monkeypatch, _report([_candidate(), _candidate("parametric"), empty])
    )
    assert response.rejected is None
    assert "rejected" not in response_to_json(response)


def test_a_decline_before_any_design_has_nothing_rejected(monkeypatch) -> None:
    response = _design_with(
        monkeypatch, _report([], evidence_notes=("no usable contiguous mix plateau",))
    )
    assert response.rejected is None


def test_rejected_designs_reach_the_wire_and_a_1_0_body_is_unchanged() -> None:
    plain = DesignResponse(contract_version="1.0", candidates=[_valid_candidate()])
    body = response_to_json(plain)
    assert "rejected" not in body
    assert "rejection_reasons" not in body["candidates"][0]

    declined = DesignResponse(
        contract_version="1.1",
        decline_reason="no_publishable_candidate",
        rejected=[_valid_candidate(rejection_reasons=["cliff", "tilt"])],
    )
    body = response_to_json(declined)
    assert body["decline_reason"] == "no_publishable_candidate"
    assert body["rejected"][0]["rejection_reasons"] == ["cliff", "tilt"]
    assert body["rejected"][0]["filters"][0]["type"] == "low_shelf"


@pytest.mark.parametrize(
    "rejected, message",
    [
        ([], "empty list"),
        ([_valid_candidate()], "rejection_reasons"),
        ([_valid_candidate(rejection_reasons=[])], "rejection_reasons"),
        ([_valid_candidate(rejection_reasons=[""])], "rejection_reasons"),
        ([_valid_candidate(rejection_reasons=["x"], filters=[])], r"rejected\[0\]"),
        (
            [
                _valid_candidate(
                    rejection_reasons=["x"],
                    filters=[BiquadSpec("high_pass", 20.0, 0.0, 0.7)],
                )
            ],
            r"rejected\[0\]\.filters\[0\]",
        ),
    ],
)
def test_validate_response_rejects_a_malformed_rejected_list(rejected, message) -> None:
    for shape in (
        dict(candidates=[_valid_candidate()]),
        dict(decline_reason="no_publishable_candidate"),
    ):
        with pytest.raises(ContractViolation, match=message):
            validate_response(
                DesignResponse(contract_version="1.1", rejected=rejected, **shape)
            )


def test_validate_response_refuses_reasons_on_a_candidate() -> None:
    with pytest.raises(ContractViolation, match="belongs in rejected"):
        validate_response(
            DesignResponse(
                contract_version="1.1",
                candidates=[_valid_candidate(rejection_reasons=["cliff"])],
            )
        )


def test_rejected_designs_are_exempt_from_the_confidence_order() -> None:
    """Confidence measures evidence, not a pass: a refused design may score higher."""
    validate_response(
        DesignResponse(
            contract_version="1.1",
            candidates=[_valid_candidate(confidence=0.3)],
            rejected=[
                _valid_candidate(confidence=0.5, rejection_reasons=["cliff"]),
                _valid_candidate(confidence=0.9, rejection_reasons=["tilt"]),
            ],
        )
    )


# ---- 1.4: which answer a build gives ----------------------------------------


def test_every_answer_says_its_design_version_settings_and_build(monkeypatch) -> None:
    monkeypatch.setattr("beqforge.record.revision", lambda: "abc123+src:def456")
    params = PipelineParams(strategies=("flatten",))
    failing = dataclasses.replace(
        _candidate(passed=False), verdict=_verdict(False, ["overshoot"])
    )
    for report in (_report([_candidate()]), _report([failing])):
        monkeypatch.setattr("beqforge.designer.run", lambda m, p, r=report, **_: r)
        # whatever version the request names, as with the 1.1 and 1.3 fields
        response = design(
            dataclasses.replace(_small_request(), contract_version="1.0"), params
        )
        validate_response(response)
        body = response_to_json(response)
        assert body["contract_version"] == "1.0"
        assert body["design_version"] == DESIGN_VERSION
        assert body["design_settings"] == design_settings_digest(params)
        assert body["designer_build"] == "abc123+src:def456"


def test_a_response_without_the_1_4_fields_is_unchanged_on_the_wire() -> None:
    body = response_to_json(
        DesignResponse(contract_version="1.0", decline_reason="no_rolloff_detected")
    )
    assert not {"design_version", "design_settings", "designer_build"} & body.keys()


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"design_version": -1}, "design_version"),
        ({"design_version": "4"}, "design_version"),
        ({"design_version": True}, "design_version"),
        ({"design_settings": ""}, "design_settings"),
        ({"designer_build": 7}, "designer_build"),
    ],
)
def test_validate_response_rejects_a_malformed_design_identity(
    overrides, match
) -> None:
    with pytest.raises(ContractViolation, match=match):
        validate_response(
            DesignResponse(
                contract_version="1.4",
                decline_reason="no_rolloff_detected",
                **overrides,
            )
        )


def test_all_default_settings_are_the_empty_set() -> None:
    assert design_settings_detail(PipelineParams()) == {}
    assert design_settings_digest(PipelineParams()) == design_settings_digest(
        PipelineParams(
            strategies=("flatten", "counterfactual", "parametric"),
            realisation=Realisation(fs=96000, coefficient_bits=28, integer_bits=5),
        )
    )


def test_serve_designer_with_no_flags_sends_the_empty_set(monkeypatch) -> None:
    """All defaults has to mean the server started with no flags, or the empty set lies;
    workers, cores, the cache, records and the shared root are no part of it."""
    from tools.designer_server import build_parser, pipeline_params

    for name in list(os.environ):
        if name.startswith("BEQFORGE_"):
            monkeypatch.delenv(name)
    parser = build_parser()
    assert design_settings_detail(pipeline_params(parser.parse_args([]), parser)) == {}
    busy = parser.parse_args(
        ["--workers", "2", "--cores", "4", "--cache-dir", "c", "--record-dir", "r"]
        + ["--shared-root", "w"]
    )
    assert design_settings_detail(pipeline_params(busy, parser)) == {}
    tuned = parser.parse_args(["--integer-bits", "4", "--strategy", "flatten"])
    assert design_settings_detail(pipeline_params(tuned, parser)) == {
        "integer_bits": 4,
        "strategies": ["flatten"],
    }


@pytest.mark.parametrize(
    "changed",
    [
        PipelineParams(strategies=("flatten",)),
        PipelineParams(strategies=("parametric", "counterfactual", "flatten")),
        PipelineParams(exclude_bands_hz=((30.0, 32.0),)),
        PipelineParams(accept=AcceptParams(goal_tolerance_db=1.0)),
        PipelineParams(accept=AcceptParams(target_tilt_db_per_octave=0.25)),
        PipelineParams(judge_from_content_edge=True),
        PipelineParams(realisation=Realisation(fs=48000.0)),
        PipelineParams(realisation=Realisation(coefficient_bits=24)),
        PipelineParams(realisation=Realisation(integer_bits=4)),
    ],
)
def test_every_setting_that_can_change_an_answer_changes_the_digest(changed) -> None:
    assert design_settings_digest(changed) != design_settings_digest(PipelineParams())
    assert len(design_settings_detail(changed)) == 1


def test_equal_settings_digest_equally_and_exclusions_in_any_order() -> None:
    one = PipelineParams(exclude_bands_hz=((30.0, 32.0), (50, 52)))
    other = PipelineParams(exclude_bands_hz=((50.0, 52.0), (30.0, 32.0)))
    assert design_settings_digest(one) == design_settings_digest(other)
    assert design_settings_detail(one) == {
        "exclude_bands_hz": [[30.0, 32.0], [50.0, 52.0]]
    }
    assert len(design_settings_digest(one)) == 12


def test_the_per_request_playback_model_is_not_a_setting() -> None:
    """Bass management comes with each request, so it is the caller's to key on."""
    params = PipelineParams(strategies=("flatten",))
    assert design_settings_digest(
        dataclasses.replace(params, playback=PlaybackParams(crossover_hz=120.0))
    ) == design_settings_digest(params)
