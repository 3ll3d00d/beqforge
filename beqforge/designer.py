"""The `design(request) -> response` binding for beqdesigner's designer-interface.md v1.2.

Read that document (in the sibling `beqdesigner` repo, `design/designer-interface.md`) before
touching this file — it is the contract, not this module. In short: beqdesigner POSTs a
`DesignRequest` (raw audio, already decimated) and expects a `DesignResponse` back — either a
ranked, non-empty list of candidates or a decline, never both, never neither. `tools/
designer_server.py` is the HTTP transport (§7.1); this module is the pure adapter between that
wire format and `beqforge.pipeline.run`, kept separately testable without a socket.

1.1 adds `rejected`: every candidate the judge failed goes back beside the answer (or the
decline) with its failures as `rejection_reasons`, for a reviewer to see what was tried and why
it lost. It is a separate list rather than a flag on `candidates` so a 1.0 caller, which ignores
fields it does not know, can never publish one.

1.2 (HTTP binding only; beqdesigner's `design/designer-by-reference.md` §3) lets an array
arrive by reference — a WAV under a root both sides can see, with the SHA-256 of the decoded
column — instead of as base64. The data model does not change: `request_from_json` turns a
reference back into the same array (`beqforge.reference`), or refuses it naming the array.

1.4 says which answer a build gives, apart from which build it is: `design_version`
(`DESIGN_VERSION`), `design_settings` (a digest of the server-wide settings that can change an
answer, `design_settings_digest`) and `designer_build` (`record.revision()`), top-level on every
response whatever version the request names, and on `/health`. Two packagings of one release
report different builds but the same design version, so a caller can tell which titles a new
release would answer differently (`plans/design-version.md`).

1.5 lets a request carry `adjustments` -- a band to leave alone, a floor, a boost cap, a tilted goal, a note -- and
answers each in `adjustment_outcomes` (`beqforge.adjustments`, `plans/contract-1.5-adjustments.md`). They are applied to
this request's parameters only, after the settings digest (which describes the server, not the request); a request
without them is untouched, so its answer is the 1.4 answer.

1.6 (additive): `run_record` on every response names its run record relative to the shared root,
so a caller can hand it back to `POST /impact` without parsing commentary. Records are named per
request and design version and carry the identity themselves, so a redesign no longer
overwrites the last one. `/impact` itself is `beqforge.impact` (`plans/redesign-scope.md`).

The whole file exists because this repo already does the work the contract asks for — the
mapping is almost entirely "read the field off `Report`/`Candidate`/`Verdict` that already
means this", not new analysis. Where there is genuine judgement (declining, `gain_reduction_db`
only when the caller told us its playback model, capping `confidence` defensively) it is called
out inline.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from beqforge import BiquadSpec, explain, record
from beqforge.adjustments import (
    OUTCOMES,
    AdjustmentOutcome,
    DesignAdjustment,
    adjustments_from_json,
    apply_adjustments,
    finish_outcomes,
    outcome_to_json,
)
from beqforge.cache import Store
from beqforge.design import DesignMethod
from beqforge.material import Material, PlaybackParams
from beqforge.pipeline import Candidate, PipelineParams, Report, run
from beqforge.reference import array_from_reference

logger = logging.getLogger(__name__)

CONTRACT_VERSION = "1.6"
"""The version this module implements. Responses echo the request's own version instead."""

DESIGN_VERSION = 8
"""Which answer this code gives (1.4): bumped by any change that can alter `candidates`,
`rejected`, a decline or a 1.3 fit figure for an unchanged request and unchanged settings.

Not by wording (`commentary`, `decline_message`), speed, packaging, the server or the transport,
and not by a new output that leaves the existing ones as they were. An answer change is one
beyond `tests/test_design_golden.py`'s tolerance, not a last-digit difference between platforms.
That test fails on an answer changed without a bump, or a bump without regenerating its golden.
One version is one algorithm. From 6 the fit is meant to give one filter on every machine too
(TODO 28), measured so far only on this machine natively and as an emulated older CPU, so a
caller still compares versions, never figures.

Releases before this field: 0.0.x and 0.1.0 are 0 (before versioning), 0.2.0 is 1, 0.2.1 is 2,
0.2.2 is 3, and 0.2.3 to 0.2.5 are 4; 0.2.7, the first to report it, and 0.2.8 are 4 too.
0.2.9 is 5: it scores the fit on the published (rounded) parameters, fills mains-hum notches before
measuring the deficit, bounds the fit by the over-lift bar and refuses an infrasonic plateau as
the reference (TODO 29, released together, so one version). 0.2.10 is 6: it makes the fit
reproducible: identification converges to 1e-12 and the fit's target and ceiling are quantised
to 0.01 dB (TODO 28), builds the sub feed from the request's `bass_management` instead of
reading only its crossover, which moves `gain_reduction_db` (TODO 1), and keeps a passband whose
knee lands under 10 Hz as the reference (TODO 31). 0.2.11 is 6 too: it keeps the share within
tolerance in [0, 1] (a last-digit difference, not an answer change) and only renames run records
(TODO 35). 0.2.12 is 7: among the fits within the fitter's residual bar of its answer it keeps
the first the judge passes, fewest sections first, instead of whichever the arithmetic landed on
(TODO 32). 0.3.0 is 8: the fit's search scores a whole generation at once, in the linear
domain (TODO 23), which re-rolls the fit among near-equal optima as any change to its
arithmetic does. `plans/design-version.md` has each one's build."""

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
    adjustments: tuple[DesignAdjustment, ...] = ()
    """1.5: what the caller asks this design to change; () for none."""


_LPF_POSITIONS = ("Before", "After", "Off")


def playback_from_bass_management(
    bass_management: dict, channel_names: Iterable[str], base: PlaybackParams
) -> PlaybackParams:
    """§2's `bass_management` as the sub feed it describes.

    `lpf_fs` is the crossover. "Before" puts one LR4 on every channel, LFE included, and
    "After" one on their sum: the same linear feed, so both are the bus low-pass with no
    separate mains low-pass (`base`'s default low-passes the mains twice, at the crossover and
    on the bus). "Off" low-passes nothing; the crossover still names the band the sub plays.
    `headroom_type` sets the gains: "WCS" attenuates the mains by the coherent sum of every
    channel but the LFE plus the LFE at +10 dB, a number by its magnitude plus 10 dB, and the
    LFE by 10 dB less either way. `clip_before`/`clip_after` simulate a chain that clips; they
    are not modelled (`gain_reduction_db` is the reduction that keeps the feed from clipping at
    all), and the clipping commentary says so. A malformed field is a `ValueError`.
    """
    try:
        crossover = float(bass_management["lpf_fs"])
    except (KeyError, TypeError, ValueError) as bad:
        raise ValueError(f"bass_management.lpf_fs must be a number: {bad}") from bad
    position = bass_management.get("lpf_position", "Before")
    if position not in _LPF_POSITIONS:
        raise ValueError(
            f"bass_management.lpf_position must be one of {_LPF_POSITIONS}, got {position!r}"
        )
    headroom_type = bass_management.get("headroom_type", "WCS")
    if headroom_type == "WCS":
        mains = sum(1 for name in channel_names if name != "LFE")
        headroom_db = 20.0 * math.log10(mains + 10.0 ** (10.0 / 20.0))
    else:
        try:
            headroom_db = abs(float(headroom_type)) + 10.0
        except (TypeError, ValueError) as bad:
            raise ValueError(
                f"bass_management.headroom_type must be 'WCS' or a number in dB, "
                f"got {headroom_type!r}"
            ) from bad
        if not math.isfinite(headroom_db):
            raise ValueError("bass_management.headroom_type must be finite")
    return dataclasses.replace(
        base,
        crossover_hz=crossover,
        mains_lowpass_hz=None,
        sub_lowpass_hz=None if position == "Off" else "crossover",
        main_gain_db=-headroom_db,
        lfe_gain_db=10.0 - headroom_db,
    )


def unmodelled_bass_management(bass_management: dict | None) -> tuple[str, ...]:
    """The fields of §2's `bass_management` that ask for something the feed does not model."""
    return tuple(
        field
        for field in ("clip_before", "clip_after")
        if bass_management and bass_management.get(field)
    )


def _validate_audio_arrays(
    mono_mix: np.ndarray, channels: dict[str, np.ndarray] | None
) -> None:
    """Enforce the interface's shared, time-aligned 1-D audio-array contract."""
    arrays = [("mono_mix", mono_mix), *((channels or {}).items())]
    expected_length: int | None = None
    for name, samples in arrays:
        array = np.asarray(samples)
        if array.ndim != 1:
            raise ValueError(
                f"{name} must be a 1-D audio array, got shape {array.shape}"
            )
        if not np.all(np.isfinite(array)):
            raise ValueError(f"{name} must contain only finite samples")
        if name == "mono_mix":
            expected_length = len(array)
        elif len(array) != expected_length:
            raise ValueError(
                f"channel {name!r} has {len(array)} samples; "
                f"mono_mix has {expected_length}"
            )


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
    rejection_reasons: list[str] | None = None
    """1.1: non-empty on every entry of `DesignResponse.rejected`, None on every candidate."""
    residual_at_hz: float | None = None
    """1.3: where the error `residual_db` reports is, inside `residual_band_hz`."""
    residual_direction: Literal["over", "under"] | None = None
    """1.3: whether the cascade boosts more ("over") or less than the target there."""
    residual_rms_db: float | None = None
    """1.3: RMS error weighted by the target's requested boost; None when it requests none."""
    residual_within_tolerance: float | None = None
    """1.3: share of the requested boost within `residual_tolerance_db` of the target."""
    residual_tolerance_db: float | None = None


@dataclass(frozen=True, slots=True)
class DesignResponse:
    """designer-interface.md §3. Exactly one of `candidates`/`decline_reason` is populated.

    `rejected` (1.1) may accompany either: review only, never applied or published.
    """

    contract_version: str
    candidates: list[DesignCandidate] | None = None
    decline_reason: str | None = None
    decline_message: str | None = None
    rejected: list[DesignCandidate] | None = None
    design_version: int | None = None
    """1.4: `DESIGN_VERSION`, on a design and a decline alike."""
    design_settings: str | None = None
    """1.4: `design_settings_digest` of the settings this answer was designed with."""
    designer_build: str | None = None
    """1.4: `record.revision()`, the same string as the commentary's `beqforge_revision`."""
    adjustment_outcomes: list[AdjustmentOutcome] | None = None
    """1.5: one per request adjustment, on a design and a decline alike; None when none were asked."""
    run_record: str | None = None
    """1.6: this answer's run record, POSIX and relative to the shared root, so a caller can hand
    it back to `/impact` unchanged; None without a shared root, a record, or one inside the root."""


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
    ("nothing worth correcting", "within_goal_tolerance"),
    ("within the programme's own ripple", "within_programme_ripple"),
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
    candidate: Candidate,
    params: PipelineParams,
    *,
    report_gain_reduction: bool,
    run_notes: tuple[str, ...] = (),
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

    # what plays against what it was asked for (TODO 14), not the fitter's objective
    # `fit_error_db`, which mixes in quantisation change and was reported against a band
    # narrower than the one `_fit_all` scored
    fit = candidate.target_fit
    if fit is not None and not math.isfinite(fit.max_error_db):
        fit = None
    weighted = fit is not None and math.isfinite(fit.rms_db)

    commentary = {"strategy": candidate.label}
    if candidate.effective_params:
        commentary["effective_params"] = candidate.effective_params
    # the response has no field for run-level notes, so the candidate carries them: what bound
    # its own target first, then the run's limitations
    notes = tuple(dict.fromkeys((*candidate.target_notes, *run_notes)))
    if notes:
        commentary["target_notes"] = "; ".join(notes)
    # what the judge itself noticed — above all how much of the correction sits below the
    # level-invariance floor (E6). A reviewer reading only the response had
    # the fraction as a bare number and never saw the sentence saying what it means
    if candidate.verdict.notes:
        commentary["verdict_notes"] = "; ".join(dict.fromkeys(candidate.verdict.notes))
    # recovered_fraction and shaping_fraction are deliberately not here as bare numbers: read
    # out of context they mean nothing to a reviewer. `explain.correction` says both in words,
    # and the run record keeps the numbers.

    return DesignCandidate(
        filters=list(candidate.filters),
        confidence=confidence,
        mv_adjust_db=candidate.mv_adjust_db,
        method=candidate.method or "non_parametric",
        gain_reduction_db=gain_reduction_db,
        residual_db=None if fit is None else fit.max_error_db,
        residual_band_hz=None if fit is None else fit.band_hz,
        commentary=commentary,
        residual_at_hz=None if fit is None else fit.at_hz,
        residual_direction=None if fit is None else ("over" if fit.over else "under"),
        residual_rms_db=fit.rms_db if weighted else None,
        residual_within_tolerance=fit.within_tolerance if weighted else None,
        residual_tolerance_db=fit.tolerance_db if weighted else None,
    )


def design_settings_detail(params: PipelineParams) -> dict[str, object]:
    """The server-wide settings that can change an answer and differ from their default.

    Exactly what `serve-designer` can set: strategies (in order: the order candidates are built
    in is the order `rejected` and exact ranking ties fall in), exclusions (sorted), the goal's
    tolerance and tilt, judging from the content edge, and the device's rate and coefficient
    format. Workers, cores, the cache, records and the shared root change no answer and are not
    here. A setting at its default is left out, so a flag added later whose default keeps
    today's behaviour moves no server's digest; changing a default that alters answers is a
    `DESIGN_VERSION` bump anyway.
    """

    def settings(p: PipelineParams) -> dict[str, object]:
        return {
            "strategies": list(p.strategies),
            "exclude_bands_hz": sorted(
                [float(low), float(high)] for low, high in p.exclude_bands_hz
            ),
            "goal_tolerance_db": float(p.accept.goal_tolerance_db),
            "goal_tilt_db_per_octave": float(p.accept.target_tilt_db_per_octave),
            "content_edge": bool(p.judge_from_content_edge),
            "device_rate_hz": float(p.realisation.fs),
            "coefficient_bits": int(p.realisation.coefficient_bits),
            "integer_bits": int(p.realisation.integer_bits),
        }

    defaults = settings(PipelineParams())
    return {k: v for k, v in settings(params).items() if v != defaults[k]}


def design_settings_digest(params: PipelineParams) -> str:
    """`design_settings_detail` in canonical JSON (sorted keys, no spaces, floats as Python's
    shortest round-trip form), SHA-256, first 12 hex. All defaults digests the empty set."""
    canonical = json.dumps(
        design_settings_detail(params), sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(b"design-settings-v1\0")
    digest.update(canonical.encode("utf-8"))
    return digest.hexdigest()[:12]


def _request_digest(request: DesignRequest, settings: str) -> str:
    """Everything beside the audio that can change the answer: coverage, the playback chain, the
    adjustments (order and the caller's ids carry no meaning, §2) and the server's settings."""
    asked = sorted(
        json.dumps([a.kind, a.params, a.text], sort_keys=True)
        for a in request.adjustments or ()
    )
    body = json.dumps(
        {
            "coverage": request.coverage,
            "bass_management": request.bass_management,
            "adjustments": asked,
            "design_settings": settings,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()


def _provenance(
    report: Report,
    params: PipelineParams,
    material: Material,
    record_dir: Path | None,
    request: DesignRequest,
    settings: str,
) -> tuple[dict[str, str], Path | None]:
    """Which build answered, and where its run record went — so a response can be replayed.

    A response carries only the accepted candidate (or a decline) and nothing about the code,
    so a review queue built from responses cannot say which build made an entry or why the
    other candidates lost. The record is named by the request audio's digest, the rest of the
    request's (`_request_digest`) and the design version: the same request at the same version
    writes the same file, and it replays with `tools/replay.py` (charts from the mix only; the
    material itself never touched disk). It was the audio's digest alone, so a library's
    redesign at a new version overwrote every record of the old one (TODO 35), and a request
    with adjustments overwrote the plain one. A failed write is logged and reported in the
    provenance, never raised — the design is the product, the record is a receipt.
    """
    provenance = {"beqforge_revision": record.revision()}
    if record_dir is None:
        return provenance, None
    digest = record.array_digest(material)
    rest = _request_digest(request, settings)
    path = (
        Path(record_dir)
        / f"designer-{digest[:16]}-{rest[:8]}-v{DESIGN_VERSION}.run.json.gz"
    )
    try:
        curves = record.curves_from(
            material,
            {c.label: c.filters for c in report.candidates},
            (),
            params.realisation,
        )
        record.write(
            path,
            report,
            params,
            None,
            curves,
            material_sha256=digest,
            identity={"design_version": DESIGN_VERSION, "design_settings": settings},
        )
        provenance["run_record"] = str(path)
    except (OSError, ValueError) as failed:
        logger.warning(f"run record not written to {path}: {failed}")
        provenance["run_record"] = f"not written: {failed}"
        return provenance, None
    return provenance, path


def _under_root(path: Path | None, shared_root: Path | None) -> str | None:
    """1.6's `run_record`: `path` relative to `shared_root`, POSIX, or None when it lies outside."""
    if path is None or shared_root is None:
        return None
    try:
        return path.resolve().relative_to(shared_root.resolve()).as_posix()
    except ValueError:
        return None


def design(
    request: DesignRequest,
    params: PipelineParams | None = None,
    *,
    record_dir: Path | None = None,
    cache: Store | None = None,
    shared_root: Path | None = None,
) -> DesignResponse:
    """designer-interface.md §1: one call, one title, one answer.

    `params` carries everything the wire request does not — device realisation, which
    strategies to run, authored exclusions — configured once at server start-up and applied to
    every request alike; see `tools/designer_server.py`. `request.bass_management`, when given,
    overrides `params.playback`'s crossover for this call only, and is the one thing that turns
    `gain_reduction_db` on (§2: "meaningful only together with `channels`" — and only when the
    caller told us the model, never approximated from `mono_mix` alone).

    The sub feed is built as `bass_management` describes it (`playback_from_bass_management`):
    the crossover, where the low-pass sits and the gains `headroom_type` names. That feed is
    what verification, counterfactual summation and the clipping figure read, so the caller's
    chain can change the answer. Clipping simulation (`clip_before`/`clip_after`) is not
    modelled, and the clipping commentary says so rather than claiming it.

    Every response says which build produced it (`beqforge_revision` in the accepted
    candidate's commentary, or a trailing bracket on a decline message); with `record_dir`,
    the full run record is written there too and named the same way — see `_provenance`.

    With `cache`, every stage whose key has not moved is reused from it — the analysis for any
    request carrying the same samples, the parametric proposal while the server's settings are
    unchanged (R2a). Nothing about the answer depends on it.
    """
    params = params or PipelineParams()
    settings = design_settings_digest(params)
    # 1.5: this request's own changes, after the digest -- which describes the server, not the request
    asked = tuple(request.adjustments or ())
    provisional: dict[str, AdjustmentOutcome] = {}
    if asked:
        params, provisional = apply_adjustments(params, asked)

    _validate_audio_arrays(request.mono_mix, request.channels)

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
        playback = playback_from_bass_management(
            request.bass_management, material.channels, params.playback
        )
        params = dataclasses.replace(params, playback=playback)

    report = run(material, params, cache_path=cache)
    provenance, written = _provenance(
        report, params, material, record_dir, request, settings
    )
    run_record = _under_root(written, shared_root)

    unmodelled = unmodelled_bass_management(request.bass_management)
    rejected = _rejected(report, params, report_gain_reduction, unmodelled)
    outcomes = finish_outcomes(provisional, asked, report, params) if asked else None
    accepted = report.accepted
    if accepted is None:
        if not report.candidates:
            # the blockers alone when the report has them: the reason, not every caveat
            reason, message = _decline_for_blockers(
                report.blockers or report.evidence_notes
            )
        else:
            reason, message = _decline_for_no_passing_candidate(report)
        stamp = "; ".join(f"{k}: {v}" for k, v in provenance.items())
        return DesignResponse(
            contract_version=request.contract_version,
            decline_reason=reason,
            decline_message=f"{message} | found: {explain.found(report)} [{stamp}]",
            rejected=rejected,
            design_version=DESIGN_VERSION,
            design_settings=settings,
            designer_build=provenance["beqforge_revision"],
            adjustment_outcomes=outcomes,
            run_record=run_record,
        )

    candidate = _to_design_candidate(
        accepted,
        params,
        report_gain_reduction=report_gain_reduction,
        run_notes=report.evidence_notes,
    )
    # the plain-language account first, so a reader of the response meets the basis for the
    # correction before the notes and parameters that qualify it
    account = {
        "found": explain.found(report),
        "correction": explain.correction(accepted, report),
        "clipping": explain.clipping(
            accepted,
            from_request=report_gain_reduction,
            unmodelled=unmodelled,
        ),
        "fit": explain.fit(accepted),
        "alternatives": explain.alternatives(report, accepted),
    }
    candidate = dataclasses.replace(
        candidate, commentary={**account, **(candidate.commentary or {}), **provenance}
    )
    return DesignResponse(
        contract_version=request.contract_version,
        candidates=[candidate],
        rejected=rejected,
        design_version=DESIGN_VERSION,
        design_settings=settings,
        designer_build=provenance["beqforge_revision"],
        adjustment_outcomes=outcomes,
        run_record=run_record,
    )


def _rejected(
    report: Report,
    params: PipelineParams,
    report_gain_reduction: bool,
    unmodelled: tuple[str, ...] = (),
) -> list[DesignCandidate] | None:
    """Every candidate the judge failed, nearest to acceptable first (fewest failures).

    A candidate that passed but lost selection is not here: it was not rejected, and
    `alternatives` already says why it lost. Nor is one with no sections, which a reviewer
    could not load (§5). Each carries the same plain-language account as an accepted one, so
    what the filter would have done can be read beside why it was refused. None when empty —
    the contract rejects an empty list.
    """
    failed = [
        c
        for c in report.candidates
        if not c.verdict.passed and c.filters and any(c.verdict.failures)
    ]
    entries = [
        dataclasses.replace(
            (
                mapped := _to_design_candidate(
                    c, params, report_gain_reduction=report_gain_reduction
                )
            ),
            commentary={
                "correction": explain.correction(c, report),
                "clipping": explain.clipping(
                    c,
                    from_request=report_gain_reduction,
                    unmodelled=unmodelled,
                ),
                "fit": explain.fit(c),
                **(mapped.commentary or {}),
            },
            rejection_reasons=[f for f in c.verdict.failures if f],
        )
        for c in sorted(failed, key=lambda c: len(c.verdict.failures))
    ]
    return entries or None


def _ndarray_from_json(
    d: dict,
    name: str = "array",
    shared_root: Path | None = None,
    fs: int = 0,
    opened: dict | None = None,
) -> np.ndarray:
    """One array, inline (`data_base64`) or, from 1.2, by reference (`file` + `sha256`).

    Exactly one of the two. A body that breaks that, or a `file` without its `sha256`, is
    malformed (`ValueError`, 400); a well-formed reference that cannot be honoured raises
    `UnusableReference` (422) from `beqforge.reference`.
    """
    if d.get("dtype") != _ARRAY_DTYPE:
        raise ValueError(
            f"unsupported array dtype {d.get('dtype')!r}, expected {_ARRAY_DTYPE!r}"
        )
    inline, by_reference = "data_base64" in d, "file" in d
    if inline == by_reference:
        raise ValueError(f"{name} needs exactly one of data_base64 or file")
    if by_reference:
        if not isinstance(d["file"], dict) or not d.get("sha256"):
            raise ValueError(f"{name}: a file reference needs file.path and sha256")
        return array_from_reference(name, d, shared_root, fs, opened)
    data = np.frombuffer(base64.b64decode(d["data_base64"]), dtype="<f8")
    return data.reshape(tuple(d["shape"]))


def _ndarray_to_json(arr: np.ndarray) -> dict:
    as_f64 = np.ascontiguousarray(arr, dtype="<f8")
    return {
        "dtype": _ARRAY_DTYPE,
        "shape": list(as_f64.shape),
        "data_base64": base64.b64encode(as_f64.tobytes()).decode("ascii"),
    }


def request_from_json(body: dict, shared_root: Path | None = None) -> DesignRequest:
    """designer-interface.md §7.1's request body, as POSTed by `http_designer(url)`.

    `shared_root` is where this server finds audio sent by reference (1.2); without one, a
    `file` array is refused with `UnusableReference`. The material the arrays become is named
    "designer-request" either way, so a request by reference and the same request inline give
    the same cache key and the same record.
    """
    channels = body.get("channels")
    fs = int(body["fs"])
    opened: dict = {}
    request = DesignRequest(
        contract_version=body["contract_version"],
        fs=fs,
        coverage=body["coverage"],
        mono_mix=_ndarray_from_json(
            body["mono_mix"], "mono_mix", shared_root, fs, opened
        ),
        channels=(
            {
                name: _ndarray_from_json(arr, name, shared_root, fs, opened)
                for name, arr in channels.items()
            }
            if channels
            else None
        ),
        bass_management=body.get("bass_management"),
        adjustments=adjustments_from_json(body.get("adjustments")),
    )
    _validate_audio_arrays(request.mono_mix, request.channels)
    if request.bass_management is not None:
        if not isinstance(request.bass_management, dict):
            raise ValueError("bass_management must be an object or null")
        playback_from_bass_management(
            request.bass_management, request.channels or {}, PlaybackParams()
        )
    return request


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
        # 1.1, and only where it means something, so a 1.0 response is unchanged on the wire
        **(
            {"rejection_reasons": list(c.rejection_reasons)}
            if c.rejection_reasons is not None
            else {}
        ),
        # 1.3, likewise only where measured
        **{
            name: getattr(c, name)
            for name in _FIT_FIELDS
            if getattr(c, name) is not None
        },
    }


_FIT_FIELDS = (
    "residual_at_hz",
    "residual_direction",
    "residual_rms_db",
    "residual_within_tolerance",
    "residual_tolerance_db",
)
"""1.3's companions to `residual_db`, in wire order."""


def response_to_json(response: DesignResponse) -> dict:
    """designer-interface.md §7.1's response body; `rejected` only when there are any, and
    1.4's design version, settings and build only when set."""
    if response.candidates is not None:
        body = {
            "contract_version": response.contract_version,
            "candidates": [_candidate_to_json(c) for c in response.candidates],
        }
    else:
        body = {
            "contract_version": response.contract_version,
            "decline_reason": response.decline_reason,
            "decline_message": response.decline_message,
        }
    if response.rejected is not None:
        body["rejected"] = [_candidate_to_json(c) for c in response.rejected]
    for name in _IDENTITY_FIELDS:
        if getattr(response, name) is not None:
            body[name] = getattr(response, name)
    if response.adjustment_outcomes is not None:
        body["adjustment_outcomes"] = [
            outcome_to_json(o) for o in response.adjustment_outcomes
        ]
    if response.run_record is not None:
        body["run_record"] = response.run_record
    return body


_IDENTITY_FIELDS = ("design_version", "design_settings", "designer_build")
"""1.4's top-level fields, in wire order."""


_ALLOWED_BIQUAD_TYPES = {"peaking_eq", "low_shelf", "high_shelf"}
_MAX_BIQUAD_SECTIONS = 10


class ContractViolation(ValueError):
    """A `DesignResponse` that violates designer-interface.md §3-§5.

    Mirrors beqdesigner's own `pipeline.designer.convert.validate_response` — that module
    can't be imported from here (PyQt6, a separate repo/venv; AGENTS.md), so this is an
    independent re-implementation of the same rules, checked against the same document. Called
    by `tools/designer_server.py` before a response ever goes on the wire: a violation here is
    this module's own mapping bug, never the caller's to see, per "never trust a residual"
    applied to this boundary — a response that merely *looks* right is not enough.
    """


def validate_response(response: DesignResponse) -> None:
    """:raises ContractViolation: if `response` violates the contract."""
    is_decline = response.decline_reason is not None
    is_success = response.candidates is not None
    if is_success and is_decline:
        raise ContractViolation(
            "DesignResponse populates both candidates and decline_reason"
        )
    if not is_success and not is_decline:
        raise ContractViolation(
            "DesignResponse populates neither candidates nor decline_reason"
        )

    _validate_rejected(response.rejected)
    _validate_identity(response)
    _validate_outcomes(response.adjustment_outcomes)

    if is_decline:
        if not isinstance(response.decline_reason, str) or not response.decline_reason:
            raise ContractViolation("decline_reason must be a non-empty string")
        return

    if len(response.candidates) == 0:
        raise ContractViolation("success response has an empty candidates list")

    previous_confidence = None
    for i, candidate in enumerate(response.candidates):
        _validate_candidate(candidate, i)
        if candidate.rejection_reasons is not None:
            raise ContractViolation(
                f"candidates[{i}] carries rejection_reasons — a rejected design belongs in "
                "rejected, never in candidates"
            )
        if (
            previous_confidence is not None
            and candidate.confidence > previous_confidence
        ):
            raise ContractViolation(
                f"candidates[{i}].confidence ({candidate.confidence}) exceeds "
                f"candidates[{i - 1}]'s ({previous_confidence}) — not ordered best-first"
            )
        previous_confidence = candidate.confidence


def _validate_outcomes(outcomes: list[AdjustmentOutcome] | None) -> None:
    """1.5 (§3): each outcome known, each id once; `adapted` says what was applied and why, `declined` and
    `not_understood` why, and apply nothing. (That each answers an adjustment the request sent is the caller's check:
    the response alone does not know the request.)"""
    if outcomes is None:
        return
    seen: set[str] = set()
    for i, o in enumerate(outcomes):
        name = f"adjustment_outcomes[{i}]"
        if not o.id or o.id in seen:
            raise ContractViolation(f"{name} has no id, or one already answered")
        seen.add(o.id)
        if o.outcome not in OUTCOMES:
            raise ContractViolation(
                f"{name}.outcome {o.outcome!r} is not one of {OUTCOMES}"
            )
        if o.outcome != "honoured" and not o.reason:
            raise ContractViolation(f"{name} is {o.outcome}, so it must say why")
        if o.outcome == "adapted" and not isinstance(o.applied, dict):
            raise ContractViolation(
                f"{name} is adapted, so it must say what was applied"
            )
        if o.outcome in ("declined", "not_understood") and o.applied is not None:
            raise ContractViolation(f"{name} is {o.outcome}, so nothing was applied")


def _validate_identity(response: DesignResponse) -> None:
    """1.4: each of design_version, design_settings and designer_build absent or well formed."""
    version = response.design_version
    if version is not None and (
        isinstance(version, bool) or not isinstance(version, int) or version < 0
    ):
        raise ContractViolation(
            f"design_version must be a non-negative integer, got {version!r}"
        )
    for name in ("design_settings", "designer_build"):
        value = getattr(response, name)
        if value is not None and (not isinstance(value, str) or not value):
            raise ContractViolation(f"{name} must be a non-empty string, got {value!r}")
    path = response.run_record
    if path is not None and (
        not isinstance(path, str)
        or not path
        or "\\" in path
        or path.startswith("/")
        or ".." in path.split("/")
    ):
        # 1.6: the caller hands it back to /impact, under 1.2's rules for a path by reference
        raise ContractViolation(
            f"run_record must be a relative POSIX path under the shared root, got {path!r}"
        )


def _validate_rejected(rejected: list[DesignCandidate] | None) -> None:
    """1.1: None or non-empty; every entry a valid candidate with reasons. No ordering rule."""
    if rejected is None:
        return
    if len(rejected) == 0:
        raise ContractViolation("rejected is an empty list — omit it instead")
    for i, entry in enumerate(rejected):
        _validate_candidate(entry, i, "rejected")
        reasons = entry.rejection_reasons
        if (
            not isinstance(reasons, list)
            or not reasons
            or not all(isinstance(r, str) and r for r in reasons)
        ):
            raise ContractViolation(
                f"rejected[{i}].rejection_reasons must be a non-empty list of non-empty "
                f"strings, got {reasons!r}"
            )


def _validate_candidate(
    candidate: DesignCandidate, index: int, where: str = "candidates"
) -> None:
    if candidate.confidence is None or not (0.0 <= candidate.confidence <= 1.0):
        raise ContractViolation(
            f"{where}[{index}].confidence must be in [0.0, 1.0], got {candidate.confidence}"
        )
    if candidate.mv_adjust_db is None or not math.isfinite(candidate.mv_adjust_db):
        raise ContractViolation(
            f"{where}[{index}].mv_adjust_db must be a finite number, got {candidate.mv_adjust_db}"
        )
    if candidate.gain_reduction_db is not None and (
        not math.isfinite(candidate.gain_reduction_db)
        or candidate.gain_reduction_db > 0
    ):
        raise ContractViolation(
            f"{where}[{index}].gain_reduction_db must be finite and <= 0, "
            f"got {candidate.gain_reduction_db}"
        )
    if not candidate.filters:
        raise ContractViolation(f"{where}[{index}] has an empty filters list")
    if len(candidate.filters) > _MAX_BIQUAD_SECTIONS:
        raise ContractViolation(
            f"{where}[{index}]: {len(candidate.filters)} sections exceeds the budget of "
            f"{_MAX_BIQUAD_SECTIONS}"
        )
    for i, spec in enumerate(candidate.filters):
        _validate_biquad_spec(spec, i, index, where)
    _validate_fit(candidate, f"{where}[{index}]")
    if candidate.commentary is not None:
        if not isinstance(candidate.commentary, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in candidate.commentary.items()
        ):
            raise ContractViolation(
                f"{where}[{index}].commentary must be a dict[str, str]"
            )


def _validate_fit(candidate: DesignCandidate, prefix: str) -> None:
    """1.3: `residual_db`'s companions are present only with it, and consistent with it."""
    present = {name: getattr(candidate, name) for name in _FIT_FIELDS}
    for name, value in present.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractViolation(f"{prefix}.{name} must be finite, got {value}")
    residual = candidate.residual_db
    if residual is None:
        orphans = [name for name, value in present.items() if value is not None]
        if orphans:
            raise ContractViolation(
                f"{prefix} has {', '.join(orphans)} without residual_db"
            )
        return
    if (candidate.residual_at_hz is None) != (candidate.residual_direction is None):
        raise ContractViolation(
            f"{prefix}.residual_at_hz and residual_direction come together or not at all"
        )
    if candidate.residual_direction not in (None, "over", "under"):
        raise ContractViolation(
            f"{prefix}.residual_direction must be 'over' or 'under', "
            f"got {candidate.residual_direction!r}"
        )
    band = candidate.residual_band_hz
    at = candidate.residual_at_hz
    if at is not None and band is not None and not band[0] <= at <= band[1]:
        raise ContractViolation(
            f"{prefix}.residual_at_hz {at} is outside residual_band_hz {band}"
        )
    rms = candidate.residual_rms_db
    if (rms is None) != (candidate.residual_within_tolerance is None):
        raise ContractViolation(
            f"{prefix}.residual_rms_db and residual_within_tolerance share one weighting, so "
            "come together or not at all"
        )
    if rms is not None and not 0.0 <= rms <= residual + 1e-9:
        raise ContractViolation(
            f"{prefix}.residual_rms_db {rms} must be in [0, residual_db {residual}]"
        )
    within = candidate.residual_within_tolerance
    tolerance = candidate.residual_tolerance_db
    if (within is None) != (tolerance is None):
        raise ContractViolation(
            f"{prefix}.residual_within_tolerance and residual_tolerance_db come together "
            "or not at all"
        )
    if within is not None and not 0.0 <= within <= 1.0:
        raise ContractViolation(
            f"{prefix}.residual_within_tolerance must be in [0, 1], got {within}"
        )
    if tolerance is not None and tolerance <= 0:
        raise ContractViolation(
            f"{prefix}.residual_tolerance_db must be > 0, got {tolerance}"
        )


def _validate_biquad_spec(
    spec: BiquadSpec, index: int, candidate_index: int, where: str = "candidates"
) -> None:
    prefix = f"{where}[{candidate_index}].filters[{index}]"
    if spec.type not in _ALLOWED_BIQUAD_TYPES:
        raise ContractViolation(f"{prefix}.type {spec.type!r} is not publishable")
    if not math.isfinite(spec.freq_hz) or spec.freq_hz <= 0:
        raise ContractViolation(f"{prefix}.freq_hz must be > 0, got {spec.freq_hz}")
    if not math.isfinite(spec.gain_db):
        raise ContractViolation(f"{prefix}.gain_db must be finite, got {spec.gain_db}")
    if not math.isfinite(spec.q) or spec.q <= 0:
        raise ContractViolation(f"{prefix}.q must be > 0, got {spec.q}")
