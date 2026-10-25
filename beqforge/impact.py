"""Which designs a designer upgrade may move (TODO 34; designer-interface.md 1.6 §7.1, "Impact").

A design version is one number per build, so every bump flags the whole library as out of date
though most changes reach a few titles. This answers, per run record, how likely a design of the
same request by this build is to differ from the one the record holds, and why, so a person can
choose what to redesign. See `plans/redesign-scope.md`.

The pipeline is a fixed catalogue of named features (`FEATURES`). Each owns the code that
implements it (`Feature.owns`, matched against `module:qualname`) and reads from a run record how
a design relied on it (`Feature.reader`). Each answer-changing design version says, in
`impact.toml`, which features it changed and how (`Touch`); `tools/impact.py check` refuses a
commit range whose changed code belongs to a feature its new versions don't declare, or to no
feature at all. A record is scored against every change after the version it was designed at.

Nothing here designs anything, and nothing is decided by it: the answer is advisory.
"""

import ast
import fnmatch
import gzip
import json
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

IMPACT_FILE = Path(__file__).with_name("impact.toml")

MAX_RECORDS = 500
"""Per `/impact` request (§7.1)."""

LIKELY = 0.5
"""A measured share at or above this is `likely`; anything above zero is `possible`."""

OUTCOMES = (
    "no_fit",
    "declined_after_fit",
    "designed_with_failures",
    "designed_all_passed",
)
"""How a record's design came out, the classes a behaviour change's degree is measured over:
declined before any fit (in analysis, or with no target worth proposing), declined with every
fitted candidate failing, designed with some candidate failing, and designed with all passing."""

Tier = Literal["will_move", "likely", "possible", "unaffected", "unknown"]


@dataclass(frozen=True, slots=True)
class Reliance:
    """How one record's design relied on one feature."""

    kind: str
    """The class a change's degree is looked up by: one of `OUTCOMES`."""
    detail: str
    """For a person: what in the record put it here."""
    value: float | None = None
    """The recorded figure a threshold compares, in the threshold's units; None when the record
    does not hold it, and then a threshold change cannot be scored."""


Reader = Callable[[dict], Reliance | None]


@dataclass(frozen=True, slots=True)
class Feature:
    id: str
    summary: str
    owns: tuple[str, ...]
    """`module:qualname` globs, the module dotted from the repository root's packages
    (`pipeline`, `beq_common.biquad`); see `owners`."""
    reader: Reader | None = None
    """None for a feature that changes no answer."""

    @property
    def answers(self) -> bool:
        return self.reader is not None


def outcome(record: dict) -> str:
    candidates = record.get("candidates") or []
    if not candidates:
        return "no_fit"
    if record.get("accepted") is None:
        return "declined_after_fit"
    if any(not (c.get("verdict") or {}).get("passed") for c in candidates):
        return "designed_with_failures"
    return "designed_all_passed"


_DESCRIBED = {
    "no_fit": "declined before any fit",
    "declined_after_fit": "declined: every fitted candidate failed",
    "designed_with_failures": "designed, with some candidate failing",
    "designed_all_passed": "designed, every candidate passing",
}


def _every(record: dict) -> Reliance:
    """Every design relies on it, declined or not."""
    kind = outcome(record)
    return Reliance(kind, _DESCRIBED[kind])


def _fitted(record: dict) -> Reliance | None:
    """Every design that reached the fit relies on it; one declined before it does not."""
    kind = outcome(record)
    return None if kind == "no_fit" else Reliance(kind, _DESCRIBED[kind])


def _strategy(prefix: str) -> Reader:
    def read(record: dict) -> Reliance | None:
        mine = [
            c
            for c in record.get("candidates") or []
            if str(c.get("label", "")).startswith(prefix)
        ]
        if not mine:
            return None
        kind = outcome(record)
        won = record.get("accepted")
        states = ", ".join(
            f"{c['label']} "
            + (
                "won"
                if c["label"] == won
                else "passed"
                if (c.get("verdict") or {}).get("passed")
                else "failed"
            )
            for c in mine
        )
        return Reliance(kind, f"{_DESCRIBED[kind]}; {states}")

    return read


def _check(*starts: str) -> Reader:
    """A judge check: every fitted candidate was put through it; say where it failed one."""

    def read(record: dict) -> Reliance | None:
        found = _fitted(record)
        if found is None:
            return None
        failed = [
            c["label"]
            for c in record.get("candidates") or []
            if any(
                str(f).startswith(starts)
                for f in (c.get("verdict") or {}).get("failures") or ()
            )
        ]
        if failed:
            return replace(
                found, detail=f"{found.detail}; failed it: {', '.join(failed)}"
            )
        return found

    return read


FEATURES: tuple[Feature, ...] = (
    # -- analysis: what the material says, before any target
    Feature(
        "analysis.input",
        "the material as decoded and summed: arrays, channels and bass management",
        (
            "material:*",
            "reference:*",
            "designer:request_from_json",
            "designer:_ndarray_from_json",
            "designer:_validate_audio_arrays",
            "designer:playback_from_bass_management",
            "designer:unmodelled_bass_management",
            "designer:_ARRAY_DTYPE",
            "designer:_LPF_POSITIONS",
            "designer:DesignRequest*",
            "designer:Coverage",
            "designer:ChannelScope",
            "pipeline:PipelineParams.playback",
            "pipeline:PipelineParams.exclude_bands_hz",
        ),
        _every,
    ),
    Feature(
        "analysis.extraction",
        "loud and quiet frames, their envelopes and the evidence they carry",
        ("extraction:*", "pipeline:PipelineParams.extraction"),
        _every,
    ),
    Feature(
        "analysis.diagnosis",
        "the reference plateau, the floors, tracking and filtered detection",
        ("diagnose:*", "pipeline:PipelineParams.diagnose"),
        _every,
    ),
    Feature(
        "analysis.identification",
        "the rolloff model and its identification",
        ("identify:*", "rolloff:*", "pipeline:PipelineParams.identify"),
        _every,
    ),
    Feature(
        "analysis.blockers",
        "what declines a title before any target: evidence notes and channel checks",
        (
            "pipeline:analyse",
            "pipeline:Analysed*",
            "pipeline:evidence_notes",
            "pipeline:correction_evidence_score",
            "pipeline:channels_missing_low_end",
            "dc_offset:*",
        ),
        _every,
    ),
    # -- targets
    Feature(
        "targets.shared",
        "what every target shares: evidence pricing, hum notches, the judged band and ceiling",
        (
            "pipeline:propose",
            "pipeline:Proposal*",
            "pipeline:Strategy*",
            "pipeline:cached_module_sets",
            "pipeline:_usable",
            "pipeline:priced_by_evidence",
            "pipeline:_held_below_floor",
            "pipeline:_worth_correcting",
            "pipeline:mains_hum_notches",
            "pipeline:hum_notches",
            "pipeline:fill_hum_notches",
            "pipeline:passband_ripple_db",
            "pipeline:MAINS_HZ",
            "pipeline:HUM_*",
            "pipeline:MIX_TEXTURE_TREND_DEGREE",
            "pipeline:STRATEGIES",
            "pipeline:contrast_ceiling_db",
            "pipeline:content_edge_hz",
            "pipeline:judged_band_hz",
            "pipeline:_judged_top_hz",
            "pipeline:evidence_excess",
            "pipeline:EvidenceExcess*",
            "pipeline:PipelineParams.strategies",
            "pipeline:PipelineParams.max_target_boost_db",
            "pipeline:PipelineParams.lowest_frequency_hz",
            "pipeline:PipelineParams.confidence_z",
        ),
        _every,
    ),
    Feature(
        "targets.flatten",
        "the flatten target",
        (
            "pipeline:flatten_targets",
            "pipeline:_flat_deficit",
            "pipeline:low_end_deficit_db",
            "pipeline:_deficit_anchor",
            "pipeline:_taper",
            "pipeline:PipelineParams.flatten_*",
        ),
        _strategy("flatten"),
    ),
    Feature(
        "targets.counterfactual",
        "the counterfactual targets",
        (
            "pipeline:counterfactual_target",
            "pipeline:counterfactual_targets",
            "pipeline:_Restoration*",
            "pipeline:_restoration_mix",
            "pipeline:PipelineParams.restore_caps_db",
        ),
        _strategy("counterfactual"),
    ),
    Feature(
        "targets.parametric",
        "the parametric target and its alignment",
        (
            "design:*",
            "pipeline:parametric_params",
            "pipeline:parametric_derivation",
            "pipeline:parametric_targets",
            "pipeline:ParametricDerivation*",
            "pipeline:PipelineParams.parametric_max_boost_db",
        ),
        _strategy("parametric"),
    ),
    # -- the fit
    Feature(
        "fit.input",
        "what the fitter is asked: the target, ceiling and band, quantised (row 28)",
        (
            "filters:FitRequest*",
            "filters:_quantised",
            "filters:_reproducible",
            "filters:FIT_INPUT_STEP_DB",
            "filters:correction_band_hz",
            "filters:WIDEN_OCTAVES",
            "filters:Ceiling*",
            "pipeline:_fit_all",
            "pipeline:_placements",
            "pipeline:_fit_band_hz",
            "pipeline:overlift_allowance",
        ),
        _fitted,
    ),
    Feature(
        "fit.search",
        "the optimiser: structures, starts, pruning and the residual it minimises",
        (
            "filters:_fit_structure*",
            "filters:_run_fits",
            "filters:_fit_pool",
            "filters:_fit_task",
            "filters:_structure_tasks",
            "filters:_physical_cores",
            "filters:_windows_physical_cores",
            "filters:_macos_physical_cores",
            "filters:FIT_WORKERS",
            "filters:_tiers",
            "filters:_by_owner",
            "filters:_prune",
            "filters:_contribution",
            "filters:fit_to_biquads",
            "filters:invert_to_shelves",
            "filters:inversion_target_db",
            "filters:residual_db",
            "filters:_published_parameters",
            "filters:_unpack",
            "filters:FitStats*",
            "filters:FIT_STATS",
            "filters:FitTask*",
            "filters:PARALLEL_FITS",
            "pipeline:PipelineParams.max_sections",
            "pipeline:PipelineParams.fit_seeds",
            "pipeline:PipelineParams.max_gain_db",
            "pipeline:PipelineParams.residual_band_hz",
            "pipeline:PipelineParams.fit_tolerance_db",
        ),
        _fitted,
    ),
    Feature(
        "fit.choice",
        "which of the fitter's results is kept: the escalation and the near-equal choice",
        (
            "filters:_Escalation*",
            "filters:_escalate",
            "filters:_settled",
            "filters:fit_minimal_biquads*",
            "filters:fit_near_equal_all",
            "filters:_exposure_db",
            "filters:_publishable",
            "filters:_within_drift",
            "filters:_published_drift",
            "pipeline:_choose_fit",
            "pipeline:_lifts_beyond_goal",
            "pipeline:PipelineParams.residual_target_db",
            "pipeline:FitOptions",
        ),
        _fitted,
    ),
    Feature(
        "fit.realisation",
        "publication rounding and the device's coefficients",
        (
            "filters:Realisation*",
            "filters:drift_distribution*",
            "filters:unstable_sections",
            "beq_common.publication:*",
            "pipeline:PipelineParams.realisation",
        ),
        _fitted,
    ),
    Feature(
        "filter.arithmetic",
        "filter arithmetic and the design grid, shared by every stage",
        (
            "beq_common.biquad:*",
            "beq_common.types:*",
            "biquad:*",
            "__init__:*",
            "filters:magnitude_db",
            "filters:biquad_sos",
            "filters:_sos_from_parameters",
            "filters:_z_powers",
            "filters:section_poles",
            "filters:_prototype_poles",
            "filters:high_pass_sos",
            "filters:_REAL_POLE_TOLERANCE",
            "filters:_Z_POWERS*",
            "pipeline:_GRID_OCTAVES",
            "pipeline:PUBLISH_FS",
        ),
        _every,
    ),
    # -- the judge
    Feature(
        "judge.verification",
        "applying a cascade to the sub feed and measuring the corrected curve",
        (
            "verify:*",
            "pipeline:_judge",
            "pipeline:PipelineParams.verify_floor_hz",
            "pipeline:PipelineParams.judge_from_content_edge",
        ),
        _fitted,
    ),
    Feature(
        "judge.assess",
        "the judge's shared machinery: the verdict and the checks' common arithmetic",
        (
            "accept:assess",
            "accept:Verdict*",
            "accept:AcceptParams",
            "accept:AcceptParams.target_tilt_db_per_octave",
            "accept:AcceptParams.decision_quantum_db",
            "accept:_at",
            "accept:_smooth",
            "accept:shaping_fraction",
            "accept:recovered_fraction",
            "pipeline:PipelineParams.accept",
        ),
        _fitted,
    ),
    Feature(
        "judge.span",
        "the judged band must be wide enough to read a slope",
        ("accept:AcceptParams.min_judge_octaves",),
        _check("only "),
    ),
    Feature(
        "judge.tilt",
        "the corrected tilt against the intended",
        ("accept:AcceptParams.tilt_tolerance_db_per_octave",),
        _check("tilts "),
    ),
    Feature(
        "judge.level",
        "the corrected level against the intended",
        ("accept:AcceptParams.level_tolerance_db",),
        _check("corrected level "),
    ),
    Feature(
        "judge.goal",
        "the goal tolerance: how far from flat counts as flat",
        (
            "accept:AcceptParams.goal_tolerance_db",
            "accept:AcceptParams.spread_margin_db",
        ),
        _fitted,
    ),
    Feature(
        "judge.turnover",
        "too much too soon, then a rolloff",
        (
            "accept:turnover_db_per_octave",
            "accept:AcceptParams.turnover_min_octaves",
        ),
        _check("peaks at "),
    ),
    Feature(
        "judge.overlift",
        "lifting above anything the material or the target asks",
        ("accept:overlift_bar_db",),
        _check("lifts "),
    ),
    Feature(
        "judge.wobble",
        "ripple about the corrected trend against the material's",
        (
            "accept:spectral_roughness",
            "accept:corrected_wobble",
            "accept:AcceptParams.roughness_degree",
        ),
        _check("corrected low end is uneven"),
    ),
    Feature(
        "judge.cliff",
        "a discontinuity the correction introduces",
        (
            "accept:worst_gradient",
            "accept:AcceptParams.cliff_*",
        ),
        _check("introduces a cliff"),
    ),
    Feature(
        "judge.extent",
        "how far down the correction reaches against the content",
        (
            "accept:corrected_extent_hz",
            "accept:AcceptParams.extent_smoothing_bins",
        ),
        _check("corrected only down to"),
    ),
    Feature(
        "judge.sections",
        "each section stable after rounding and earning its slot",
        (
            "accept:AcceptParams.min_section_contribution_db",
            "accept:AcceptParams.max_drift_db",
        ),
        _check("section "),
    ),
    Feature(
        "judge.contrast",
        "boosting where contrast licenses less: lifting the quiet floor",
        ("pipeline:_within_ceiling",),
        _check("boosts "),
    ),
    Feature(
        "judge.headroom",
        "the gain reduction a design needs on the assumed sub feed",
        (
            "pipeline:measure_headroom",
            "pipeline:required_gain_reduction_db",
            "pipeline:Headroom*",
        ),
        _fitted,
    ),
    # -- selection and the response
    Feature(
        "selection",
        "which passing candidate wins, its confidence, and the run that orders it all",
        (
            "pipeline:run",
            "pipeline:Report*",
            "pipeline:Candidate*",
            "pipeline:TargetFit*",
            "pipeline:target_fit",
            "pipeline:PipelineParams",
            "accept:confidence_from_evidence",
        ),
        _fitted,
    ),
    Feature(
        "response",
        "the answer on the wire: candidates, rejected, declines and fit figures",
        (
            "designer:design",
            "designer:_decline_*",
            "designer:_to_design_candidate",
            "designer:_rejected",
            "designer:_candidate_to_json",
            "designer:response_to_json",
            "designer:_ndarray_to_json",
            "designer:_FIT_FIELDS",
            "designer:DesignCandidate*",
            "designer:DesignResponse*",
            "designer:validate_response",
            "designer:_validate_*",
            "designer:ContractViolation*",
            "designer:_ALLOWED_BIQUAD_TYPES",
            "designer:_MAX_BIQUAD_SECTIONS",
            "designer:_IDENTITY_FIELDS",
            "designer:_BLOCKER_CODES",
            "explain:*",
        ),
        _every,
    ),
    Feature(
        "request.adjustments",
        "contract 1.5's adjustments and their outcomes",
        ("adjustments:*",),
        _every,
    ),
    # -- changes no answer
    Feature(
        "identity",
        "which answer this code gives: the design version, settings digest and contract",
        (
            "designer:DESIGN_VERSION",
            "designer:CONTRACT_VERSION",
            "designer:design_settings_*",
            "beq_common:*",
            "beq_common.provenance:*",
        ),
    ),
    Feature(
        "record",
        "the run record and its name",
        (
            "record:*",
            "designer:_provenance",
            "designer:_under_root",
            "designer:_request_digest",
        ),
    ),
    Feature("cache", "the stage cache, whose answers are bit-identical", ("cache:*",)),
    Feature(
        "reporting",
        "charts, files for people, timings and the command line",
        (
            "charts:*",
            "beqd:*",
            "cli:*",
            "pipeline:Timings*",
            "pipeline:logger",
            "*:<module>",
            "*:logger",
        ),
    ),
    Feature("validation", "the synthetic protocol and E10", ("e10:*", "harness:*")),
    Feature("impact", "this module", ("impact:*",)),
)

_BY_ID = {f.id: f for f in FEATURES}


def feature(feature_id: str) -> Feature:
    return _BY_ID[feature_id]


def owners(qualified: str) -> tuple[Feature, ...]:
    """The features that own `module:qualname`: those naming it exactly, or else those whose
    most specific matching glob is the most specific, a glob whose qualname part is literal
    (`*:<module>`) before one whose qualname is a wildcard (`pipeline:*`), then the longer.
    Empty when nothing owns it."""
    exact = tuple(f for f in FEATURES if qualified in f.owns)
    if exact:
        return exact
    best: list[tuple[tuple[bool, int], Feature]] = []
    for f in FEATURES:
        keys = [
            ("*" not in p.partition(":")[2], len(p))
            for p in f.owns
            if fnmatch.fnmatchcase(qualified, p)
        ]
        if keys:
            best.append((max(keys), f))
    if not best:
        return ()
    top = max(k for k, _ in best)
    return tuple(f for k, f in best if k == top)


# -- what changed: impact.toml


@dataclass(frozen=True, slots=True)
class Touch:
    feature: str
    kind: Literal["behaviour", "threshold", "all", "unchanged"]
    degree: dict[str, float] | None = None
    old: float | None = None
    new: float | None = None
    near: float | None = None
    """For a threshold: how far outside the old and new values a figure is still `likely`."""
    note: str = ""


@dataclass(frozen=True, slots=True)
class Change:
    id: str
    design_version: int
    summary: str
    touches: tuple[Touch, ...]
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    design_version: int
    commit: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImpactData:
    since: int
    releases: tuple[Release, ...]
    changes: tuple[Change, ...]

    def after(self, design_version: int, current: int) -> tuple[Change, ...]:
        """The changes a record designed at `design_version` has not seen, oldest first."""
        return tuple(
            c for c in self.changes if design_version < c.design_version <= current
        )


def parse(text: str) -> ImpactData:
    """`impact.toml`'s contents, checked: every touch names a known feature with a valid kind."""
    raw = tomllib.loads(text)
    releases = tuple(
        Release(
            str(r["version"]),
            int(r["design_version"]),
            str(r["commit"]),
            tuple(r.get("sources", ())),
        )
        for r in raw.get("release", ())
    )
    changes = []
    for c in raw.get("change", ()):
        touches = []
        for t in c.get("touches", ()):
            kind = t["kind"]
            if kind not in ("behaviour", "threshold", "all", "unchanged"):
                raise ValueError(f"change {c['id']}: unknown kind {kind!r}")
            if t["feature"] not in _BY_ID:
                raise ValueError(f"change {c['id']}: unknown feature {t['feature']!r}")
            degree = t.get("degree")
            if kind == "behaviour":
                if not degree or set(degree) != set(OUTCOMES):
                    raise ValueError(
                        f"change {c['id']}: {t['feature']} needs a degree for each of {OUTCOMES}"
                    )
                if any(not 0.0 <= float(v) <= 1.0 for v in degree.values()):
                    raise ValueError(f"change {c['id']}: degrees are shares in [0, 1]")
            if kind == "threshold" and ("old" not in t or "new" not in t):
                raise ValueError(f"change {c['id']}: a threshold needs old and new")
            touches.append(
                Touch(
                    t["feature"],
                    kind,
                    {k: float(v) for k, v in degree.items()} if degree else None,
                    t.get("old"),
                    t.get("new"),
                    t.get("near"),
                    t.get("note", ""),
                )
            )
        changes.append(
            Change(
                str(c["id"]),
                int(c["design_version"]),
                str(c["summary"]),
                tuple(touches),
                str(c.get("evidence", "")),
            )
        )
    since = int(raw["since"])
    if any(c.design_version <= since for c in changes):
        raise ValueError("a change at or before `since` can never be scored")
    if len({c.id for c in changes}) != len(changes):
        raise ValueError("change ids must be unique")
    return ImpactData(
        since, releases, tuple(sorted(changes, key=lambda c: c.design_version))
    )


def load(path: Path = IMPACT_FILE) -> ImpactData:
    return parse(path.read_text(encoding="utf-8"))


# -- which design a record holds


@dataclass(frozen=True, slots=True)
class RecordIdentity:
    design_version: int
    design_settings: str | None
    """None when the record cannot say which settings it was designed under."""


def _release_of(revision: str, data: ImpactData) -> Release | None:
    stamp = revision.removesuffix(" (frozen build)")
    described, _, sources = stamp.partition("+src:")
    if described.endswith("-dirty"):
        return None
    for release in data.releases:
        if described in (release.commit, f"v{release.version}") or (
            described == "unknown" and sources in release.sources
        ):
            return release
    return None


def _literal(node: ast.AST):
    """A params repr's value: constants, tuples and lists of them, and calls as dicts."""
    match node:
        case ast.Constant(value=value):
            return value
        case ast.Tuple(elts=items) | ast.List(elts=items):
            return tuple(_literal(i) for i in items)
        case ast.UnaryOp(op=ast.USub(), operand=ast.Constant(value=value)) if (
            isinstance(value, int | float)
        ):
            return -value
        case ast.Name(id="inf"):
            return float("inf")
        case ast.Call(func=ast.Name(), args=[], keywords=keywords):
            return {k.arg: _literal(k.value) for k in keywords}
    raise ValueError(f"not a literal: {ast.dump(node)[:80]}")


def settings_from_params(text: str) -> str | None:
    """The design settings digest of a record's `PipelineParams` repr, or None if it can't be read.

    For records written before they carried their identity. A designer record holds the
    params its request was designed with, adjustments applied, so a request whose adjustments
    moved a setting reads as other settings: unknown, which is the safe answer.
    """
    from beqforge.designer import design_settings_digest
    from beqforge.pipeline import PipelineParams

    try:
        tree = _literal(ast.parse(text, mode="eval").body)
        default = PipelineParams()
        params = replace(
            default,
            strategies=tuple(tree["strategies"]),
            exclude_bands_hz=tuple(tuple(b) for b in tree["exclude_bands_hz"]),
            judge_from_content_edge=bool(tree["judge_from_content_edge"]),
            accept=replace(
                default.accept,
                goal_tolerance_db=float(tree["accept"]["goal_tolerance_db"]),
                target_tilt_db_per_octave=float(
                    tree["accept"]["target_tilt_db_per_octave"]
                ),
            ),
            realisation=replace(
                default.realisation,
                fs=float(tree["realisation"]["fs"]),
                coefficient_bits=int(tree["realisation"]["coefficient_bits"]),
                integer_bits=int(tree["realisation"]["integer_bits"]),
            ),
        )
    except (SyntaxError, ValueError, KeyError, TypeError):
        return None
    return design_settings_digest(params)


def record_identity(record: dict, data: ImpactData) -> RecordIdentity | str:
    """The identity a record was designed at, or why it can't be known."""
    fingerprint = record.get("fingerprint")
    if not isinstance(fingerprint, dict) or "revision" not in fingerprint:
        return "not a beqforge run record"
    stated = record.get("design_identity")
    if isinstance(stated, dict) and isinstance(stated.get("design_version"), int):
        return RecordIdentity(stated["design_version"], stated.get("design_settings"))
    release = _release_of(str(fingerprint["revision"]), data)
    if release is None:
        return f"designed by a build this designer does not know ({fingerprint['revision']})"
    return RecordIdentity(
        release.design_version, settings_from_params(str(fingerprint.get("params", "")))
    )


# -- scoring


@dataclass(frozen=True, slots=True)
class Reason:
    change: str | None
    feature: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class Assessment:
    tier: Tier
    score: float | None
    from_design_version: int | None
    reasons: tuple[Reason, ...]


def _unknown(
    reason: str,
    version: int | None = None,
    change: str | None = None,
    feature: str | None = None,
) -> Assessment:
    return Assessment("unknown", None, version, (Reason(change, feature, reason),))


def _threshold(touch: Touch, relied: Reliance) -> tuple[float, bool] | None:
    """(score, certain) for a threshold change, or None when the record lacks the figure."""
    if relied.value is None:
        return None
    low, high = sorted((float(touch.old), float(touch.new)))
    if low <= relied.value <= high:
        return 1.0, True
    if touch.near:
        distance = min(abs(relied.value - low), abs(relied.value - high))
        if distance <= touch.near:
            return LIKELY + (1.0 - LIKELY) * (1.0 - distance / touch.near) * 0.99, False
    return 0.1, False


def assess(record: dict, current: tuple[int, str], data: ImpactData) -> Assessment:
    """How likely a design of `record`'s request by a designer at `current` (design version,
    settings digest) is to differ from the one it holds (§7.1, "Impact")."""
    identity = record_identity(record, data)
    if isinstance(identity, str):
        return _unknown(identity)
    version, settings = identity.design_version, identity.design_settings
    now, now_settings = current
    if settings is None:
        return _unknown(
            "the record does not say which settings it was designed under", version
        )
    if settings != now_settings:
        return _unknown(
            f"designed under other settings ({settings}; this designer's are {now_settings})",
            version,
        )
    if version == now:
        return Assessment("unaffected", 0.0, version, ())
    if version > now:
        return _unknown(
            f"designed at version {version}, newer than this designer's {now}", version
        )
    if version < data.since:
        return _unknown(
            f"designed at version {version}, older than this designer's impact data "
            f"(version {data.since} on)",
            version,
        )
    reasons: list[Reason] = []
    best = 0.0
    certain = likely = False
    for change in data.after(version, now):
        for touch in change.touches:
            if touch.kind == "unchanged":
                continue
            relied = feature(touch.feature).reader(record)
            if relied is None:
                continue
            if touch.kind == "behaviour":
                share = touch.degree[relied.kind]
                if share <= 0.0:
                    continue
                detail = f"{relied.detail}; {share:.0%} of such designs moved"
            elif touch.kind == "all":
                share, likely = 1.0, True
                detail = f"{relied.detail}; the change reaches every such design"
            else:
                scored = _threshold(touch, relied)
                if scored is None:
                    return _unknown(
                        f"the record lacks the figure {touch.feature} compares, "
                        f"which moves from {touch.old} to {touch.new}",
                        version,
                        change.id,
                        touch.feature,
                    )
                share, sure = scored
                certain |= sure
                detail = (
                    f"{relied.detail}; recorded {relied.value:g}, the threshold moves "
                    f"from {touch.old} to {touch.new}"
                )
            best = max(best, share)
            reasons.append(Reason(change.id, touch.feature, detail))
    if certain:
        tier: Tier = "will_move"
    elif likely or best >= LIKELY:
        tier = "likely"
    elif best > 0.0:
        tier = "possible"
    else:
        return Assessment("unaffected", 0.0, version, ())
    return Assessment(tier, round(best, 4), version, tuple(reasons))


# -- the endpoint


class MalformedImpactRequest(ValueError):
    """400: the body does not parse or fails the schema."""


def _check_request(body: object) -> list[tuple[str, str]]:
    if not isinstance(body, dict) or set(body) != {"contract_version", "records"}:
        raise MalformedImpactRequest(
            "the body must hold exactly contract_version and records"
        )
    if body["contract_version"] != "1.6":
        raise MalformedImpactRequest(
            f"contract_version must be '1.6', not {body['contract_version']!r}"
        )
    records = body["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise MalformedImpactRequest(f"records must be a list of 1 to {MAX_RECORDS}")
    pairs = []
    for i, entry in enumerate(records):
        if not isinstance(entry, dict) or set(entry) != {"id", "path"}:
            raise MalformedImpactRequest(f"records[{i}] must hold exactly id and path")
        rid, path = entry["id"], entry["path"]
        if not isinstance(rid, str) or not rid:
            raise MalformedImpactRequest(f"records[{i}].id must be a non-empty string")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or (len(path) > 1 and path[1] == ":" and path[0].isalpha())
            or "\\" in path
            or ".." in path.split("/")
        ):
            raise MalformedImpactRequest(
                f"records[{i}].path {path!r} must be relative and POSIX, with no '..'"
            )
        pairs.append((rid, path))
    if len({rid for rid, _ in pairs}) != len(pairs):
        raise MalformedImpactRequest("two records share an id")
    return pairs


def _read(root: Path, relative: str) -> dict | str:
    from beqforge.reference import UnusableReference, resolve

    try:
        path = resolve(root, relative, "record")
    except UnusableReference as refused:
        return refused.reason
    if not path.is_file():
        return "record not found"
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as unreadable:
        return f"record unreadable: {unreadable}"
    return record if isinstance(record, dict) else "not a beqforge run record"


def answer(
    body: object,
    shared_root: Path | None,
    identity: dict,
    data: ImpactData | None = None,
) -> tuple[int, dict]:
    """`POST /impact`: (status, payload). `identity` is the server's, as on `/health`."""
    try:
        pairs = _check_request(body)
    except MalformedImpactRequest as malformed:
        return 400, {"error": f"malformed impact request: {malformed}"}
    if shared_root is None:
        return 422, {
            "error": "no shared root is configured on this designer",
            "reason": "no shared root is configured on this designer",
        }
    data = data or load()
    current = (identity["design_version"], identity["design_settings"])
    results = []
    for rid, relative in pairs:
        record = _read(shared_root, relative)
        found = (
            _unknown(record)
            if isinstance(record, str)
            else assess(record, current, data)
        )
        results.append(
            {
                "id": rid,
                "tier": found.tier,
                "score": found.score,
                "from_design_version": found.from_design_version,
                "reasons": [
                    {"change": r.change, "feature": r.feature, "detail": r.detail}
                    for r in found.reasons
                ],
            }
        )
    versions = [
        r["from_design_version"]
        for r in results
        if r["from_design_version"] is not None
    ]
    changes = data.after(min(versions), current[0]) if versions else ()
    return 200, {
        "contract_version": "1.6",
        "design_version": identity["design_version"],
        "design_settings": identity["design_settings"],
        "designer_build": identity.get("designer_build"),
        "changes": [
            {"design_version": c.design_version, "id": c.id, "summary": c.summary}
            for c in changes
        ],
        "results": results,
    }


# -- which code a commit changed, for `tools/impact.py check`


def _without_docstrings(node: ast.AST) -> ast.AST:
    """A copy of `node` with every docstring and bare string statement removed."""
    node = ast.parse(ast.unparse(node)) if not isinstance(node, ast.Module) else node
    for parent in ast.walk(node):
        body = getattr(parent, "body", None)
        if isinstance(body, list):
            parent.body = [
                s
                for s in body
                if not (
                    isinstance(s, ast.Expr)
                    and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str)
                )
            ] or [ast.Pass()]
    return node


def _dump(node: ast.AST) -> str:
    return ast.dump(_without_docstrings(node), include_attributes=False)


def definitions(source: str) -> dict[str, str]:
    """Each qualname in a module to a dump of its code, docstrings and comments ignored.

    Functions and classes by name; a class's methods and fields as `Class.name`; a module
    constant (a single-name assignment) by its name; everything else at module level, imports
    included, as `<module>`, and a class's other statements (decorators, bases) as the class.
    """
    tree = ast.parse(source)
    found: dict[str, str] = {}
    rest: list[ast.stmt] = []

    def assigned(statement: ast.stmt) -> str | None:
        match statement:
            case ast.AnnAssign(target=ast.Name(id=name)):
                return name
            case ast.Assign(targets=[ast.Name(id=name)]):
                return name
        return None

    for statement in tree.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            found[statement.name] = _dump(statement)
        elif isinstance(statement, ast.ClassDef):
            own: list[ast.stmt] = []
            for member in statement.body:
                name = (
                    member.name
                    if isinstance(
                        member, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
                    )
                    else assigned(member)
                )
                if name is None:
                    own.append(member)
                else:
                    found[f"{statement.name}.{name}"] = _dump(member)
            shell = ast.ClassDef(
                name=statement.name,
                bases=statement.bases,
                keywords=statement.keywords,
                body=own or [ast.Pass()],
                decorator_list=statement.decorator_list,
                type_params=getattr(statement, "type_params", []),
            )
            found[statement.name] = _dump(ast.fix_missing_locations(shell))
        elif (name := assigned(statement)) is not None:
            found[name] = _dump(statement)
        elif not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            rest.append(statement)
    found["<module>"] = _dump(ast.Module(body=rest, type_ignores=[]))
    return found


def changed(before: str | None, after: str | None) -> set[str]:
    """The qualnames whose code differs between two versions of a module, added and removed
    ones included. None stands for a module that does not exist on that side."""
    old = definitions(before) if before is not None else {}
    new = definitions(after) if after is not None else {}
    return {q for q in old.keys() | new.keys() if old.get(q) != new.get(q)}
