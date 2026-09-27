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

import numpy as np
import pytest

from beqforge import BiquadSpec
from beqforge.accept import AcceptParams, Verdict
from beqforge.designer import (
    CONTRACT_VERSION,
    ContractViolation,
    DesignCandidate,
    DesignRequest,
    DesignResponse,
    _decline_for_blockers,
    _decline_for_no_passing_candidate,
    _ndarray_from_json,
    _ndarray_to_json,
    _to_design_candidate,
    design,
    request_from_json,
    response_to_json,
    validate_response,
)
from beqforge.filters import Realisation
from beqforge.material import PlaybackParams
from beqforge.pipeline import Candidate, FitStats, PipelineParams, Report, Timings
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


def _candidate(
    label: str = "flatten",
    *,
    passed: bool = True,
    confidence: float = 0.8,
    offset_db: float = -1.2,
    fit_error_db: float = 0.3,
    method: str = "fitted",
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
    candidate = _candidate(confidence=0.62, offset_db=-3.4, fit_error_db=0.12)
    params = PipelineParams()
    mapped = _to_design_candidate(candidate, params, report_gain_reduction=True)
    assert mapped.confidence == pytest.approx(0.62)
    assert mapped.mv_adjust_db == pytest.approx(candidate.mv_adjust_db)
    assert mapped.method == "fitted"
    assert mapped.gain_reduction_db == pytest.approx(-3.4)
    assert mapped.residual_db == pytest.approx(0.12)
    assert mapped.residual_band_hz == params.residual_band_hz
    assert mapped.commentary["strategy"] == "flatten"


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


def test_to_design_candidate_leaves_residual_none_without_a_finite_error() -> None:
    candidate = _candidate(fit_error_db=math.nan)
    mapped = _to_design_candidate(
        candidate, PipelineParams(), report_gain_reduction=False
    )
    assert mapped.residual_db is None
    assert mapped.residual_band_hz is None


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
    monkeypatch.setattr("beqforge.designer.run", lambda material, params: report)

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
    monkeypatch.setattr("beqforge.designer.run", lambda material, params: report)

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
    monkeypatch.setattr("beqforge.designer.run", lambda material, params: report)

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

    def fake_run(material, params):
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
    assert seen_params["playback"].crossover_hz == pytest.approx(100.0)


def test_design_echoes_the_request_contract_version(monkeypatch) -> None:
    report = _report(
        [], evidence_notes=("no qualifying loud events; restoration withheld",)
    )
    monkeypatch.setattr("beqforge.designer.run", lambda material, params: report)

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
    monkeypatch.setattr("beqforge.designer.run", lambda material, params: report)
    monkeypatch.setattr("beqforge.record.revision", lambda: "abc123+src:def456")
    commentary = design(_small_request()).candidates[0].commentary
    assert commentary["beqforge_revision"] == "abc123+src:def456"
    # the plain-language account leads, before the notes and parameters that qualify it
    assert list(commentary)[:4] == ["found", "correction", "clipping", "alternatives"]
    assert commentary["strategy"] == "flatten"  # added to, not replaced
    assert "run_record" not in commentary  # nothing asked for one


def test_a_decline_names_the_build_that_made_it(monkeypatch) -> None:
    failing = dataclasses.replace(
        _candidate(passed=False), verdict=_verdict(False, ["overshoot"])
    )
    monkeypatch.setattr(
        "beqforge.designer.run", lambda material, params: _report([failing])
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
        "beqforge.designer.run", lambda material, params: _report([_candidate()])
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
    assert "the assumed bass management (LR4 crossover at 80 Hz" in text
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
