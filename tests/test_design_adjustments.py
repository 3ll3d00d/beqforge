"""Contract 1.5's adjustments (`beqforge.adjustments`, `plans/contract-1.5-adjustments.md`).

The mapping onto parameters and every answer is pure and tested without a fit. Four real designs of the synthetic
24 Hz Butterworth title (`test_design_designer_server._known_filter_request`, `flatten` only, about 12 s each) check
the direction each kind moves a design in, as beqdesigner's conformance list asks; a request without adjustments is
held to its 1.4 answer by `test_design_golden.py`.
"""

import dataclasses
import json

import pytest

from beqforge.adjustments import (
    MAX_TILT_DB_PER_OCTAVE,
    AdjustmentOutcome,
    DesignAdjustment,
    adjustments_from_json,
    apply_adjustments,
    finish_outcomes,
    kinds_for,
    peak_boost_db,
)
from beqforge.designer import (
    ContractViolation,
    DesignResponse,
    design,
    request_from_json,
    response_to_json,
    validate_response,
)
from beqforge.pipeline import PipelineParams
from tests.test_design_designer_server import _known_filter_request

PARAMS = PipelineParams()


def _ask(ident: str, kind: str, **params) -> DesignAdjustment:
    return DesignAdjustment(ident, kind, params)


# --- shape ----------------------------------------------------------------------------------------------------------


def test_adjustments_are_read_as_sent_and_none_is_none() -> None:
    body = [
        {"id": "a1", "kind": "floor", "params": {"hz": 10}, "text": "rumble"},
        {"id": "a2", "kind": "note"},
    ]
    assert adjustments_from_json(body) == (
        DesignAdjustment("a1", "floor", {"hz": 10}, "rumble"),
        DesignAdjustment("a2", "note", {}, None),
    )
    assert adjustments_from_json(None) == ()


@pytest.mark.parametrize(
    "body",
    [
        {"id": "a"},
        ["floor"],
        [{"kind": "floor"}],
        [{"id": "a", "kind": ""}],
        [{"id": "a", "kind": "x", "params": [1]}],
        [{"id": "a", "kind": "x"}, {"id": "a", "kind": "y"}],
    ],
)
def test_only_a_body_not_of_the_shape_is_refused(body) -> None:
    with pytest.raises((TypeError, ValueError)):  # the server answers either with a 400
        adjustments_from_json(body)


# --- the mapping and the answers ----------------------------------------------------------------------------------


def test_a_request_without_adjustments_leaves_the_parameters_alone() -> None:
    params, outcomes = apply_adjustments(PARAMS, ())
    assert params is PARAMS and outcomes == {}


def test_each_kind_sets_its_dial_for_this_request() -> None:
    params, outcomes = apply_adjustments(
        PARAMS,
        (
            _ask("a1", "exclude_band", low_hz=28, high_hz=34),
            _ask("a2", "floor", hz=12),
            _ask("a3", "max_boost", db=10),
            _ask("a4", "goal_tilt", db_per_octave=1.0),
        ),
    )
    assert params.exclude_bands_hz == ((28.0, 34.0),)
    assert params.lowest_frequency_hz == 12.0
    assert params.max_target_boost_db == 10.0 and params.parametric_max_boost_db == 10.0
    assert set(params.restore_caps_db) == {10.0}
    assert params.accept.target_tilt_db_per_octave == 1.0
    assert {i: o.outcome for i, o in outcomes.items()} == dict.fromkeys(
        ("a1", "a2", "a3", "a4"), "honoured"
    )
    assert (
        PARAMS.max_target_boost_db is None and PARAMS.exclude_bands_hz == ()
    )  # the server's are untouched


@pytest.mark.parametrize(
    "ask, outcome, says",
    [
        (
            _ask("a", "exclude_band", low_hz=1, high_hz=10),
            "adapted",
            "narrowed to the band analysed",
        ),
        (
            _ask("a", "exclude_band", low_hz=300, high_hz=400),
            "declined",
            "outside the band analysed",
        ),
        (
            _ask("a", "exclude_band", low_hz=30, high_hz=20),
            "declined",
            "low below high",
        ),
        (_ask("a", "floor", hz=2), "adapted", "nothing is placed below 5 Hz"),
        (_ask("a", "floor", hz=150), "declined", "too little of the band"),
        (_ask("a", "floor", hz="ten"), "declined", "positive number"),
        (_ask("a", "max_boost", db=0), "declined", "positive number"),
        (
            _ask("a", "goal_tilt", db_per_octave=MAX_TILT_DB_PER_OCTAVE + 1),
            "declined",
            "is not taken",
        ),
        (_ask("a", "note"), "not_understood", "kept with the design"),
        (
            _ask("a", "x-someone-else", names=["x"]),
            "not_understood",
            "not 'x-someone-else'",
        ),
    ],
)
def test_what_cannot_be_done_as_asked_is_answered_with_why(ask, outcome, says) -> None:
    _, outcomes = apply_adjustments(PARAMS, (ask,))
    assert outcomes["a"].outcome == outcome and says in outcomes["a"].reason


def test_order_does_not_matter_and_a_second_of_a_one_value_kind_is_declined() -> None:
    first, second = _ask("a1", "max_boost", db=8), _ask("a2", "max_boost", db=12)
    params, outcomes = apply_adjustments(PARAMS, (second, first))
    assert params == apply_adjustments(PARAMS, (first, second))[0]
    assert params.max_target_boost_db == 8.0
    assert (
        outcomes["a2"].outcome == "declined" and "a1 was used" in outcomes["a2"].reason
    )


def test_health_lists_the_kinds_with_the_servers_own_settings_as_defaults() -> None:
    kinds = kinds_for(dataclasses.replace(PARAMS, lowest_frequency_hz=6.0))
    assert set(kinds) == {"exclude_band", "floor", "max_boost", "goal_tilt", "note"}
    assert kinds["floor"]["params"]["hz"]["default"] == 6.0
    assert (
        kinds["goal_tilt"]["params"]["db_per_octave"]["maximum"]
        == MAX_TILT_DB_PER_OCTAVE
    )
    json.dumps(kinds)  # it goes on the wire as it is


def test_a_cap_the_realised_design_still_passes_is_adapted_and_a_decline_is_said() -> (
    None
):
    from beqforge import BiquadSpec

    shelf = [BiquadSpec(type="low_shelf", freq_hz=20.0, gain_db=9.0, q=0.7)]
    report = type("R", (), {"accepted": type("C", (), {"filters": shelf})()})()
    asked = (_ask("a1", "max_boost", db=6), _ask("a2", "floor", hz=10))
    _, provisional = apply_adjustments(PARAMS, asked)
    finished = finish_outcomes(provisional, asked, report, PARAMS)
    assert peak_boost_db(shelf, PARAMS.realisation.fs) == pytest.approx(9.0, abs=0.1)
    assert finished[0].outcome == "adapted" and finished[0].applied[
        "db"
    ] == pytest.approx(9.0, abs=0.1)
    declined = finish_outcomes(
        provisional, asked, type("R", (), {"accepted": None})(), PARAMS
    )
    assert (
        declined[1].outcome == "honoured"
        and "did not support a design" in declined[1].reason
    )


# --- the wire -------------------------------------------------------------------------------------------------------


def test_a_response_carries_its_answers_only_when_some_were_asked() -> None:
    plain = DesignResponse(contract_version="1.4", decline_reason="no_usable_plateau")
    assert "adjustment_outcomes" not in response_to_json(plain)
    answered = dataclasses.replace(
        plain,
        contract_version="1.5",
        adjustment_outcomes=[AdjustmentOutcome("a1", "declined", None, "no")],
    )
    assert response_to_json(answered)["adjustment_outcomes"] == [
        {"id": "a1", "outcome": "declined", "applied": None, "reason": "no"}
    ]
    validate_response(answered)


@pytest.mark.parametrize(
    "outcome",
    [
        AdjustmentOutcome("a", "maybe", None, "x"),
        AdjustmentOutcome("a", "adapted", None, "x"),
        AdjustmentOutcome("a", "declined"),
        AdjustmentOutcome("a", "declined", {"x": 1}, "x"),
    ],
)
def test_answers_that_break_the_contract_are_never_sent(outcome) -> None:
    with pytest.raises(ContractViolation):
        validate_response(
            DesignResponse(
                contract_version="1.5",
                decline_reason="x",
                adjustment_outcomes=[outcome],
            )
        )


# --- direction, on real designs -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def designed():
    """The synthetic title designed plainly and with each kind (flatten only, as the server tests)."""
    body = _known_filter_request()
    params = PipelineParams(strategies=("flatten",))

    def run(*asks):
        request = request_from_json(
            {
                **body,
                "contract_version": "1.5",
                "adjustments": [
                    {"id": f"a{i}", "kind": kind, "params": p}
                    for i, (kind, p) in enumerate(asks)
                ],
            }
        )
        response = design(request, params)
        validate_response(response)
        return response

    return {
        "plain": run(),
        "capped": run(("max_boost", {"db": 6})),
        "tilted": run(("goal_tilt", {"db_per_octave": 1.5})),
        "floored": run(("floor", {"hz": 15})),
        "band": run(("exclude_band", {"low_hz": 10, "high_hz": 18})),
    }


def _peak(response) -> float:
    return peak_boost_db(
        response.candidates[0].filters, PipelineParams().realisation.fs
    )


def test_a_boost_cap_lowers_the_peak_boost(designed) -> None:
    assert _peak(designed["plain"]) > 10
    assert _peak(designed["capped"]) < 6.5
    assert designed["capped"].adjustment_outcomes[0].outcome == "honoured"
    assert designed["plain"].adjustment_outcomes is None


def test_a_tilted_goal_asks_for_more_at_the_bottom(designed) -> None:
    assert (
        designed["tilted"].candidates[0].mv_adjust_db
        > designed["plain"].candidates[0].mv_adjust_db + 0.5
    )


def test_a_floor_keeps_every_section_above_it(designed) -> None:
    assert min(f.freq_hz for f in designed["floored"].candidates[0].filters) >= 15


def test_leaving_out_the_band_that_holds_the_rolloff_declines_and_says_so(
    designed,
) -> None:
    band = designed["band"]
    assert band.candidates is None and band.decline_reason
    assert band.adjustment_outcomes[0].outcome == "honoured"
    assert "did not support a design" in band.adjustment_outcomes[0].reason
