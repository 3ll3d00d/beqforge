"""Contract 1.5's adjustments: what a caller asks a design to change, and beqforge's answer to each.

beqdesigner's `designer-interface.md` §2 "Adjustments" and §3 "Adjustment outcomes"; the handoff that set out this
mapping is [plans/contract-1.5-adjustments.md](../plans/contract-1.5-adjustments.md). Each kind lands on a dial
`serve-designer` already has, set for this one request:

* `exclude_band` (`low_hz`, `high_hz`): appended to `PipelineParams.exclude_bands_hz`, the list `--exclude` fills.
* `floor` (`hz`): `PipelineParams.lowest_frequency_hz`, raised (never lowered below the server's).
* `max_boost` (`db`): `PipelineParams.max_target_boost_db`, a ceiling on every strategy's target beside the evidence's
  (`pipeline.priced_by_evidence`), and `parametric_max_boost_db` and every `restore_caps_db` capped at it.
* `goal_tilt` (`db_per_octave`): `AcceptParams.target_tilt_db_per_octave`, which `--goal-tilt` sets, for this request.
* `note`: free text, kept in the answer's reason and not acted on.

Nothing here can make beqforge publish what its evidence does not support (§4): every kind narrows or weakens a
design, or changes the goal the judge then holds the design to. A request with no adjustments is not touched, so its
answer is the 1.4 answer. Pure: no I/O, no fitting.
"""

import dataclasses
import math
from dataclasses import dataclass

import numpy as np

from beqforge.filters import biquad_sos, magnitude_db
from beqforge.pipeline import DESIGN_GRID, PipelineParams, Report

KINDS = ("exclude_band", "floor", "max_boost", "goal_tilt", "note")
OUTCOMES = ("honoured", "adapted", "declined", "not_understood")

MAX_TILT_DB_PER_OCTAVE = 3.0
"""The steepest goal tilt taken. `AcceptParams.target_tilt_db_per_octave` documents roughly 6 dB of headroom for
+2 dB/octave; past 3 the goal asks more of the bottom than any title in the baseline set had to give."""


@dataclass(frozen=True, slots=True)
class DesignAdjustment:
    """§2: one change asked for."""

    id: str
    kind: str
    params: dict
    text: str | None = None


@dataclass(frozen=True, slots=True)
class AdjustmentOutcome:
    """§3: what was done with one adjustment."""

    id: str
    outcome: str
    applied: dict | None = None
    reason: str | None = None


def adjustments_from_json(body: object) -> tuple[DesignAdjustment, ...]:
    """The request's `adjustments`, checked for shape only (§2: an unknown kind or a bad parameter is answered, not
    refused). Absent or null is none.

    Raises:
        TypeError: when it is not a list of objects, or one's `params` is not an object.
        ValueError: when one has no `id` or `kind`, or two share an id.
    """
    if body is None:
        return ()
    if not isinstance(body, list):
        raise TypeError("adjustments must be a list")
    seen: set[str] = set()
    adjustments = []
    for i, item in enumerate(body):
        if not isinstance(item, dict):
            raise TypeError(f"adjustments[{i}] must be an object")
        ident, kind, params = item.get("id"), item.get("kind"), item.get("params", {})
        if (
            not isinstance(ident, str)
            or not ident
            or not isinstance(kind, str)
            or not kind
        ):
            raise ValueError(f"adjustments[{i}] needs a non-empty id and kind")
        if not isinstance(params, dict):
            raise TypeError(f"adjustments[{i}].params must be an object")
        if ident in seen:
            raise ValueError(f"adjustment id {ident!r} is used twice")
        seen.add(ident)
        text = item.get("text")
        adjustments.append(
            DesignAdjustment(
                ident, kind, dict(params), text if isinstance(text, str) else None
            )
        )
    return tuple(adjustments)


def outcome_to_json(outcome: AdjustmentOutcome) -> dict:
    return {
        "id": outcome.id,
        "outcome": outcome.outcome,
        "applied": outcome.applied,
        "reason": outcome.reason,
    }


def kinds_for(params: PipelineParams) -> dict[str, dict]:
    """`/health`'s `adjustment_kinds` (§7.1): each kind this server takes, its parameters' defaults this server's own
    settings, so a caller's form opens on what the server would do."""
    low, high = params.diagnose.band_hz
    return {
        "exclude_band": {
            "description": "Leave a frequency range alone: neither evidence of a rolloff nor something to correct.",
            "params": {
                "low_hz": {
                    "type": "number",
                    "unit": "Hz",
                    "minimum": low,
                    "maximum": high,
                },
                "high_hz": {
                    "type": "number",
                    "unit": "Hz",
                    "minimum": low,
                    "maximum": high,
                },
            },
        },
        "floor": {
            "description": "Restore nothing below this frequency: no section is placed lower.",
            "params": {
                "hz": {
                    "type": "number",
                    "unit": "Hz",
                    "minimum": params.lowest_frequency_hz,
                    "maximum": high / 2,
                    "default": params.lowest_frequency_hz,
                },
            },
        },
        "max_boost": {
            "description": "Boost no more than this anywhere.",
            "params": {
                "db": {
                    "type": "number",
                    "unit": "dB",
                    "minimum": 1.0,
                    "maximum": max(params.restore_caps_db),
                    "default": params.parametric_max_boost_db,
                },
            },
        },
        "goal_tilt": {
            "description": "Tilt the goal towards the bottom: positive for more bass than flat, negative for less.",
            "params": {
                "db_per_octave": {
                    "type": "number",
                    "unit": "dB/oct",
                    "minimum": -MAX_TILT_DB_PER_OCTAVE,
                    "maximum": MAX_TILT_DB_PER_OCTAVE,
                    "default": params.accept.target_tilt_db_per_octave,
                },
            },
        },
        "note": {
            "description": "Anything else, in words. Kept with the design; not acted on."
        },
    }


def _number(params: dict, name: str) -> float | None:
    value = params.get(name)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        return None
    return float(value)


def _declined(adjustment: DesignAdjustment, reason: str) -> AdjustmentOutcome:
    return AdjustmentOutcome(adjustment.id, "declined", None, reason)


def apply_adjustments(
    params: PipelineParams, adjustments: tuple[DesignAdjustment, ...]
) -> tuple[PipelineParams, dict[str, AdjustmentOutcome]]:
    """The parameters this request designs with, and a provisional outcome for every adjustment (`finish_outcomes`
    revisits them once the design is made). Order does not matter: the result is the same whichever comes first,
    except that of two asks of a kind that takes one value, the first by id is used and the other declined."""
    outcomes: dict[str, AdjustmentOutcome] = {}
    band_low, band_high = params.diagnose.band_hz
    excluded = list(params.exclude_bands_hz)
    floor, cap, tilt = params.lowest_frequency_hz, None, None
    taken: dict[str, str] = {}
    for adjustment in sorted(adjustments, key=lambda a: a.id):
        kind, p = adjustment.kind, adjustment.params
        if kind in ("floor", "max_boost", "goal_tilt") and kind in taken:
            outcomes[adjustment.id] = _declined(
                adjustment, f"only one {kind} is taken: {taken[kind]} was used"
            )
            continue
        if kind == "exclude_band":
            low, high = _number(p, "low_hz"), _number(p, "high_hz")
            if low is None or high is None or low >= high:
                outcomes[adjustment.id] = _declined(
                    adjustment, "low_hz and high_hz must be numbers, low below high"
                )
                continue
            used = (max(low, band_low), min(high, band_high))
            if used[0] >= used[1]:
                outcomes[adjustment.id] = _declined(
                    adjustment,
                    f"{low:g}-{high:g} Hz is outside the band analysed ({band_low:g}-{band_high:g} Hz)",
                )
                continue
            excluded.append(used)
            applied = {"low_hz": used[0], "high_hz": used[1]}
            outcomes[adjustment.id] = (
                AdjustmentOutcome(adjustment.id, "honoured", applied)
                if used == (low, high)
                else AdjustmentOutcome(
                    adjustment.id,
                    "adapted",
                    applied,
                    f"narrowed to the band analysed ({band_low:g}-{band_high:g} Hz)",
                )
            )
        elif kind == "floor":
            hz = _number(p, "hz")
            if hz is None or hz <= 0:
                outcomes[adjustment.id] = _declined(
                    adjustment, "hz must be a positive number"
                )
                continue
            if hz >= band_high / 2:
                outcomes[adjustment.id] = _declined(
                    adjustment,
                    f"{hz:g} Hz leaves too little of the band analysed (to {band_high:g} Hz) to correct",
                )
                continue
            taken[kind] = adjustment.id
            if hz < params.lowest_frequency_hz:
                outcomes[adjustment.id] = AdjustmentOutcome(
                    adjustment.id,
                    "adapted",
                    {"hz": params.lowest_frequency_hz},
                    f"nothing is placed below {params.lowest_frequency_hz:g} Hz on any title: nothing was measured there",
                )
                continue
            floor = hz
            outcomes[adjustment.id] = AdjustmentOutcome(
                adjustment.id, "honoured", {"hz": hz}
            )
        elif kind == "max_boost":
            db = _number(p, "db")
            if db is None or db <= 0:
                outcomes[adjustment.id] = _declined(
                    adjustment, "db must be a positive number"
                )
                continue
            taken[kind] = adjustment.id
            cap = db
            outcomes[adjustment.id] = AdjustmentOutcome(
                adjustment.id, "honoured", {"db": db}
            )
        elif kind == "goal_tilt":
            rate = _number(p, "db_per_octave")
            if rate is None:
                outcomes[adjustment.id] = _declined(
                    adjustment, "db_per_octave must be a number"
                )
                continue
            if abs(rate) > MAX_TILT_DB_PER_OCTAVE:
                outcomes[adjustment.id] = _declined(
                    adjustment,
                    f"a tilt beyond ±{MAX_TILT_DB_PER_OCTAVE:g} dB/oct is not taken",
                )
                continue
            taken[kind] = adjustment.id
            tilt = rate
            outcomes[adjustment.id] = AdjustmentOutcome(
                adjustment.id, "honoured", {"db_per_octave": rate}
            )
        elif kind == "note":
            outcomes[adjustment.id] = AdjustmentOutcome(
                adjustment.id,
                "not_understood",
                None,
                "a note is kept with the design, not acted on",
            )
        else:
            outcomes[adjustment.id] = AdjustmentOutcome(
                adjustment.id,
                "not_understood",
                None,
                f"beqforge takes {', '.join(KINDS)}; not {kind!r}",
            )
    changes: dict = {}
    if excluded != list(params.exclude_bands_hz):
        changes["exclude_bands_hz"] = tuple(excluded)
    if floor != params.lowest_frequency_hz:
        changes["lowest_frequency_hz"] = floor
    if cap is not None:
        changes["max_target_boost_db"] = cap
        changes["parametric_max_boost_db"] = min(params.parametric_max_boost_db, cap)
        changes["restore_caps_db"] = tuple(
            sorted({min(c, cap) for c in params.restore_caps_db})
        )
    if tilt is not None:
        changes["accept"] = dataclasses.replace(
            params.accept, target_tilt_db_per_octave=tilt
        )
    return (dataclasses.replace(params, **changes) if changes else params), outcomes


def peak_boost_db(filters: list, fs: float) -> float:
    """The most a cascade boosts anywhere on the design grid, as realised at `fs`."""
    if not filters:
        return 0.0
    return float(np.max(magnitude_db(biquad_sos(list(filters), fs), DESIGN_GRID, fs)))


def finish_outcomes(
    outcomes: dict[str, AdjustmentOutcome],
    adjustments: tuple[DesignAdjustment, ...],
    report: Report,
    params: PipelineParams,
) -> list[AdjustmentOutcome]:
    """The answers in the request's order, once the design is made: a cap the realised filters still go past is
    `adapted` (the fit meets a target within a tolerance, so it can overshoot a little: say by how much), and an
    adjustment that was applied when the design then declined says so (it may be why the evidence left was too thin)."""
    accepted = report.accepted
    peak = (
        peak_boost_db(accepted.filters, params.realisation.fs)
        if accepted is not None
        else None
    )
    finished = []
    for adjustment in adjustments:
        outcome = outcomes[adjustment.id]
        if (
            adjustment.kind == "max_boost"
            and outcome.outcome == "honoured"
            and peak is not None
            and outcome.applied is not None
            and peak
            > outcome.applied["db"]
            + params.residual_target_db  # within the fit's own tolerance: met
        ):
            outcome = AdjustmentOutcome(
                adjustment.id,
                "adapted",
                {"db": round(peak, 2)},
                f"capped at {outcome.applied['db']:g} dB; the realised design peaks at {peak:.1f} dB",
            )
        elif (
            accepted is None
            and outcome.outcome in ("honoured", "adapted")
            and not outcome.reason
        ):
            outcome = dataclasses.replace(
                outcome,
                reason="applied; with it the evidence left did not support a design (see the decline)",
            )
        finished.append(outcome)
    return finished
