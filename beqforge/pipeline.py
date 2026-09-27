"""The repeatable process: material in, a judged filter and its reasoning out.

A **target** is a curve to be realised; a **strategy** is one way of deriving one. Each is a
first-class citizen — they are run through the same fitter and the same acceptance model, so
their outputs are directly comparable, and any of them may be selected, combined, or all run
at once with the best surviving candidate taken. They disagree usefully, and a disagreement
is evidence about the material rather than a problem to be resolved by picking a favourite.

* **`flatten`** — invert the measured mix response: the shape a good correction produces is
  flat to the bottom of the evidence, and the target is the mix's own deficit against its
  plateau. Needs no model of the rolloff and no `N`/`A` separation, which is the weak link.
* **`counterfactual`** — restore the filtered channels, re-sum, read the deficit off the mix.
  The route for a mix whose sum carries no usable evidence at the bottom because a filtered
  channel sits far under the mains there.
* **`parametric`** — `identify_rolloff` on the mono mix and invert the fitted rolloff.
  The soft-hinge route; the only one that can produce an exact closed-form inversion, when the
  alignment is representable.

`flatten` is validated only on modern, bass-rich material. On a sparse or old mix, flattening
would lift the noise floor with the content, and nothing in the target itself objects — that
is what the evidence pricing is for. `diagnose`'s band tracking sets the noise floor below
which `flatten` holds its boost flat, and its level-independence test is diagnostic only;
identification is not on the path to a target except through `parametric`.

Candidates are judged by `accept.assess` and the survivors ranked. The ranking is deliberately
shallow — the acceptance model does the work, and a scalar score that could overrule it would
reintroduce exactly the aggregate-blindness R1 exists to defeat.
"""

import dataclasses
import logging
import math
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import scipy.fft

from beqforge import DESIGN_GRID, BiquadSpec
from beqforge import cache
from beqforge.accept import (
    AcceptParams,
    Verdict,
    assess,
)
from beqforge.design import DesignMethod, DesignParams, design
from beqforge.diagnose import (
    Diagnosis,
    DiagnoseParams,
    diagnose,
    mean_spectrum,
    plateau_reference,
    smooth_unexcluded,
    supported_mix_change,
    unexcluded,
)
from beqforge.extraction import Envelopes, ExtractionParams, extract
from beqforge.filters import (
    FIT_STATS,
    FitRequest,
    FitStats,
    Realisation,
    publication_filters,
    biquad_sos,
    correction_band_hz,
    fit_minimal_biquads_all,
    magnitude_db,
)
from beqforge.identify import IdentifyParams, Identification, identify_rolloff
from beqforge.material import (
    LFE_GAIN,
    MAIN_GAIN,
    Material,
    PlaybackParams,
    bass_managed_sum,
)
from beqforge.verify import (
    Correction,
    device_waveform,
    house_curve_db,
    verify,
    waveform_peak,
)

logger = logging.getLogger(__name__)


class Timings:
    """Wall time per stage, so a slow run can be diagnosed instead of guessed at.

    Kept as plain seconds against ordered labels rather than anything cleverer: the question
    it has to answer is "which stage is the budget", and the answer has always been one stage.
    """

    def __init__(self) -> None:
        self.stages: list[tuple[str, float]] = []

    @contextmanager
    def stage(self, label: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.stages.append((label, time.perf_counter() - started))

    @property
    def total_s(self) -> float:
        return sum(seconds for _, seconds in self.stages)


PUBLISH_FS = 96000.0
_GRID_OCTAVES = math.log2(400.0 / 3.0)
"""Span of `DESIGN_GRID`, so a width in octaves becomes a count of points."""


@dataclass(frozen=True, slots=True)
class PipelineParams:
    """Everything the run may vary, in one place so a refinement is one edit."""

    diagnose: DiagnoseParams = field(default_factory=DiagnoseParams)
    extraction: ExtractionParams = field(default_factory=ExtractionParams)
    identify: IdentifyParams = field(default_factory=IdentifyParams)
    accept: AcceptParams = field(default_factory=AcceptParams)
    realisation: Realisation = field(default_factory=Realisation)
    playback: PlaybackParams = field(default_factory=PlaybackParams)
    """Sub-feed model used for playback verification and clipping measurement."""

    strategies: tuple[str, ...] = ("flatten", "counterfactual", "parametric")
    """Which target-derivation strategies to run, by name (see `STRATEGIES`).

    All of them by default. They cost a fit each, and they disagree in ways that say something
    about the material, so the default is to hear from all of them and let the acceptance
    model choose."""

    flatten_settled_octaves: float = 0.33
    """How long the deficit must stay shut before the correction is called over.

    A third of an octave. The material wobbles around its own plateau by several dB (§6.4), so
    a single point under the floor is roughness, not the end of the correction."""

    flatten_deficit_floor_db: float = 0.5
    """Deficit below which `flatten`'s correction is over, scanning upward from the bottom.

    This replaces `flatten_reference_hz`, which was 40.0 and justified as "above the knee,
    below bass management" — the same sentence that justified the 22-35 Hz channel reference
    §3.1 had to remove, on the strategy that produces every accepted filter. `flatten` now
    levels the mix against the mix's **own plateau** (`plateau_reference`) and stops where its
    own deficit stops, so neither the level nor the extent is a constant.

    A fixed 40 Hz sat inside the plateau of every mix it was tried on, so it was not yet wrong
    — but only narrowly on some, and a mix with a knee near 50 Hz would have been levelled
    inside its own rolloff.

    Scanning **upward from the bottom** and taking the first crossing is what keeps the
    high-frequency fall out of the target. Referenced to a plateau level rather than to a
    point, the mix drops back below that level above the plateau's top — by construction —
    and a deficit computed over the whole band would read that fall as something to correct.
    The correction is the *first* region, not every region."""

    flatten_taper_ratio: float = 1.25
    """How far above the anchor the target is tapered to nothing, as a frequency ratio.

    A quarter of an octave. Wide enough that the transition is smooth against a 400-point
    log grid, narrow enough that it does not reach down into the correction."""

    restore_caps_db: tuple[float, ...] = (25.0, 35.0, 45.0, 50.0)
    """Ceilings on the counterfactual restoration, one candidate each.

    A sweep rather than a choice: how far a channel's attenuation can be inverted before it
    is inverting something that is not a filter is exactly what is not known in advance, and
    the acceptance model is better placed to reject the wrong ones than a prior is.

    The sweep runs to 50 dB because that is where a very heavily attenuated channel's own
    measured attenuation runs out: smaller caps can leave the restored mix still falling too
    steeply for the acceptance model (`max_tilt_db_per_octave`), while beyond 50 dB every cap
    produces the identical target, so the top of the sweep is a natural stop, not an arbitrary
    one. Cheap to try even where it does nothing: a cap whose target matches an earlier one is
    deduplicated before fitting."""

    max_sections: int = 4
    """Ceiling on biquads a fit may spend, escalated from 1 up to this (`_tiers`).

    Raising it to `BIQUAD_BUDGET` (10, designer-interface.md v1.0 §5) was tried on the theory
    that a title exhausting 4 sections without settling was budget-starved rather than
    shape-limited. It was not: the extra sections were spent, and the candidate failed the same
    comparative checks anyway ("still falls ... under-corrected; corrected level outside the
    window" is not a section-count problem). Every other candidate hit its identical wall at
    whatever section count it tried. Cost was out of proportion to that answer — an order of
    magnitude more time and optimiser runs for the same abstention.

    Reverted rather than left at 10 and merely undocumented: a search-cost ceiling that costs
    14x on exactly the titles it was meant to help, for no change in outcome, is not a free
    knob to leave turned up on the chance some other title differs. The actual gap this
    exposed is in what `flatten`/`counterfactual` construct as targets — a corrected level
    the acceptance window can hold and a slope it can defend at once — not in how many
    sections are on offer to fit whatever target they hand the optimiser."""

    parametric_max_boost_db: float = 20.0
    """Total parametric correction cap, used to place its protective high-pass.

    Separate from max_gain_db, the per-section bound shared by every fitter.
    """

    residual_target_db: float = 0.5
    max_gain_db: float = 26.0
    """The fitter's per-*section* gain bound (§5.1), not a bound on any target.

    Realisability, not evidence: no BEQ should publish a section gain like this regardless of
    what a target asks for — `gain_headroom_db`'s note on `DesignParams` is the precedent,
    "a fit allowed 45 dB used it, expressing a correction under 5 dB above 10 Hz as a 3 Hz
    shelf". It used to also clip `flatten`'s target directly, standing in for evidence the
    target-construction step didn't have. Now that it does (`confidence_z`, below), the two
    roles were separated rather than left doubled up under one name: this dial no longer
    limits how much correction `flatten` may propose, only how much gain any single realised
    section may carry once fitting is done."""

    confidence_z: float = 1.645
    """How many bootstrap standard errors of margin a bin must clear before `flatten` trusts
    it (§4.1). This multiplier has no calibrated coverage guarantee.

    Replaces a flat `noise_margin_db`. That constant could not distinguish 1,300 loud frames
    drawn from hundreds of separate scenes from 11 that are each their own isolated instant —
    both got the same 12 dB haircut. `Envelopes.margin_se_db` is a block bootstrap over
    exactly that evidence (contiguous runs, not raw frames, because a 50%-overlapping frame
    pair is not two independent observations), so the ceiling now tightens where the estimate
    itself is shaky and relaxes where it is not, per bin per title, instead of asserting one
    number for every extraction. Where the evidence is solid the derived ceiling comes out
    looser than the old flat one; where a title has almost none (a handful of independent
    loud events) the standard error runs several times larger than elsewhere and the ceiling
    tightens accordingly without being told to.

    Missing or deliberately omitted measurements license no boost."""

    fit_seeds: tuple[int, ...] = (0,)
    """Seeds the fit is repeated from at each section count and split.

    One. `fit_to_biquads` warns that the objective is multimodal and that results "vary by an
    order of magnitude between seeds" — but that was measured on the *parametric* route's
    targets, a high-order rolloff terminated by a much lower-order protective filter spanning
    100 dB. The targets that produce every accepted filter are `flatten`'s, and on those a
    second seed bought little enough to be measurable (AGENTS.md's performance notes). That was
    measured when `flatten`'s targets were held under 26 dB by a fixed dial; `confidence_z`
    lets a well-supported title's target run past that, and single-seed fitting has not been
    re-measured against the larger, less "gentle" targets that implies — worth checking
    before trusting it on a title whose confidence-derived ceiling sits well above 26 dB.

    It remains the first thing to put back if a title starts producing a filter that looks
    wrong, which is why it is a parameter rather than a literal."""

    lowest_frequency_hz: float = 5.0
    """Lowest frequency a section may be *placed* at — the evidence floor of `_fit_all`.

    Not a band: one edge, and the only one `correction_band_hz` does not derive. Its own
    docstring gives the reason it cannot be — a section below the lowest measured frequency has
    its corner and Q fitted against nothing, and unbounded the fit does exactly that, once
    returning a 3.22 Hz shelf at +45 dB to express a correction under 5 dB above 10 Hz.

    5.0 to match `DesignParams.lowest_frequency_hz`, which is the same quantity on the
    parametric path and was the only place it was named. Unifying them is the improvement here;
    the value itself is still a prior, and a loose one in both directions. The analysis stages
    measure from 4.0 Hz (`DiagnoseParams.band_hz`, `ExtractionParams.band_hz`), so 5.0 is
    *tighter* than the evidence and forgoes a band that was observed. `noise_floor_hz` would be
    tighter still and is title-derived, which is what §2.1 asks for — but `flatten` deliberately
    holds its target flat below that floor, so clamping placement there too would change what
    the fitter is allowed to realise and not merely where it may look. That belongs with the
    noise-floor work, not here."""

    residual_band_hz: tuple[float, float] = (5.0, 200.0)
    """Band the fit's residual is scored over — wider than any placement, on purpose.

    `_fit_structure` states the rule: evaluate wide, place narrow. A fit scored only where the
    correction is lets a section drift upward to where nothing penalises it, which once put a
    +15.2 dB peak at 378 Hz into a bass correction. Named here rather than left a literal
    because `_fit_all` now has to guarantee it contains every derived placement band, and a
    constant it cannot see is one it cannot check."""

    verify_band_hz: tuple[float, float] = (5.0, 45.0)
    exclude_bands_hz: tuple[tuple[float, float], ...] = ()
    """Authored intervals omitted from evidence, with zero requested correction.

    References and smoothing use separate contiguous segments. Diagnosis, extraction,
    identification, all strategies and verification share these omissions. A fragmented
    judged interval cannot establish a continuous correction and causes explicit abstention.
    A smooth fitted cascade may still act inside an omission; zero is the target, not a
    guarantee that an arbitrary authored interval can be preserved exactly by biquads."""


@dataclass(frozen=True, slots=True)
class Headroom:
    """A clipping measurement qualified by its signal, gain and device assumptions."""

    offset_db: float
    peak: float | None
    playback: PlaybackParams
    realisation: Realisation
    analysis_fs: float
    unavailable_reason: str | None = None
    full_scale: float = 1.0

    def summary(self) -> str:
        if self.unavailable_reason is not None:
            return f"gain reduction unavailable ({self.unavailable_reason})"
        if self.offset_db >= 0:
            return "no gain reduction needed for the assumed sub-feed model"
        return f"needs {-self.offset_db:.1f} dB gain reduction for the assumed sub-feed model"

    def assumptions(self) -> str:
        device = self.realisation
        return (
            f"{self.playback.description()}; bass management at {self.analysis_fs:g} Hz; "
            f"published BEQ at {device.fs:g} Hz, fixed-point "
            f"{device.integer_bits}.{device.coefficient_bits - device.integer_bits}; "
            "unity full scale, extraction bandwidth only, ring-out retained, 16x interpolated peak"
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    """One design and everything known about it."""

    label: str
    filters: list[BiquadSpec]
    target_db: np.ndarray
    fit_error_db: float
    correction: Correction
    verdict: Verdict
    optimiser_filters: list[BiquadSpec] = field(default_factory=list)
    """Full-precision fit, retained only for diagnostics and its residual."""

    method: DesignMethod | None = None
    effective_params: str | None = None
    """Effective strategy settings used to derive the proposal, for reproducibility."""

    target_notes: tuple[str, ...] = ()
    """What bounded the target, if anything.

    §4.1 argues a limit that binds is a signal and not merely a limit — a correction whose
    shape is being set by the noise floor or by a boost cap says the title is in the marginal
    regime. Nothing recorded that, so a target held flat by the guard and one that genuinely
    flattened out looked identical in the output.
    """

    unpriced_target_db: np.ndarray | None = None
    """The target before `priced_by_evidence` clipped it, if any (§14.1).

    `None` for a caller-supplied candidate with no target — the same convention
    as `Proposal.unpriced_target_db`, which this is carried through from unchanged. Exists so a
    reader can see how much the evidence ceiling removed, which `verdict.recovered_fraction`
    states as a ratio but this states as the curve itself.
    """

    headroom: Headroom | None = None
    """Exact playback assumptions and measured peak, absent for legacy/caller-built candidates."""

    @property
    def peak_gain_db(self) -> float:
        """Peak filter magnitude, distinct from clipping cost on the sub feed."""
        if self.headroom is None:
            return float(
                np.max(
                    magnitude_db(
                        biquad_sos(self.filters, PUBLISH_FS), DESIGN_GRID, PUBLISH_FS
                    )
                )
            )
        device = self.headroom.realisation
        sos = device.quantise(biquad_sos(publication_filters(self.filters), device.fs))
        return float(np.max(magnitude_db(sos, DESIGN_GRID, device.fs)))

    @property
    def mv_adjust_db(self) -> float:
        """Legacy name for peak filter gain; never a master-volume/headroom requirement."""
        return self.peak_gain_db

    correction_support_score: float = math.nan
    """Boost-weighted relative precision of temporal contrast; uncalibrated.

    Missing evidence is unavailable, not maximal. This measures the proposed correction,
    not how much of an assumed original deficit it recovers or whether mastering caused it.
    """

    @property
    def confidence(self) -> float:
        """Compatibility alias for correction_support_score; no probability interpretation."""
        return self.correction_support_score


@dataclass(frozen=True, slots=True)
class Report:
    """The whole run."""

    material: Material
    diagnosis: Diagnosis
    identification: Identification | None
    candidates: list[Candidate]
    timings: Timings
    fit_stats: FitStats
    accept: AcceptParams = field(default_factory=AcceptParams)
    """The model the candidates were judged by — `accepted` needs the shape that was asked for."""

    evidence_notes: tuple[str, ...] = ()
    """Measurement limitations and abstention reasons, including runs with no candidates."""

    ranking_tie_db: float = 0.25
    """Flatness difference below which two candidates are the same answer (`accepted`).

    Inside it, the one with fewer sections wins — R3's parsimony, applied where it belongs.
    Candidates whose departures differ by a few hundredths of a dB are genuinely tied, since
    the measure's own scatter is far larger, and preferring the lower number would be
    preferring noise. Candidates that differ by a clear margin are not a tie at all."""

    mix_reference_db: float = math.nan
    """Median level of the mix's own plateau: what every deficit is measured against."""

    mix_plateau_hz: tuple[float, float] = (math.nan, math.nan)
    """Where that plateau is. NaN when the mix has none, which is itself a blocker."""

    judged_band_hz: tuple[float, float] | None = None
    """The band every candidate's corrected curve was judged over; `None` if never set."""

    blockers: tuple[str, ...] = ()
    """Why the run abstained before proposing anything — also in `evidence_notes`, where they
    come last. Kept apart so a decline can lead with its reason."""

    @property
    def accepted(self) -> Candidate | None:
        """The best of the candidates the acceptance model let through.

        Deliberately shallow: the acceptance model does the work, and a scalar score that
        could overrule it would reintroduce exactly the aggregate-blindness R1 exists to
        defeat. This only orders candidates already through it.

        Ranked on `Correction.departure_db` against the shape that was *requested* — so a run
        asking for a house curve is not handed the flattest candidate — then on section count
        within `ranking_tie_db`. It was ranked on `wobble_db`, which is the statistic the
        flatness clause judges but the wrong one to choose *between* passing candidates: it is
        blind to level and tilt, which acceptance admits across a wide range, and the margins it
        decided on were a fraction of a dB in a quantity whose own scatter is several dB. That
        could prefer a candidate several dB above plateau to one a fraction of a dB below it,
        for a hair less wobble and one fewer section.
        """
        passing = [c for c in self.candidates if c.verdict.passed]
        if not passing:
            return None
        wanted = self.accept.target_tilt_db_per_octave
        flattest = min(c.correction.departure_db(wanted) for c in passing)
        # every candidate indistinguishable from the flattest, then the cheapest of those.
        # Flatness breaks the remaining tie so the result does not depend on candidate order.
        tied = [
            c
            for c in passing
            if c.correction.departure_db(wanted) <= flattest + self.ranking_tie_db
        ]
        return min(
            tied, key=lambda c: (len(c.filters), c.correction.departure_db(wanted))
        )


@dataclass(frozen=True, slots=True)
class Proposal:
    """One strategy's suggestion: a curve to fit, or a cascade already known exactly."""

    label: str
    target_db: np.ndarray | None = None
    filters: list[BiquadSpec] | None = None
    residual_db: float = 0.0
    method: DesignMethod | None = "non_parametric"
    effective_params: str | None = None
    notes: tuple[str, ...] = ()
    """What bound this target, if anything. Carried through to the `Candidate`."""

    unpriced_target_db: np.ndarray | None = None
    """`target_db` before `priced_by_evidence` clipped it to the measured margin (§14.1).

    `None` whenever `target_db` is — a strategy that builds no target has nothing to have
    clipped. Carried through so `recovered_fraction` and a reader can both see how much the
    evidence ceiling removed, which `target_db` alone cannot show once it has been clipped."""


def _deficit_anchor(
    grid: np.ndarray,
    deficit_db: np.ndarray,
    params: "PipelineParams",
    plateau_hz: tuple[float, float],
) -> float:
    """Find the first sustained end of the low-frequency mix deficit.

    Scan upward from the first deficit and require a settled run below the floor;
    this anchors the target taper without following unrelated high-frequency shape.
    """
    keep = unexcluded(grid, params.exclude_bands_hz)
    over = (deficit_db >= params.flatten_deficit_floor_db) & keep
    if not over.any():
        # nothing to correct anywhere; the caller discards the proposal on max() < 1 dB
        return float(plateau_hz[0])
    run = max(1, int(round(len(grid) * params.flatten_settled_octaves / _GRID_OCTAVES)))
    first = int(np.argmax(over))
    settled = np.convolve(
        ((~over & keep)[first:]).astype(float), np.ones(run), mode="valid"
    )
    closed = np.flatnonzero(settled >= run)
    if closed.size:
        return float(grid[first + int(closed[0])])
    # A deficit that never settles ends at the plateau's lower edge.
    return float(plateau_hz[0])


def _taper(freqs: np.ndarray, reference_hz: float, ratio: float) -> np.ndarray:
    """Raised cosine falling from 1 at `reference_hz` to 0 at `reference_hz * ratio`.

    In log-frequency, and raised cosine rather than linear, so the target has a continuous
    derivative where it stops as well as a continuous value. A fit is scored on the target it
    is handed; anything the target does that a biquad cascade cannot follow is charged to the
    cascade's residual and read as a bad fit.
    """
    position = np.log2(np.asarray(freqs) / reference_hz) / math.log2(ratio)
    return 0.5 * (1.0 + np.cos(math.pi * np.clip(position, 0.0, 1.0)))


def evidence_notes(envelopes, z: float) -> list[str]:
    """Keep absent and failed measurements visible even when no proposal survives."""
    states = envelopes.evidence_states(z)
    return [
        f"correction evidence: {int(np.sum(states == state))} bins {state}; no boost licensed"
        for state in ("failure", "unavailable", "omitted")
        if np.any(states == state)
    ]


def correction_evidence_score(target: np.ndarray, envelopes, z: float) -> float:
    """Boost-weighted relative precision of temporal contrast, conditional on its assumptions.

    Scale-free: recovering half a deficit is not half as credible. No request or missing
    precision supplies no score; missing bins contribute zero. Not a probability, and not
    a mastering classifier. Fit residual, recovered fraction and level invariance are absent.
    """
    weight = np.maximum(target, 0)
    if not np.isfinite(weight).all() or weight.sum() <= 0:
        return math.nan
    margin = envelopes.margin_db
    se = envelopes.margin_se_db
    quality = np.zeros_like(margin)
    if se is not None:
        valid = np.isfinite(margin) & (margin > 0) & np.isfinite(se)
        quality[valid] = np.clip(1 - z * se[valid] / margin[valid], 0, 1)
        quality[envelopes.boost_ceiling(z) <= 0] = 0
    on_grid = np.interp(DESIGN_GRID, envelopes.freqs, quality, left=0, right=0)
    return float(np.sum(weight * on_grid) / weight.sum())


def _flat_deficit(material: Material, params: "PipelineParams"):
    """The mix against its own plateau: spectrum, reference, smoothed deficit and its anchor.

    Shared by the target (`low_end_deficit_db`) and the judged band (`judged_band_hz`) so
    both find the knee in the same place. `None` when the mix has no usable plateau.
    """
    freqs, response = mean_spectrum(material.mono_mix, material.fs)
    level, plateau_hz = plateau_reference(
        response, freqs, params.diagnose, params.exclude_bands_hz
    )
    if not math.isfinite(level):
        return None
    deficit = smooth_unexcluded(
        np.maximum(-(response - level), 0.0), freqs, params.exclude_bands_hz, 15
    )
    on_grid = np.interp(DESIGN_GRID, freqs, deficit, left=deficit[0], right=0.0)
    anchor = _deficit_anchor(DESIGN_GRID, on_grid, params, plateau_hz)
    return freqs, response, level, plateau_hz, on_grid, anchor


def _judged_top_hz(anchor_hz: float, params: "PipelineParams") -> float:
    """Upper edge of the judged band — and the pivot of the goal below the knee."""
    return min(max(params.verify_band_hz[1], anchor_hz), float(DESIGN_GRID[-1]))


def low_end_deficit_db(
    material: Material, params: "PipelineParams"
) -> np.ndarray | None:
    """What the mix's low end is missing: the most any strategy may ask a filter to restore.

    Measured against the **goal** below the knee: `verify.house_curve_db` at
    `AcceptParams.target_tilt_db_per_octave`, pivoting at the top of the judged band. Flat by
    default; a positive tilt asks for a rising low end, a negative one for a gentle rolloff.
    The deficit is kept from the bottom up to its first settled end (`_deficit_anchor`) and
    tapered off above it.

    A shortfall *above* that point is not a missing low end. It is the passband's own shape —
    a bass-heavy source whose plateau sits at the bottom of the band reads everything above
    it as "deficit" — and a strategy allowed to fill it reshapes the passband. It did: a
    +18.7 dB parametric boost at 88 Hz on a never-filtered corpus title (IMPROVEMENT_PLAN E2).

    This is `flatten`'s unpriced target; every strategy's target is capped by it in
    `priced_by_evidence`. `None` when the mix has no usable plateau.
    """
    measured = _flat_deficit(material, params)
    if measured is None:
        return None
    freqs, response, level, plateau_hz, on_grid, anchor = measured
    tilt = params.accept.target_tilt_db_per_octave
    if tilt != 0.0:
        goal = house_curve_db(freqs, _judged_top_hz(anchor, params), tilt)
        deficit = smooth_unexcluded(
            np.maximum(level + goal - response, 0.0),
            freqs,
            params.exclude_bands_hz,
            15,
        )
        on_grid = np.interp(DESIGN_GRID, freqs, deficit, left=deficit[0], right=0.0)
        anchor = _deficit_anchor(DESIGN_GRID, on_grid, params, plateau_hz)
    return on_grid * _taper(DESIGN_GRID, anchor, params.flatten_taper_ratio)


def passband_ripple_db(
    material: Material, params: "PipelineParams"
) -> tuple[float, tuple[float, float]] | None:
    """The programme's own texture where nothing is missing: crest-to-trough, dB, and where.

    Measured on the same smoothed mean spectrum the deficit is, over the passband above the
    correction — the top of the judged band to the top of the analysis band — as the spread of
    the curve about its own log-frequency trend, so a tilted passband is not read as ripple.

    Crest to trough, not a one-sided dip, because the reference sits near the 90th percentile
    of the spectrum, on the crests: a shortfall measured from it spans the whole swing. On the
    negative corpus (IMPROVEMENT_PLAN E2) every unfiltered title's low-end deficit came in
    under this (at most 0.77x); every real title and injected filter above it (1.08x and up).
    `None` when there is no passband left above the correction to measure.
    """
    measured = _flat_deficit(material, params)
    if measured is None:
        return None
    freqs, response, _, _, _, anchor = measured
    low, high = _judged_top_hz(anchor, params), params.diagnose.band_hz[1]
    band = (freqs >= low) & (freqs <= high) & unexcluded(freqs, params.exclude_bands_hz)
    if band.sum() < 8:
        return None
    smooth = smooth_unexcluded(response, freqs, params.exclude_bands_hz, 15)[band]
    octaves = np.log2(freqs[band])
    about = smooth - np.polyval(np.polyfit(octaves, smooth, 1), octaves)
    return float(np.max(about) - np.min(about)), (low, high)


def _worth_correcting(target: np.ndarray, params: "PipelineParams") -> bool:
    """Whether an evidence-priced target asks for more than the goal tolerance anywhere."""
    return float(np.max(target)) > params.accept.goal_tolerance_db


def _held_below_floor(
    target: np.ndarray, floor_hz: float
) -> tuple[np.ndarray, list[str]]:
    """Hold a target flat below the tracking floor, never above its own value there.

    Below the floor nothing tracks the passband, so there is nothing to recover: the boost is
    held at its value at the floor rather than chasing a curve that describes noise. Temporal
    contrast alone licenses up to 14 dB more down there on real titles (IMPROVEMENT_PLAN E5),
    so this is the only place the tracking evidence reaches a target.
    """
    notes: list[str] = []
    if math.isnan(floor_hz):
        return target, notes
    below = DESIGN_GRID < floor_hz
    if not below.any():
        return target, notes
    held = float(np.interp(floor_hz, DESIGN_GRID, target))
    withheld = float(np.max(target[below])) - held
    # The hold cannot exceed the local measured deficit.
    over_by = float(np.max(held - target[below]))
    target = np.where(below, np.minimum(held, target), target)
    if withheld >= 0.5:
        notes.append(
            f"noise floor binds: the target asks for a further {withheld:.1f} dB below "
            f"{floor_hz:.1f} Hz, held flat because nothing down there tracks the passband"
        )
    if over_by >= 0.5:
        notes.append(
            f"noise-floor hold capped at the local target below {floor_hz:.1f} Hz: "
            f"the flat hold at {held:.1f} dB would have exceeded it by up to "
            f"{over_by:.1f} dB"
        )
    return target, notes


def priced_by_evidence(
    target: np.ndarray,
    envelopes,
    diagnosis: Diagnosis,
    params: "PipelineParams",
    deficit_db: np.ndarray | None = None,
) -> tuple[np.ndarray, list[str]]:
    """Bound a target by every piece of evidence, the same way for every strategy.

    In order: held flat below the tracking floor (`_held_below_floor`); capped at the mix's
    measured low-end deficit, when `deficit_db` is given (`low_end_deficit_db`); clipped to peak–quiet
    contrast minus its uncertainty, where missing or excluded bins license zero boost. The
    result is the target passed to fitting.

    Only `flatten` used to get the first two. A model inversion or a channel restoration
    handed straight to the ceiling asked for 10 dB more than `flatten` below the floor of 28
    Years Later, and a parametric target reached 1.54 times the measured deficit on Send Help
    — the ambition IMPROVEMENT_PLAN E3 found selection rewarding.
    """
    target, notes = _held_below_floor(target, diagnosis.noise_floor_hz)
    if deficit_db is not None:
        excess = target - deficit_db
        worst = int(np.argmax(excess))
        if excess[worst] > 0.5:
            notes.append(
                f"deficit cap binds: the target asks for {target[worst]:.1f} dB at "
                f"{DESIGN_GRID[worst]:.1f} Hz, where the mix is {deficit_db[worst]:.1f} dB "
                "below its reference"
            )
        target = np.minimum(target, deficit_db)
    native_ceiling = envelopes.boost_ceiling(params.confidence_z)
    ceiling = np.interp(
        DESIGN_GRID, envelopes.freqs, native_ceiling, left=0.0, right=0.0
    )
    ceiling[~unexcluded(DESIGN_GRID, params.exclude_bands_hz)] = 0.0
    # which bins failed or lacked evidence is a property of the run, not of this target, and
    # `analyse` already reports it once in the run's limitations
    clipped = target - ceiling
    worst_bin = int(np.argmax(clipped))
    if clipped[worst_bin] > 0.5:
        notes.append(
            f"boost cap binds: the target claims {target[worst_bin]:.1f} dB at "
            f"{DESIGN_GRID[worst_bin]:.1f} Hz; the measured margin supports "
            f"{ceiling[worst_bin]:.1f} dB there at {params.confidence_z:.2g} standard "
            "errors of confidence"
        )
    return np.clip(target, 0.0, ceiling), notes


def flatten_targets(
    material: Material,
    diagnosis: Diagnosis,
    envelopes,
    identification: "Identification | None",
    params: "PipelineParams",
) -> list[Proposal]:
    """Request enough boost to reach the mix's own spectral plateau.

    The plateau-relative deficit, tapered where it closes, then priced — held below the
    tracking floor and clipped to measured contrast — like every other strategy's target.
    """
    unpriced = low_end_deficit_db(material, params)
    if unpriced is None:
        return []
    target, notes = priced_by_evidence(unpriced, envelopes, diagnosis, params, unpriced)
    if not _worth_correcting(target, params):
        return []
    return [
        Proposal(
            "flatten", target_db=target, unpriced_target_db=unpriced, notes=tuple(notes)
        )
    ]


def counterfactual_targets(
    material: Material,
    diagnosis: Diagnosis,
    envelopes,
    identification: "Identification | None",
    params: "PipelineParams",
) -> list[Proposal]:
    """Build priced mix targets from individually restored channels.

    Try each restoration cap, re-sum the channels, price the resulting mix
    deficit by contrast, and deduplicate targets before fitting.
    """
    if not diagnosis.filtered_channels:
        return []
    # Reuse channel spectra across restoration caps.
    restoration = _Restoration(material, diagnosis, params.playback)
    deficit = low_end_deficit_db(material, params)
    proposals: list[Proposal] = []
    for cap in params.restore_caps_db:
        unpriced = counterfactual_target(material, diagnosis, cap, params, restoration)
        target, capped = priced_by_evidence(
            unpriced, envelopes, diagnosis, params, deficit
        )
        if not _worth_correcting(target, params):
            logger.info(
                f"  cap {cap:.0f} dB: within {params.accept.goal_tolerance_db:g} dB of the "
                "goal, nothing to correct"
            )
            continue
        # Skip caps that produce the same priced target.
        for seen in proposals:
            if np.allclose(seen.target_db, target, atol=1e-6):
                logger.info(
                    f"  cap {cap:.0f} dB: target identical to {seen.label}; not refitting"
                )
                break
        else:
            proposals.append(
                Proposal(
                    f"counterfactual/{cap:.0f}dB",
                    target_db=target,
                    unpriced_target_db=unpriced,
                    notes=tuple(capped),
                )
            )
    return proposals


def parametric_params(params: PipelineParams) -> DesignParams:
    """The effective configuration used by both parametric derivation and its cache key."""
    return DesignParams(
        max_boost_db=params.parametric_max_boost_db,
        max_drift_db=params.accept.max_drift_db,
        max_gain_db=params.max_gain_db,
        max_sections=params.max_sections,
        residual_target_db=params.residual_target_db,
        residual_band_hz=params.residual_band_hz,
        confidence_z=params.confidence_z,
        lowest_frequency_hz=params.lowest_frequency_hz,
        realisation=params.realisation,
        fit_seeds=params.fit_seeds,
    )


def parametric_targets(
    material: Material,
    diagnosis: Diagnosis,
    envelopes,
    identification: "Identification | None",
    params: "PipelineParams",
) -> list[Proposal]:
    """Propose the identified rolloff's protected and evidence-priced inverse."""
    if identification is None or not identification.detected:
        return []
    deficit = low_end_deficit_db(material, params)
    result = design(
        identification,
        envelopes,
        parametric_params(params),
        price_target=lambda target: priced_by_evidence(
            target, envelopes, diagnosis, params, deficit
        ),
    )
    if not result.filters:
        logger.info(f"  parametric declined: {result.decline_reason}")
        return []
    if result.target_db is not None and not _worth_correcting(result.target_db, params):
        logger.info("  parametric: within the goal tolerance, nothing to correct")
        return []
    return [
        Proposal(
            "parametric",
            filters=result.filters,
            residual_db=result.residual_db,
            target_db=result.target_db,
            unpriced_target_db=result.unpriced_target_db,
            method=result.method,
            notes=result.target_notes,
            effective_params=repr(parametric_params(params)),
        )
    ]


@dataclass(frozen=True, slots=True)
class Strategy:
    """One way of deriving a target, and what deriving it costs to repeat.

    `cache_modules` is what a strategy declares when its *derivation* is expensive enough to be
    worth keeping — the module set its output depends on, so the cache knows when to drop it.
    `None` means derive it every time, which is right for a strategy that is a few hundred
    milliseconds of deterministic numpy.
    """

    derive: "Callable[..., list[Proposal]]"
    cache_modules: tuple[str, ...] | None = None
    effective_params: Callable[[PipelineParams], object] = lambda params: params
    """Settings consumed by derivation; also the configuration component of its cache key."""


STRATEGIES = {
    "flatten": Strategy(flatten_targets),
    "counterfactual": Strategy(counterfactual_targets),
    "parametric": Strategy(
        parametric_targets, cache.PARAMETRIC_MODULES, parametric_params
    ),
}
"""Every way of deriving a target, by name. All equal citizens of the same pipeline.

`parametric` is the one that caches, because it is the one whose target derivation runs an
optimiser: it calls `design`, which calls the fitter, and that is more than any other single
stage of a run. What it contributes is a statement about
the *material* — does this look like a deliberate rolloff, of what alignment and order — which
does not change between runs of the same code over the same title. `flatten` and
`counterfactual` derive a curve directly and are not worth the round trip.
"""


@dataclass(frozen=True, slots=True)
class _Restoration:
    """What restoring a channel needs that does not depend on how far it is restored.

    The spectrum of each filtered channel, the bin axis, and the mix's own reference curve.
    A cap changes only the ceiling applied to the boost, so recomputing these per cap was
    three forward and three inverse transforms of a two-hour signal for one answer.
    """

    spectra: dict[str, np.ndarray]
    bins: np.ndarray
    before_db: np.ndarray
    mix: np.ndarray
    """The mix a restored channel is re-summed into — see `_restoration_mix`."""
    gains: dict[str, float]
    """Each channel's weight in `mix`."""
    length: int
    """Transform length: the programme zero-padded to a length the FFT factors quickly.

    Unpadded, the length is whatever the programme happens to be, and a two-hour title can
    factor as 2*3*613*1741 or 7*7*144779 — pocketfft's slow path, measured at 1.9 s a transform
    and 86 s for one title's counterfactual targets. Padding (typically by under 1%) takes that
    to about 0.1 s. It changes the restoration only at the programme's ends, where the
    zero-phase gain's circular wrap now reads zeros instead of the other end of the film."""

    def __init__(
        self,
        material: Material,
        diagnosis: Diagnosis,
        playback: PlaybackParams | None = None,
    ) -> None:
        mix, gains = _restoration_mix(material, playback or PlaybackParams())
        object.__setattr__(self, "mix", mix)
        object.__setattr__(self, "gains", gains)
        length = scipy.fft.next_fast_len(len(mix), real=True)
        spectra = {
            name: np.fft.rfft(material.channels[name], length)
            for name in diagnosis.filtered_channels
        }
        object.__setattr__(self, "spectra", spectra)
        object.__setattr__(self, "length", length)
        object.__setattr__(
            self,
            "bins",
            np.fft.rfftfreq(length, 1.0 / material.fs),
        )
        object.__setattr__(self, "before_db", mean_spectrum(mix, material.fs)[1])


def _restoration_mix(
    material: Material, playback: PlaybackParams
) -> tuple[np.ndarray, dict[str, float]]:
    """The mix a counterfactual restoration is re-summed into, and each channel's weight in it.

    `material.mono_mix` carries §2's fixed weights. The deficit a restoration reads is a
    question about the sub feed the playback model describes, so when that model weights the
    LFE against the mains differently, the mix is rebuilt from the channels at the model's
    gains. Only the ratio matters — the deficit is read against the mix's own plateau, so a
    common gain cancels — and at §2's ratio the stored mix is used exactly as it stands.
    """
    stored_ratio_db = 20.0 * math.log10(LFE_GAIN / MAIN_GAIN)
    if math.isclose(
        playback.lfe_gain_db - playback.main_gain_db, stored_ratio_db, abs_tol=1e-9
    ):
        return material.mono_mix, {
            name: LFE_GAIN if name == "LFE" else MAIN_GAIN for name in material.channels
        }
    gains = {
        name: 10.0
        ** ((playback.lfe_gain_db if name == "LFE" else playback.main_gain_db) / 20.0)
        for name in material.channels
    }
    mix = np.zeros_like(material.mono_mix, dtype=np.float64)
    for name, samples in material.channels.items():
        mix += gains[name] * samples
    return mix, gains


def counterfactual_target(
    material: Material,
    diagnosis: Diagnosis,
    restore_cap_db: float,
    params: PipelineParams,
    restoration: "_Restoration | None" = None,
) -> np.ndarray:
    """Mix deficit if the filtered channels had never been filtered.

    The inversion is applied to the channel in isolation and the mix rebuilt, so the answer
    accounts for the other channels continuing to supply whatever they supply. That matters:
    a channel 23 dB under the mains contributes nothing to the sum until it is restored, and
    a target computed on the channel alone would not know that.
    """
    restoration = restoration or _Restoration(material, diagnosis, params.playback)
    freqs = diagnosis.freqs
    restored = restoration.mix.copy()
    for name in diagnosis.filtered_channels:
        samples = material.channels[name]
        response = diagnosis.channels[name].response_db
        boost = np.where(
            unexcluded(freqs, params.exclude_bands_hz) & np.isfinite(response),
            np.clip(-np.minimum(response, 0.0), 0.0, restore_cap_db),
            0.0,
        )
        # A quiet channel must earn its own lift before its increased contribution enters
        # the coherent sum. A clean neighbour never lends its allowance to this channel.
        boost = np.minimum(
            boost,
            diagnosis.channels[name].boost_allowance(
                params.confidence_z, params.diagnose.tracking_floor
            ),
        )
        if not np.any(boost > 0):
            continue
        # restoration stops at this channel's own plateau, since that is what its response
        # was referenced to — a common cutoff would restore one channel into its passband
        # while stopping another short of its knee
        knee = freqs > diagnosis.channels[name].plateau_hz[0]
        boost = np.where(knee, 0.0, boost)
        spectrum = restoration.spectra[name]
        gain = np.interp(restoration.bins, freqs, boost, left=boost[0], right=0.0)
        gain[~unexcluded(restoration.bins, params.exclude_bands_hz)] = 0.0
        lifted = np.fft.irfft(spectrum * 10.0 ** (gain / 20.0), n=restoration.length)[
            : len(samples)
        ]
        restored = restored + restoration.gains[name] * (lifted - samples)

    before = restoration.before_db
    grid, deficit = supported_mix_change(
        restoration.mix, restored, material.fs, params.confidence_z
    )
    deficit[~unexcluded(grid, params.exclude_bands_hz)] = 0.0
    target = np.interp(DESIGN_GRID, grid, deficit, left=deficit[0], right=0.0)
    target = smooth_unexcluded(target, DESIGN_GRID, params.exclude_bands_hz, 9)
    _, plateau_hz = plateau_reference(
        before, grid, params.diagnose, params.exclude_bands_hz
    )
    anchor = _deficit_anchor(DESIGN_GRID, target, params, plateau_hz)
    target *= _taper(DESIGN_GRID, anchor, params.flatten_taper_ratio)
    target[~unexcluded(DESIGN_GRID, params.exclude_bands_hz)] = 0.0
    return target


def _fit_all(
    proposals: list[Proposal], params: PipelineParams
) -> list[tuple[list[BiquadSpec], float]]:
    """Fit all proposed targets under a shared section escalation.

    Derive each target's placement span from its active correction, expand the
    scored band to cover those spans, and return the fitted cascades in order.
    """
    placements = [
        correction_band_hz(p.target_db, DESIGN_GRID, params.lowest_frequency_hz)
        for p in proposals
    ]
    # Score every frequency at which a section can be placed.
    score_high = max(params.residual_band_hz[1], *(high for _, high in placements))
    return fit_minimal_biquads_all(
        [
            FitRequest(p.target_db, placement, p.label)
            for p, placement in zip(proposals, placements, strict=True)
        ],
        DESIGN_GRID,
        PUBLISH_FS,
        params.max_sections,
        params.residual_target_db,
        band_hz=(params.residual_band_hz[0], score_high),
        max_gain_db=params.max_gain_db,
        realisation=params.realisation,
        seeds=params.fit_seeds,
        max_drift_db=params.accept.max_drift_db,
    )


@dataclass(frozen=True, slots=True)
class Analysed:
    """Everything `run` knows before any strategy proposes a target.

    `params` is the run's effective configuration — exclusions merged into every stage — so a
    caller holding this cannot accidentally judge against a different contract than the one
    the analysis used. `blockers` non-empty means the run abstains without proposing anything.
    """

    params: PipelineParams
    identify_params: IdentifyParams
    diagnosis: Diagnosis
    envelopes: Envelopes
    identification: Identification | None
    limitations: tuple[str, ...]
    blockers: tuple[str, ...]
    mix_reference_db: float = math.nan
    mix_plateau_hz: tuple[float, float] = (math.nan, math.nan)
    judged_band_hz: tuple[float, float] | None = None


def analyse(
    material: Material,
    params: PipelineParams | None = None,
    cache_path: Path | None = None,
    fresh: bool = False,
    timings: Timings | None = None,
) -> Analysed:
    """Diagnose, extract and identify (from the stage cache when valid), then list blockers.

    The first half of `run`, separable so a regression probe can read the decisions that
    precede fitting — plateau, floors, judged band, evidence ceiling — without paying for a fit.
    """
    timings = timings or Timings()
    params = params or PipelineParams()
    # One effective exclusion contract at every stage, including directly configured omissions.
    bands = tuple(
        sorted(
            set(
                (
                    *params.exclude_bands_hz,
                    *params.diagnose.exclude_bands_hz,
                    *params.extraction.exclude_bands_hz,
                    *params.identify.exclude_bands_hz,
                )
            )
        )
    )
    unexcluded(DESIGN_GRID, bands)  # validate even when all evidence is unavailable
    params = dataclasses.replace(
        params,
        exclude_bands_hz=bands,
        diagnose=dataclasses.replace(params.diagnose, exclude_bands_hz=bands),
        extraction=dataclasses.replace(params.extraction, exclude_bands_hz=bands),
    )
    unknown = set(params.strategies) - STRATEGIES.keys()
    if unknown:
        raise ValueError(
            f"unknown strategy {sorted(unknown)!r}; have {', '.join(sorted(STRATEGIES))}"
        )
    logger.info("=" * 80)
    logger.info(f"Material: {material}")

    identification: Identification | None = None
    # the run's exclusions are the run's, whichever stage reads the spectrum
    identify_params = dataclasses.replace(
        params.identify,
        exclude_bands_hz=tuple(
            dict.fromkeys((*params.identify.exclude_bands_hz, *params.exclude_bands_hz))
        ),
    )

    analysis_key = (
        None
        if cache_path is None
        else cache.key_for(
            "analysis",
            cache.ANALYSIS_MODULES,
            material,
            params.diagnose,
            params.extraction,
            identify_params,
        )
    )
    stored = (
        None
        if cache_path is None or fresh
        else cache.load(cache_path, "analysis", analysis_key)
    )

    logger.info("=" * 80)
    logger.info("Per-channel decomposition")
    if stored is not None:
        with timings.stage("analysis/cached"):
            analysis = cache.analysis_from_json(stored)
        diagnosis = analysis.diagnosis
        envelopes = analysis.envelopes
        identification = analysis.identification
        for channel in diagnosis.channels.values():
            logger.info(f"  {channel}")
        logger.info(f"Extracted {envelopes}")
        if identification is not None:
            logger.info(f"Identified {identification}")
    else:
        with timings.stage("diagnose"):
            diagnosis = diagnose(material, params.diagnose, params.extraction)

        with timings.stage("extract"):
            envelopes = extract(
                material.mono_mix, float(material.fs), params.extraction
            )
        with timings.stage("identify"):
            try:
                identification = identify_rolloff(envelopes, identify_params)
            except ValueError as unusable:
                logger.warning(f"Sum-based identification unavailable: {unusable}")
        if cache_path is not None:
            cache.store(
                cache_path,
                "analysis",
                analysis_key,
                cache.analysis_to_json(
                    cache.Analysis(diagnosis, envelopes, identification)
                ),
            )

    limitations = evidence_notes(envelopes, params.confidence_z)
    limitations.extend(
        (
            "mastering-rolloff support: unavailable from programme alone; spectral shape and level invariance are non-identifying features",
            "correction support is conditional: quiet frames must represent additive stationary noise, loud frames independent programme events, and tracking must not be stopband leakage",
            "preference shaping: reference-to-plateau restoration assumes the desired original spectrum; temporal contrast is not SNR and bootstrap precision does not validate that assumption",
        )
    )
    blockers = []
    mix_freqs, mix_response = mean_spectrum(material.mono_mix, material.fs)
    mix_level, region = plateau_reference(
        mix_response, mix_freqs, params.diagnose, params.exclude_bands_hz
    )
    if not math.isfinite(mix_level):
        blockers.append("no usable contiguous mix plateau; restoration withheld")
    if material.coverage != "complete_programme":
        blockers.append(
            "excerpt: programme quiet-frame evidence unavailable; restoration withheld"
        )
    if not material.channels:
        blockers.append("channel evidence unavailable; restoration withheld")
        blockers.append("playback verification unavailable: no channel decomposition")
    if not envelopes.loud_frames:
        blockers.append("no qualifying loud events; restoration withheld")
    if not np.any(envelopes.boost_ceiling(params.confidence_z) > 0):
        blockers.append("no bins support a positive correction; restoration withheld")
    judged = None
    if math.isfinite(mix_level):
        limitations.append(
            f"mix reference: contiguous plateau {region[0]:.3f}-{region[1]:.3f} Hz, "
            f"median {mix_level:.6f} dB; shared by targets and verification"
        )
        # A BEQ acts on the sub feed. A reference that starts above the band the sub plays is
        # not a bass passband, so a deficit read against it is the shape of whatever carries
        # the mix up there — typically a dialogue-led mix with no authored bass, where the
        # centre carries the plateau and the LFE is empty — not a rolloff to restore.
        sub_edge = min(
            corner
            for corner in (params.playback.crossover_hz, params.playback.bus_lowpass_hz)
            if corner is not None
        )
        if region[0] >= sub_edge:
            blockers.append(
                "no usable contiguous mix plateau in the band the sub plays: the mix's only "
                f"flat region is {region[0]:.1f}-{region[1]:.1f} Hz, above the "
                f"{sub_edge:g} Hz sub-feed low-pass, so there is no bass passband to restore "
                "towards; restoration withheld"
            )
        texture = passband_ripple_db(material, params)
        low_end = low_end_deficit_db(material, params)
        if texture is not None and low_end is not None:
            ripple, (edge_low, edge_high) = texture
            deepest = float(np.max(low_end))
            if deepest <= ripple:
                blockers.append(
                    "within the programme's own ripple: the low end's deepest shortfall "
                    f"({deepest:.1f} dB) is no larger than the {ripple:.1f} dB crest-to-trough "
                    f"swing of the passband above it ({edge_low:.0f}-{edge_high:.0f} Hz), "
                    "so it is texture, not a missing low end; restoration withheld"
                )
    if math.isfinite(mix_level):
        judged = judged_band_hz(material, diagnosis, params)
        if any(a <= judged[1] and b >= judged[0] for a, b in bands):
            blockers.append(
                "exclusions fragment the judged band; contiguous verification unavailable"
            )
    if bands:
        limitations.append(
            f"authored exclusions {bands}: omitted evidence, zero requested correction"
        )
    if not blockers:
        sub = bass_managed_sum(material, playback=params.playback)
        if sub is None or not np.any(sub):
            blockers.append(
                "playback verification unavailable: silent or absent sub feed"
            )
    limitations.append(params.playback.description())
    limitations.extend(blockers)
    for note in limitations:
        logger.info(note)
    return Analysed(
        params=params,
        identify_params=identify_params,
        diagnosis=diagnosis,
        envelopes=envelopes,
        identification=identification,
        limitations=tuple(limitations),
        blockers=tuple(blockers),
        mix_reference_db=mix_level,
        mix_plateau_hz=region,
        judged_band_hz=judged,
    )


def propose(
    material: Material,
    analysed: Analysed,
    cache_path: Path | None = None,
    fresh: bool = False,
    timings: Timings | None = None,
) -> list[Proposal]:
    """Every selected strategy's proposals, each carrying the notes on what bound its target."""
    timings = timings or Timings()
    params = analysed.params
    diagnosis = analysed.diagnosis
    envelopes = analysed.envelopes
    identification = analysed.identification
    identify_params = analysed.identify_params
    logger.info("=" * 80)
    logger.info(f"Strategies: {', '.join(params.strategies)}")
    proposals: list[Proposal] = []
    for name in params.strategies:
        strategy = STRATEGIES.get(name)
        if strategy is None:
            raise ValueError(
                f"unknown strategy {name!r}; have {', '.join(sorted(STRATEGIES))}"
            )
        key = (
            None
            if cache_path is None or strategy.cache_modules is None
            else cache.key_for(
                name,
                strategy.cache_modules,
                material,
                params.diagnose,
                params.extraction,
                identify_params,
                strategy.effective_params(params),
            )
        )
        held = None if key is None or fresh else cache.load(cache_path, name, key)
        if held is not None:
            with timings.stage(f"target/{name} (cached)"):
                produced = cache.proposals_from_json(held, Proposal)
        else:
            with timings.stage(f"target/{name}"):
                produced = strategy.derive(
                    material, diagnosis, envelopes, identification, params
                )
                produced = [
                    dataclasses.replace(
                        p, effective_params=repr(strategy.effective_params(params))
                    )
                    for p in produced
                ]
            if key is not None:
                cache.store(cache_path, name, key, cache.proposals_to_json(produced))
        logger.info(f"  {name}: {len(produced)} proposal(s)")
        # a proposal's notes are what bound *its* target; the run's limitations live once, on
        # `Report.evidence_notes`, and the designer response joins the two itself
        proposals.extend(produced)
    return proposals


def run(
    material: Material,
    params: PipelineParams | None = None,
    cache_path: Path | None = None,
    fresh: bool = False,
) -> Report:
    """Run diagnosis, evidence-priced target strategies, fitting and acceptance.

    Refuse proposals when programme coverage or spectral evidence is missing.
    Cache reusable analysis by material, parameters and source hashes; publish
    each fitted cascade before verifying it on the modelled sub feed.
    """
    timings = Timings()
    FIT_STATS.reset()
    analysed = analyse(material, params, cache_path, fresh, timings)
    params = analysed.params
    diagnosis = analysed.diagnosis
    envelopes = analysed.envelopes
    identification = analysed.identification
    if analysed.blockers:
        return Report(
            material,
            diagnosis,
            identification,
            [],
            timings,
            FIT_STATS,
            accept=params.accept,
            evidence_notes=analysed.limitations,
            mix_reference_db=analysed.mix_reference_db,
            mix_plateau_hz=analysed.mix_plateau_hz,
            judged_band_hz=analysed.judged_band_hz,
            blockers=analysed.blockers,
        )
    proposals = propose(material, analysed, cache_path, fresh, timings)
    if not proposals:
        # the reason to abstain, said as one: no strategy found anything worth correcting
        within = (
            "nothing worth correcting: no strategy's evidence-priced target departs from the "
            f"goal by more than {params.accept.goal_tolerance_db:g} dB"
        )
        return Report(
            material,
            diagnosis,
            identification,
            [],
            timings,
            FIT_STATS,
            accept=params.accept,
            evidence_notes=(*analysed.limitations, within),
            mix_reference_db=analysed.mix_reference_db,
            mix_plateau_hz=analysed.mix_plateau_hz,
            judged_band_hz=analysed.judged_band_hz,
            blockers=(within,),
        )

    needs_fitting = [p for p in proposals if p.filters is None]
    with timings.stage("fit"):
        results = _fit_all(needs_fitting, params) if needs_fitting else []
    fitted = dict(
        zip(
            [p.label for p in needs_fitting],
            results,
            strict=True,
        )
    )

    candidates: list[Candidate] = []
    for proposal in proposals:
        if proposal.filters is not None:
            filters, error = proposal.filters, proposal.residual_db
        else:
            filters, error = fitted[proposal.label]
        with timings.stage(f"judge/{proposal.label}"):
            candidates.append(
                _judge(
                    proposal.label,
                    filters,
                    proposal.target_db,
                    error,
                    material,
                    diagnosis,
                    params,
                    proposal.notes,
                    unpriced_target=proposal.unpriced_target_db,
                    method=proposal.method,
                    effective_params=proposal.effective_params,
                    judged_band=analysed.judged_band_hz,
                )
            )

    candidates = [
        dataclasses.replace(
            c,
            correction_support_score=correction_evidence_score(
                c.target_db, envelopes, params.confidence_z
            ),
        )
        for c in candidates
    ]
    logger.info(f"Fitting cost: {FIT_STATS}")
    return Report(
        material=material,
        diagnosis=diagnosis,
        identification=identification,
        candidates=candidates,
        timings=timings,
        fit_stats=FIT_STATS,
        accept=params.accept,
        evidence_notes=analysed.limitations,
        mix_reference_db=analysed.mix_reference_db,
        mix_plateau_hz=analysed.mix_plateau_hz,
        judged_band_hz=analysed.judged_band_hz,
    )


def measure_headroom(
    material: Material,
    filters: list[BiquadSpec],
    params: PipelineParams,
    *,
    sub_samples: np.ndarray | None = None,
) -> Headroom:
    """Measure peak clipping after the published cascade on the sub feed.

    Apply the quantised device transfer to the bass-managed waveform and
    report the non-positive gain offset needed to keep its peak below full scale.
    """
    sub = (
        sub_samples
        if sub_samples is not None
        else bass_managed_sum(material, playback=params.playback)
    )
    reason = None
    peak = None
    offset = math.nan
    if sub is None:
        reason = "no channel decomposition"
    elif not np.isfinite(sub).all():
        reason = "non-finite sub-feed samples"
    else:
        try:
            filtered = device_waveform(
                filters, sub, float(material.fs), params.realisation, include_tail=True
            )
            if not np.isfinite(filtered).all():
                raise ValueError("non-finite device waveform")
            peak = waveform_peak(filtered)
            offset = min(-20.0 * math.log10(peak), 0.0) if peak > 0 else 0.0
        except ValueError as unavailable:
            reason = str(unavailable)
            logger.warning(f"Headroom unavailable: {reason}")
    return Headroom(
        offset, peak, params.playback, params.realisation, float(material.fs), reason
    )


def required_gain_reduction_db(
    material: Material, filters: list[BiquadSpec], params: PipelineParams
) -> float:
    """Compatibility scalar; `measure_headroom` also retains assumptions and unavailable reasons."""
    return measure_headroom(material, filters, params).offset_db


def judged_band_hz(
    material: Material, diagnosis: Diagnosis, params: PipelineParams
) -> tuple[float, float]:
    """Set one verification band from mix evidence for all candidates.

    Start no lower than the mix tracking floor; extend the upper edge to the
    first settled end of its plateau-relative deficit. A shared band keeps
    candidate shape measurements comparable.
    """
    low = params.verify_band_hz[0]
    floor = diagnosis.noise_floor_hz
    if not math.isnan(floor):
        low = max(low, floor)
    measured = _flat_deficit(material, params)
    if measured is None:
        raise ValueError("no usable contiguous mix plateau")
    return low, _judged_top_hz(measured[-1], params)


def _judge(
    label: str,
    filters: list[BiquadSpec],
    target: np.ndarray | None,
    error: float,
    material: Material,
    diagnosis: Diagnosis,
    params: PipelineParams,
    target_notes: tuple[str, ...] = (),
    unpriced_target: np.ndarray | None = None,
    method: DesignMethod | None = None,
    effective_params: str | None = None,
    judged_band: tuple[float, float] | None = None,
) -> Candidate:
    """Publish, verify and assess one proposed cascade.

    Round its parameters, apply the quantised device response to the sub feed,
    measure headroom, then test the corrected curve against both the priced
    target and material-based safeguards.
    """
    optimiser_filters = filters
    filters = publication_filters(filters)
    sub = bass_managed_sum(material, playback=params.playback)
    if sub is None:
        raise ValueError("playback verification unavailable: no channel decomposition")
    correction = verify(
        filters,
        sub,
        float(material.fs),
        # the same for every candidate, so `run` passes the one `analyse` found
        band_hz=judged_band or judged_band_hz(material, diagnosis, params),
        diagnose_params=params.diagnose,
        exclude_bands_hz=params.exclude_bands_hz,
        accept_params=params.accept,
        realisation=params.realisation,
        priced_target_db=target,
        reference_samples=material.mono_mix,
        playback_model=params.playback.description(),
    )
    headroom = measure_headroom(material, filters, params, sub_samples=sub)
    verdict = assess(
        filters,
        correction,
        diagnosis.noise_floor_hz,
        params.accept,
        params.realisation,
        filter_floor_hz=diagnosis.filter_floor_hz,
        required_offset_db=headroom.offset_db,
        target_db=target,
        # the band `_fit_all` let this target's sections be placed in: a section is credited
        # for work the fitter asked of it, not only for work inside the judged band
        contribution_band_hz=(
            None
            if target is None
            else correction_band_hz(target, DESIGN_GRID, params.lowest_frequency_hz)
        ),
    )
    verdict.notes.append(
        f"verification transfer: published quantised device at {params.realisation.fs:g} Hz; "
        f"sub output from {material.fs:g} Hz extraction, relative to unchanged playback baseline; "
        "headroom uses the same transfer with ring-out and 16x peak interpolation"
    )
    verdict.notes.append(headroom.summary())
    verdict.notes.append(headroom.assumptions())
    logger.info(f"  {label}: {verdict}")
    for note in target_notes:
        logger.info(f"    {note}")
    return Candidate(
        label=label,
        filters=filters,
        target_db=target if target is not None else np.zeros_like(DESIGN_GRID),
        unpriced_target_db=unpriced_target,
        fit_error_db=error,
        optimiser_filters=optimiser_filters,
        correction=correction,
        verdict=verdict,
        headroom=headroom,
        target_notes=target_notes,
        method=method,
        effective_params=effective_params,
    )
