"""The `design(request) -> response` binding for beqdesigner's designer-interface.md v1.0.

Read that document (in the sibling `beqdesigner` repo, `design/designer-interface.md`) before
touching this file — it is the contract, not this module. In short: beqdesigner POSTs a
`DesignRequest` (raw audio, already decimated) and expects a `DesignResponse` back — either a
ranked, non-empty list of candidates or a decline, never both, never neither. `tools/
designer_server.py` is the HTTP transport (§7.1); this module is the pure adapter between that
wire format and `beqforge.pipeline.run`, kept separately testable without a socket.

The whole file exists because this repo already does the work the contract asks for — the
mapping is almost entirely "read the field off `Report`/`Candidate`/`Verdict` that already
means this", not new analysis. Where there is genuine judgement (declining, `gain_reduction_db`
only when the caller told us its playback model, capping `confidence` defensively) it is called
out inline.
"""

from __future__ import annotations

import base64
import dataclasses
import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from beqforge import BiquadSpec
from beqforge.design import DesignMethod
from beqforge.material import Material
from beqforge.pipeline import Candidate, PipelineParams, Report, run

CONTRACT_VERSION = "1.0"

Coverage = Literal["complete_programme", "excerpt"]
ChannelScope = Literal["all_channels", "lfe_only", "mixed"]

_ARRAY_DTYPE = "float64"


@dataclass(frozen=True, slots=True)
class DesignRequest:
    """designer-interface.md §2."""

    contract_version: str
    fs: int
    mono_mix: np.ndarray
    coverage: Coverage
    channels: dict[str, np.ndarray] | None = None
    bass_management: dict | None = None


@dataclass(frozen=True, slots=True)
class DesignCandidate:
    """designer-interface.md §3."""

    filters: list[BiquadSpec]
    confidence: float
    mv_adjust_db: float
    method: DesignMethod
    gain_reduction_db: float | None = None
    residual_db: float | None = None
    residual_band_hz: tuple[float, float] | None = None
    commentary: dict[str, str] | None = None
    fc_hz: float | None = None
    slope: float | None = None
    fc_uncertainty_hz: float | None = None
    slope_uncertainty: float | None = None
    channel_scope: ChannelScope | None = None


@dataclass(frozen=True, slots=True)
class DesignResponse:
    """designer-interface.md §3. Exactly one of `candidates`/`decline_reason` is populated."""

    contract_version: str
    candidates: list[DesignCandidate] | None = None
    decline_reason: str | None = None
    decline_message: str | None = None


# Substrings `pipeline.run` puts in `Report.evidence_notes` when it returns `candidates=[]`
# (its `blockers` list, folded into the same free-text notes as everything else). Matched in
# order, first hit wins — these are not an enum on the pipeline side, so this mapping is the
# one place that has to be kept in sync with the wording there.
_BLOCKER_CODES: tuple[tuple[str, str], ...] = (
    ("excerpt:", "excerpt_coverage"),
    ("no usable contiguous mix plateau", "no_usable_plateau"),
    ("channel evidence unavailable", "channel_evidence_unavailable"),
    ("no qualifying loud events", "no_qualifying_loud_events"),
    ("no bins support a positive correction", "insufficient_coherent_bandwidth"),
    ("exclusions fragment the judged band", "exclusions_fragment_band"),
    ("playback verification unavailable", "playback_verification_unavailable"),
)


def _decline_for_blockers(evidence_notes: tuple[str, ...]) -> tuple[str, str]:
    for note in evidence_notes:
        for prefix, code in _BLOCKER_CODES:
            if prefix in note:
                return code, "; ".join(evidence_notes)
    return "restoration_withheld", "; ".join(evidence_notes)


def _decline_for_no_passing_candidate(report: Report) -> tuple[str, str]:
    parts = [
        f"{c.label}: {'; '.join(c.verdict.failures)}"
        for c in report.candidates
        if c.verdict.failures
    ]
    message = "; ".join(parts) if parts else "no candidate passed acceptance"
    return "no_publishable_candidate", message


def _to_design_candidate(
    candidate: Candidate, params: PipelineParams, *, report_gain_reduction: bool
) -> DesignCandidate:
    confidence = candidate.confidence
    if not math.isfinite(confidence):
        # correction_evidence_score is only NaN for a target with no positive weight, which an
        # accepted candidate should never have; clamped rather than trusted, per "never trust a
        # residual" applied to this boundary too.
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)

    gain_reduction_db = None
    if report_gain_reduction and candidate.headroom is not None:
        offset = candidate.headroom.offset_db
        if math.isfinite(offset):
            gain_reduction_db = min(offset, 0.0)

    residual_db: float | None = candidate.fit_error_db
    residual_band_hz: tuple[float, float] | None = params.residual_band_hz
    if residual_db is None or not math.isfinite(residual_db):
        residual_db = None
        residual_band_hz = None

    commentary = {"strategy": candidate.label}
    if candidate.effective_params:
        commentary["effective_params"] = candidate.effective_params
    if candidate.target_notes:
        commentary["target_notes"] = "; ".join(candidate.target_notes)
    if not math.isnan(candidate.verdict.recovered_fraction):
        commentary["recovered_fraction"] = f"{candidate.verdict.recovered_fraction:.3f}"
    if not math.isnan(candidate.verdict.shaping_fraction):
        commentary["shaping_fraction"] = f"{candidate.verdict.shaping_fraction:.3f}"

    return DesignCandidate(
        filters=list(candidate.filters),
        confidence=confidence,
        mv_adjust_db=candidate.mv_adjust_db,
        method=candidate.method or "non_parametric",
        gain_reduction_db=gain_reduction_db,
        residual_db=residual_db,
        residual_band_hz=residual_band_hz,
        commentary=commentary,
    )


def design(
    request: DesignRequest, params: PipelineParams | None = None
) -> DesignResponse:
    """designer-interface.md §1: one call, one title, one answer.

    `params` carries everything the wire request does not — device realisation, which
    strategies to run, authored exclusions — configured once at server start-up and applied to
    every request alike; see `tools/designer_server.py`. `request.bass_management`, when given,
    overrides `params.playback`'s crossover for this call only, and is the one thing that turns
    `gain_reduction_db` on (§2: "meaningful only together with `channels`" — and only when the
    caller told us the model, never approximated from `mono_mix` alone).

    Only `lpf_fs` of `bass_management` is honoured — `headroom_type` is a formula for callers
    without real per-channel audio to build the actual sub feed from, which this repo always
    has when `channels` is supplied; `lpf_position`/`clip_before`/`clip_after` have no
    equivalent in `PlaybackParams`' always-on mains+bus LR4 model. Not modelled, not guessed.
    """
    params = params or PipelineParams()

    material = Material(
        name="designer-request",
        fs=request.fs,
        mono_mix=np.asarray(request.mono_mix, dtype=np.float64),
        channels={
            name: np.asarray(samples, dtype=np.float64)
            for name, samples in (request.channels or {}).items()
        },
        coverage=request.coverage,
    )

    report_gain_reduction = request.bass_management is not None
    if report_gain_reduction:
        playback = dataclasses.replace(
            params.playback, crossover_hz=float(request.bass_management["lpf_fs"])
        )
        params = dataclasses.replace(params, playback=playback)

    report = run(material, params)

    accepted = report.accepted
    if accepted is None:
        if not report.candidates:
            reason, message = _decline_for_blockers(report.evidence_notes)
        else:
            reason, message = _decline_for_no_passing_candidate(report)
        return DesignResponse(
            contract_version=request.contract_version,
            decline_reason=reason,
            decline_message=message,
        )

    candidate = _to_design_candidate(
        accepted, params, report_gain_reduction=report_gain_reduction
    )
    return DesignResponse(
        contract_version=request.contract_version, candidates=[candidate]
    )


def _ndarray_from_json(d: dict) -> np.ndarray:
    if d.get("dtype") != _ARRAY_DTYPE:
        raise ValueError(
            f"unsupported array dtype {d.get('dtype')!r}, expected {_ARRAY_DTYPE!r}"
        )
    data = np.frombuffer(base64.b64decode(d["data_base64"]), dtype="<f8")
    return data.reshape(tuple(d["shape"]))


def _ndarray_to_json(arr: np.ndarray) -> dict:
    as_f64 = np.ascontiguousarray(arr, dtype="<f8")
    return {
        "dtype": _ARRAY_DTYPE,
        "shape": list(as_f64.shape),
        "data_base64": base64.b64encode(as_f64.tobytes()).decode("ascii"),
    }


def request_from_json(body: dict) -> DesignRequest:
    """designer-interface.md §7.1's request body, as POSTed by `http_designer(url)`."""
    channels = body.get("channels")
    return DesignRequest(
        contract_version=body["contract_version"],
        fs=int(body["fs"]),
        coverage=body["coverage"],
        mono_mix=_ndarray_from_json(body["mono_mix"]),
        channels=(
            {name: _ndarray_from_json(arr) for name, arr in channels.items()}
            if channels
            else None
        ),
        bass_management=body.get("bass_management"),
    )


def _candidate_to_json(c: DesignCandidate) -> dict:
    return {
        "filters": [dataclasses.asdict(f) for f in c.filters],
        "confidence": c.confidence,
        "mv_adjust_db": c.mv_adjust_db,
        "method": c.method,
        "gain_reduction_db": c.gain_reduction_db,
        "residual_db": c.residual_db,
        "residual_band_hz": (
            list(c.residual_band_hz) if c.residual_band_hz is not None else None
        ),
        "commentary": c.commentary,
        "fc_hz": c.fc_hz,
        "slope": c.slope,
        "fc_uncertainty_hz": c.fc_uncertainty_hz,
        "slope_uncertainty": c.slope_uncertainty,
        "channel_scope": c.channel_scope,
    }


def response_to_json(response: DesignResponse) -> dict:
    """designer-interface.md §7.1's response body."""
    if response.candidates is not None:
        return {
            "contract_version": response.contract_version,
            "candidates": [_candidate_to_json(c) for c in response.candidates],
        }
    return {
        "contract_version": response.contract_version,
        "decline_reason": response.decline_reason,
        "decline_message": response.decline_message,
    }
