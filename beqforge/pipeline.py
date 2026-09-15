"""The repeatable process: material in, a judged filter and its reasoning out.

A **target** is a curve to be realised; a **strategy** is one way of deriving one. Each is a
first-class citizen — they are run through the same fitter and the same acceptance model, so
their outputs are directly comparable, and any of them may be selected, combined, or all run
at once with the best surviving candidate taken. They disagree usefully, and a disagreement
is evidence about the material rather than a problem to be resolved by picking a favourite.

* **`flatten`** — invert the measured mix response. The rule the human-validated filters on
  all three titles turned out to represent: the shape a good correction produces is flat to
  the bottom of the evidence, and the target is simply the mix's own curve negated. Needs no
  model of the rolloff and no `N`/`A` separation, which is the part §0 calls the weak link.
* **`counterfactual`** — restore the filtered channels, re-sum, read the deficit off the mix.
  The route that answered title 2, where the sum carries no usable evidence below ~15 Hz
  because the filtered channel is 23 dB under the mains there.
* **`parametric`** — `identify_rolloff` on the mono mix and invert the fitted rolloff (§3.5).
  The soft-hinge route; the only one that can produce an exact closed-form inversion when the
  alignment is representable, which on the three titles so far it never was.

`flatten` is validated only on modern, bass-rich material. On a sparse or old mix, flattening
would lift the noise floor with the content, and nothing in the target itself objects — that
is what the guard is for. `diagnose`'s level-independence test, band tracking and noise floor
bound how far down a correction may reach and say when to abstain; they are not on the path to
producing a target.

Candidates are judged against §6.4 and the survivors ranked. The ranking is deliberately
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

from beqanalyser.design import DESIGN_GRID, BiquadSpec
from beqanalyser.design import cache
from beqanalyser.design.accept import (
    AcceptParams,
    Verdict,
    assess,
    confidence_from_evidence,
)
from beqanalyser.design.design import DesignMethod, DesignParams, design
from beqanalyser.design.diagnose import (
    Diagnosis,
    DiagnoseParams,
    diagnose,
    mean_spectrum,
    plateau_reference,
    smooth_unexcluded,
    unexcluded,
)
from beqanalyser.design.extraction import ExtractionParams, extract
from beqanalyser.design.filters import (
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
from beqanalyser.design.identify import IdentifyParams, Identification, identify_rolloff
from beqanalyser.design.material import (
    LFE_GAIN,
    MAIN_GAIN,
    Material,
    bass_managed_sum,
)
from beqanalyser.design.verify import Correction, device_waveform, verify, waveform_peak

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

    Measured, the mix plateau begins at 13.9, 18.3, 21.6 and 32.3 Hz across the four titles.
    40 Hz fell inside all four, so the old constant was not yet wrong — but by only 1.24x on
    the fourth, and a title with a knee near 50 Hz would have been levelled inside its own
    rolloff.

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

    50 added on Predator, the title the original three could not close: 45 dB still fell at
    2.8 dB/oct (`max_tilt_db_per_octave` is 2.0), 50 dB reached the plateau and passed outright
    — and 55/60/70 dB all produced the *identical* target, so 50 is not an arbitrary stop, it
    is where this channel's own measured attenuation runs out. Cheap to try even where it does
    nothing: a cap whose target matches an earlier one is deduplicated before fitting."""

    max_sections: int = 4
    """Ceiling on biquads a fit may spend, escalated from 1 up to this (`_tiers`).

    Tried at `BIQUAD_BUDGET` (10, designer-interface.md v1.0 §5) on the theory that a title
    exhausting 4 sections without settling was budget-starved rather than shape-limited.
    Measured on Predator, the one real title that both exhausts the budget and has the most
    to gain: `counterfactual/25dB` spent the extra room, settling at 5 sections instead of 4,
    and failed on the *same* comparative checks anyway — "still falls at 11.7 dB/oct —
    under-corrected; corrected level -9.6 dB is outside -3..+8" is not a section-count
    problem. Every other candidate hit its identical wall at whatever section count it tried.
    Cost was not proportionate to that answer: 997 s against 70 s, 265 optimiser runs against
    40, for the same abstention — PERFORMANCE.md §1.1's "`max_sections=5` would roughly
    double a run" was, if anything, optimistic about 10.

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
    it (§4.1) — one-sided ~95% at the default.

    Replaces a flat `noise_margin_db`. That constant could not distinguish 1,300 loud frames
    drawn from hundreds of separate scenes from 11 that are each their own isolated instant —
    both got the same 12 dB haircut. `Envelopes.margin_se_db` is a block bootstrap over
    exactly that evidence (contiguous runs, not raw frames, because a 50%-overlapping frame
    pair is not two independent observations), so the ceiling now tightens where the estimate
    itself is shaky and relaxes where it is not, per bin per title, instead of asserting one
    number for every extraction. Checked against all eight titles on hand: the derived
    ceiling came out looser than the old flat one everywhere the evidence was solid, and did
    what the flat one could not on the one title with almost none of it (Nocturnal Animals,
    10 independent loud events) — SE there ran 4-8x every other title's, and the ceiling
    tightened accordingly without being told to.

    Missing or deliberately omitted measurements license no boost."""

    fit_seeds: tuple[int, ...] = (0,)
    """Seeds the fit is repeated from at each section count and split.

    One. `fit_to_biquads` warns that the objective is multimodal and that results "vary by an
    order of magnitude between seeds" — but that was measured on the *parametric* route's
    targets, a high-order rolloff terminated by a much lower-order protective filter spanning
    100 dB. The targets that produce every accepted filter are `flatten`'s, and on those a
    second seed bought little enough to be measurable: see PERFORMANCE.md P13. That was
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

    @property
    def mv_adjust_db(self) -> float:
        """Master-volume reduction the cascade requires; positive means turn down.

        Taken from the cascade rather than the target: the target is not defined for every
        route, and it is the published filter's peak gain that the listener has to make room
        for regardless of how it was arrived at.
        """
        sos = biquad_sos(self.filters, PUBLISH_FS)
        return float(np.max(magnitude_db(sos, DESIGN_GRID, PUBLISH_FS)))

    @property
    def confidence(self) -> float:
        """Uncalibrated evidence score, with fit quality excluded.

        `confidence_from_evidence` on this candidate's own `verdict.recovered_fraction` and
        `verdict.shaping_fraction` (§14.3). An ordinal within this run, not a calibrated
        probability — see that function's docstring."""
        return confidence_from_evidence(
            self.verdict.recovered_fraction, self.verdict.shaping_fraction
        )


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
    Two of the three titles with more than one passing candidate are genuine ties by this
    measure: Nocturnal Animals at 2.47 against 2.49 dB and Tron at 1.32 against 1.34, where
    preferring the lower number is preferring noise. Title 3's pair sit 1.54 against 4.27 and
    are not a tie at all."""

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
        blind to level and tilt, which acceptance admits across an 11 dB and 4.5 dB/octave
        range respectively, and the margins it decided on were 0.08-0.23 dB of a quantity
        whose own scatter is 3-14 dB. On title 3 that preferred a candidate 3.70 dB above
        plateau to one 0.36 dB below it, for 0.09 dB of wobble and one fewer section.
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
    """Where `flatten`'s correction stops — the first upward crossing into nothing.

    The target has to stop somewhere or the mix's own high-frequency fall is read as a deficit
    (§3.4a). Stopping it with a hard zero left a step of 0.58-1.08 dB across one 0.55 Hz grid
    point, inside the band the residual is scored over, and no biquad cascade follows a step
    that narrow — so the minimax residual was bounded below by half of it and the fit could
    never stop early. The taper is that fix; this is where to put it.

    Scanned upward from the bottom so only the *first* zero counts. A deficit measured against
    a plateau level necessarily returns above the plateau's top, and that return is programme,
    not deficit.
    """
    keep = unexcluded(grid, params.exclude_bands_hz)
    over = (deficit_db >= params.flatten_deficit_floor_db) & keep
    if not over.any():
        # nothing to correct anywhere; the caller discards the proposal on max() < 1 dB
        return float(plateau_hz[0])
    # a sustained run below the floor, not one point under it. A mix wobbles around its own
    # plateau by several dB (§6.4), so a single crossing is the material's roughness rather
    # than the end of the correction, and stopping on one would truncate the target in a dip.
    # Same reasoning as `_lowest_run` in `diagnose`.
    run = max(1, int(round(len(grid) * params.flatten_settled_octaves / _GRID_OCTAVES)))
    first = int(np.argmax(over))
    settled = np.convolve(
        ((~over & keep)[first:]).astype(float), np.ones(run), mode="valid"
    )
    closed = np.flatnonzero(settled >= run)
    if closed.size:
        return float(grid[first + int(closed[0])])
    # the deficit never closes inside the band — the plateau's lower edge is the last honest
    # statement about where the mix stops being short, so stop there rather than off the end
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


def priced_by_evidence(
    target: np.ndarray,
    envelopes,
    diagnosis: Diagnosis,
    params: "PipelineParams",
) -> tuple[np.ndarray, list[str]]:
    """Clip a target to the boost each bin's own measured margin supports.

    Per-bin, at `confidence_z` standard errors, independent of what any other bin or title needs.
    Unsupported bins license zero boost, including profiling omissions. The noise-floor
    hold must not expand this allowance: it bounds target construction, not evidence.
    """
    native_ceiling = envelopes.boost_ceiling(params.confidence_z)
    ceiling = np.interp(
        DESIGN_GRID, envelopes.freqs, native_ceiling, left=0.0, right=0.0
    )
    ceiling[~unexcluded(DESIGN_GRID, params.exclude_bands_hz)] = 0.0
    # Per-bin, not global: a target whose *peak* sits under the ceiling's peak can still be
    # clipped somewhere else entirely. Measured on Alien — target.max() (35 dB, near 22 Hz)
    # never exceeded noise_ceiling.max() (42 dB, near 30 Hz), so this note was silent while
    # 5-17 Hz was being held 10-12 dB below its raw deficit the whole time. The bin with the
    # worst clip is the one worth naming, not the target's own unrelated peak.
    notes = evidence_notes(envelopes, params.confidence_z)
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
    """Invert the measured mix response — make it flat.

    The three human-validated filters track this within 2-4 dB, and the residual is a
    near-constant offset rather than a shape error: one sits ~3 dB above flat, the other two
    ~2 dB below. Flat is the shape; how far past flat to go is the preference dial of §4.3.
    """
    freqs, response = mean_spectrum(material.mono_mix, material.fs)
    # "flat" means the mix's own plateau, measured on the mix, not a level read off one
    # nominated frequency. A point reference also inherits whatever local wobble sits at that
    # point: across the four titles the plateau level and the level at 40 Hz differ by -2.5 to
    # +2.8 dB, which is a straight offset on the whole target.
    level, plateau_hz = plateau_reference(
        response, freqs, params.diagnose, params.exclude_bands_hz
    )
    if not math.isfinite(level):
        return []
    response = response - level
    deficit = smooth_unexcluded(
        np.maximum(-response, 0.0), freqs, params.exclude_bands_hz, 15
    )

    target = np.interp(DESIGN_GRID, freqs, deficit, left=deficit[0], right=0.0)
    anchor = _deficit_anchor(DESIGN_GRID, target, params, plateau_hz)
    # Tapered to nothing above the reference, not cut off there. The mix keeps falling above
    # the reference — by 5 to 11.6 dB over 45-200 Hz on the three titles — and that fall is
    # the programme, not a deficit, so the target has to stop. Stopping it with a hard zero
    # left a step of 0.58, 0.69 and 1.08 dB across a single grid point 0.55 Hz wide, inside
    # the 5-200 Hz band the residual is scored over. No cascade of biquads follows a step
    # that narrow, so the minimax residual was bounded below by half of it — 0.54 dB on the
    # third title, above `residual_target_db` — and the fit could never stop early, spending
    # the whole section budget to chase an artefact of where the target was truncated.
    target *= _taper(DESIGN_GRID, anchor, params.flatten_taper_ratio)
    notes: list[str] = []
    # The floor binds before the cap. `max_gain_db` is a preference dial (§4.3) and the noise
    # floor is evidence, so clipping first lets the dial pre-empt the measurement: on a floor
    # with a slope of its own the raw deficit runs to 43-62 dB, the cap flattens it to 26
    # before the hold is consulted, and the guard then finds nothing left to hold. Clipping a
    # runaway is not the same as declining to chase it, and only the second is a reason.
    floor = diagnosis.noise_floor_hz
    if not math.isnan(floor):
        # below the noise floor there is nothing to recover; hold the boost rather than
        # continuing to chase a curve that is describing noise
        held = float(np.interp(floor, DESIGN_GRID, target))
        below = DESIGN_GRID < floor
        local_deficit = target
        withheld = float(np.max(local_deficit[below])) - held if below.any() else 0.0
        # Capped at the local measured deficit, not held flat unconditionally (§14, step 4).
        # The flat hold asks for `held` at every frequency below the floor, but `held` is read
        # off the target just *above* the floor and nothing guarantees the deficit below it
        # never dips under that value — on Blazing Saddles it does, and the flat hold asked
        # for 32.2 dB at 5 Hz where the mix is only 20.9 dB short, 154% of the measured deficit.
        # Capping rather than tapering to zero: a taper below the floor would ask a shelf
        # cascade for a band-pass shape and invite a cancelling pair, where a cap just stops
        # asking for more than was measured.
        over_by = float(np.max(held - local_deficit[below])) if below.any() else 0.0
        target = np.where(below, np.minimum(held, local_deficit), target)
        if withheld >= 0.5:
            notes.append(
                f"noise floor binds: the mix asks for a further {withheld:.1f} dB below "
                f"{floor:.1f} Hz, held flat because nothing down there tracks the passband"
            )
        if over_by >= 0.5:
            notes.append(
                f"noise-floor hold capped at the local measured deficit below {floor:.1f} Hz: "
                f"the flat hold at {held:.1f} dB would have exceeded it by up to "
                f"{over_by:.1f} dB"
            )
    unpriced = target
    target, capped = priced_by_evidence(target, envelopes, diagnosis, params)
    notes.extend(capped)
    if target.max() < 1.0:
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
    """Restore the filtered channels, re-sum, and read the deficit off the mix."""
    if not diagnosis.filtered_channels:
        return []
    # Everything that does not depend on the cap, computed once. Each channel's spectrum, the
    # bin axis it sits on and the mix's own reference are the same for every cap, and this
    # title's sample count factors as 2 * 3 * 47 * 24049 — that 24,049 puts pocketfft on a
    # Bluestein path, so one forward transform is 1.22 s and one inverse 0.95 s. Three caps
    # were paying for six of each where two would do.
    restoration = _Restoration(material, diagnosis)
    proposals: list[Proposal] = []
    for cap in params.restore_caps_db:
        unpriced = counterfactual_target(material, diagnosis, cap, params, restoration)
        # Priced by the same evidence as `flatten`'s. A restored deficit is still only a claim
        # about what the mix would have been, and a claim about a bin with no measurable margin
        # is not evidence about that bin — see `priced_by_evidence`.
        target, capped = priced_by_evidence(unpriced, envelopes, diagnosis, params)
        if target.max() < 1.0:
            logger.info(f"  cap {cap:.0f} dB: deficit under 1 dB, nothing to correct")
            continue
        # A cap only changes the target when it binds. On title 1 no channel is attenuated by
        # 25 dB, so all three caps describe one deficit and fitting each spent two thirds of
        # the run recomputing one answer.
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
    """Invert the rolloff fitted by `identify_rolloff` (§3.5)."""
    if identification is None or not identification.detected:
        return []
    result = design(
        identification,
        envelopes,
        parametric_params(params),
        price_target=lambda target: priced_by_evidence(
            target, envelopes, diagnosis, params
        ),
    )
    if not result.filters:
        logger.info(f"  parametric declined: {result.decline_reason}")
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
optimiser: it calls `design`, which calls the fitter, and across the four titles that is 403 s
of a 1,586 s run — more than any other single stage. What it contributes is a statement about
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

    def __init__(self, material: Material, diagnosis: Diagnosis) -> None:
        spectra = {
            name: np.fft.rfft(material.channels[name])
            for name in diagnosis.filtered_channels
        }
        object.__setattr__(self, "spectra", spectra)
        object.__setattr__(
            self,
            "bins",
            np.fft.rfftfreq(len(material.mono_mix), 1.0 / material.fs),
        )
        object.__setattr__(
            self, "before_db", mean_spectrum(material.mono_mix, material.fs)[1]
        )


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
    restoration = restoration or _Restoration(material, diagnosis)
    freqs = diagnosis.freqs
    restored = material.mono_mix.copy()
    for name in diagnosis.filtered_channels:
        samples = material.channels[name]
        response = diagnosis.channels[name].response_db
        boost = np.where(
            unexcluded(freqs, params.exclude_bands_hz) & np.isfinite(response),
            np.clip(-np.minimum(response, 0.0), 0.0, restore_cap_db),
            0.0,
        )
        # restoration stops at this channel's own plateau, since that is what its response
        # was referenced to — a common cutoff would restore one channel into its passband
        # while stopping another short of its knee
        knee = freqs > diagnosis.channels[name].plateau_hz[0]
        boost = np.where(knee, 0.0, boost)
        spectrum = restoration.spectra[name]
        gain = np.interp(restoration.bins, freqs, boost, left=boost[0], right=0.0)
        gain[~unexcluded(restoration.bins, params.exclude_bands_hz)] = 0.0
        lifted = np.fft.irfft(spectrum * 10.0 ** (gain / 20.0), n=len(samples))
        mix_gain = LFE_GAIN if name == "LFE" else MAIN_GAIN
        restored = restored + mix_gain * (lifted - samples)

    before = restoration.before_db
    grid, after = mean_spectrum(restored, material.fs)
    deficit = np.where(
        unexcluded(grid, params.exclude_bands_hz), np.maximum(after - before, 0.0), 0.0
    )
    target = np.interp(DESIGN_GRID, grid, deficit, left=deficit[0], right=0.0)
    target = smooth_unexcluded(target, DESIGN_GRID, params.exclude_bands_hz, 9)
    # Terminated where this title's own restored deficit closes, and tapered, exactly as
    # `flatten` is — `_deficit_anchor` and `_taper` carry the reasoning for both halves of that.
    #
    # It used to be `target[DESIGN_GRID > share_band_hz[1]] = 0.0`, a hard zero at 35 Hz.
    # `DiagnoseParams.share_band_hz`'s own docstring says "Only the shares use this", and §13.5
    # keeps it as a survivor precisely because a *cross-channel comparison* needs one yardstick;
    # nothing licensed it to decide where a correction ends. The cost was not theoretical: it
    # made this whole strategy incapable on any title whose knee sits above 35 Hz, which is
    # Blazing Saddles at 44.4 Hz and Alien at 34.4-48.1 Hz — two of the three titles that
    # abstain. Their counterfactual candidates are not marginal but wrecked, a -39.7 dB hole at
    # 40 Hz and cliffs relocated to 23-37 Hz, because the deficit was cut off mid-knee.
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
    """Fit every proposal that needs fitting, in one escalation.

    One call rather than one per proposal, because the section budget is escalated and a
    target escalating alone leaves most of the machine idle: its first tier is two tasks for
    seven workers. Together, a tier is every undecided proposal's tier at once.

    **Placement is discovered per target, not asserted.** This used to hand every proposal of
    every title the literal `(5.0, 40.0)`, which hard-bounds each section's centre frequency —
    while `correction_band_hz`, written for exactly this and already used by `design.py`,
    derives the span from where the target actually asks for something. The 40 Hz ceiling was
    §2.1's move in the place it costs most: measured across the eight titles on hand, every
    title whose `flatten` target fits under it accepts a filter, and every title whose target
    reaches past it has its sections pinned against it — 38.8, 39.8, 37.6 and 37.2 Hz on
    Alien, Blazing Saddles, Nocturnal Animals and Tron — and none of those four accepts
    `flatten`. Blazing Saddles is the clearest: its target peaks at 33.6 dB at 38.9 Hz and
    still asks 23 dB at 50 Hz, all of it above the ceiling, so four sections piled into
    29-40 Hz including a -14.7 dB cancelling term and the residual landed at 2.27 dB. The
    derived band is 22-50 Hz on the five titles that already work, inside the old bound, so
    this is inert where the pipeline succeeds.
    """
    placements = [
        correction_band_hz(p.target_db, DESIGN_GRID, params.lowest_frequency_hz)
        for p in proposals
    ]
    # "Evaluate wide, place narrow" is the rule `_fit_structure` states, so the band the
    # residual is scored over must contain every band a section may be placed in. With a
    # placement ceiling fixed at 40 Hz that was true by inspection; with a derived one it has
    # to be arranged, and Alien's target already reaches 199 Hz against this 200. Inert on all
    # eight titles measured — it prevents a section being placed where nothing scores it.
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


def run(
    material: Material,
    params: PipelineParams | None = None,
    cache_path: Path | None = None,
    fresh: bool = False,
) -> Report:
    """Diagnose, propose, fit, judge.

    `cache_path` is where stages that do not change are kept so they need not be repeated —
    the analysis, and any strategy that declares `cache_modules`. `fresh` recomputes and
    overwrites them.

    Reading is on by default, which is safe because of how the key is built rather than
    because caching is usually fine: a stage is reused only when the material's own samples,
    the parameters it was given and the sources of every module it can reach all still match.
    A silently stale hit is not a thing that can happen; a *miss* is, and `cache.load` says
    which of the three moved.
    """
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
    timings = Timings()
    FIT_STATS.reset()
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
            diagnosis = diagnose(material, params.diagnose)

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
    blockers = []
    mix_freqs, mix_response = mean_spectrum(material.mono_mix, material.fs)
    mix_level, _ = plateau_reference(
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
    if not envelopes.loud_frames:
        blockers.append("no qualifying loud events; restoration withheld")
    if not np.any(envelopes.boost_ceiling(params.confidence_z) > 0):
        blockers.append("no bins support a positive correction; restoration withheld")
    if math.isfinite(mix_level):
        _, region = plateau_reference(
            mix_response, mix_freqs, params.diagnose, params.exclude_bands_hz
        )
        limitations.append(
            f"mix reference: contiguous plateau {region[0]:.3f}-{region[1]:.3f} Hz, "
            f"median {mix_level:.6f} dB; shared by targets and verification"
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
    limitations.extend(blockers)
    for note in limitations:
        logger.info(note)
    if blockers:
        return Report(
            material,
            diagnosis,
            identification,
            [],
            timings,
            FIT_STATS,
            accept=params.accept,
            evidence_notes=tuple(limitations),
        )

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
        proposals.extend(
            dataclasses.replace(p, notes=tuple(dict.fromkeys((*p.notes, *limitations))))
            for p in produced
        )

    # Every proposal that needs a fit goes into one escalation, so a section tier is as wide
    # as the run rather than as wide as one target. That costs the per-proposal breakdown this
    # stage used to carry in `Timings`; `fit_minimal_biquads_all` logs each proposal's own
    # CPU-seconds instead, which is the more useful of the two now that they overlap.
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
                )
            )

    logger.info(f"Fitting cost: {FIT_STATS}")
    return Report(
        material=material,
        diagnosis=diagnosis,
        identification=identification,
        candidates=candidates,
        timings=timings,
        fit_stats=FIT_STATS,
        accept=params.accept,
        evidence_notes=tuple(limitations),
    )


def required_gain_reduction_db(
    material: Material, filters: list[BiquadSpec], params: PipelineParams
) -> float:
    """Gain reduction needed on the sub feed: 0.0 when none, NaN when unavailable.

    beqdesigner's own quantity — `min(20*log10(1/peak), 0)` on the filtered signal — measured on
    the bass-managed sum a BEQ actually operates on, because that is the only signal where the
    question means anything. The cascade's peak magnitude is not a substitute, and a mono
    mix without channel decomposition cannot establish the sub feed's headroom.
    """
    sub = bass_managed_sum(material)
    if sub is None:
        return math.nan
    try:
        filtered = device_waveform(
            filters, sub, float(material.fs), params.realisation, include_tail=True
        )
    except ValueError as unavailable:
        logger.warning(f"Headroom unavailable: {unavailable}")
        return math.nan
    peak = waveform_peak(filtered)
    if peak <= 0.0:
        return 0.0
    return min(20.0 * math.log10(1.0 / peak), 0.0)


def judged_band_hz(
    material: Material, diagnosis: Diagnosis, params: PipelineParams
) -> tuple[float, float]:
    """The band R1 is measured over, with its bottom taken from the evidence.

    §6.2 has said since it was written that `verify_band_hz` "should be derived, not defaulted",
    and the bottom edge is the half that can be: `diagnose` measures where programme-correlated
    content stops, and below that there is nothing a correction could have got right. Leaving it
    at 5.0 Hz set `flatten` against itself — the target is deliberately held flat below the noise
    floor, on evidence, and acceptance then failed the candidate for not having corrected there.
    Nocturnal Animals is the case: its `flatten` candidate reads +2.84 dB/oct and -3.4 dB over
    5-45 Hz against limits of 2.0 and -3.0, and +0.97 and -1.9 over its own 19.8-45 Hz, which is
    the same filter judged where its material exists.

    **The top edge extends to cover the correction, and never contracts.** Replacing it with the
    mix plateau's lower edge was tried and breaks title 1: its plateau begins at 13.9 Hz, the band
    becomes 5-20.8 Hz and its accepted filter fails, because a correction acts above where the
    deficit closes as well as below it. Taking the *wider* of the nominal edge and where the mix's
    own deficit closes has neither problem — it leaves every title whose correction is contained
    in 5-45 Hz exactly as it was, and it rescues the one where the nominal band excluded most of
    where the filter works. Blazing Saddles is that title: content only above 33.7 Hz and a
    deficit reaching to ~99 Hz, so the nominal band left 0.42 of an octave to read a slope over
    and its tilt measured -7.32 dB/oct to 45 Hz against -0.02 to 80. Extended, it has 1.6 octaves
    and a verdict that means something.

    Per-title, from the mix, rather than per-candidate from the cascade — candidates have to be
    judged over one band or their statistics are not comparable.
    """
    low, high = params.verify_band_hz
    floor = diagnosis.noise_floor_hz
    if not math.isnan(floor):
        low = max(low, floor)
    # The mix's own deficit, exactly as `flatten` measures it, and terminated the same way.
    # Taking the *highest* frequency still short of the plateau is wrong and was tried: a deficit
    # measured against a plateau level necessarily returns above the plateau's top, so it put the
    # band's edge at 340-400 Hz and every title read as uncorrected. `_deficit_anchor` scans
    # upward from the bottom and stops where the deficit first stays shut, which is the question.
    freqs, response = mean_spectrum(material.mono_mix, material.fs)
    level, plateau_hz = plateau_reference(
        response, freqs, params.diagnose, params.exclude_bands_hz
    )
    if not math.isfinite(level):
        raise ValueError("no usable contiguous mix plateau")
    levelled = response - level
    deficit = smooth_unexcluded(
        np.maximum(-levelled, 0.0), freqs, params.exclude_bands_hz, 15
    )
    on_grid = np.interp(DESIGN_GRID, freqs, deficit, left=deficit[0], right=0.0)
    return low, min(
        max(high, _deficit_anchor(DESIGN_GRID, on_grid, params, plateau_hz)),
        float(DESIGN_GRID[-1]),
    )


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
) -> Candidate:
    """`target` is the priced target the fitter was handed, or `None` for a candidate with
    none (a caller-supplied cascade) — passed through to `verify`/`assess` so intent (§14.2) can
    fall back to the house curve rather than to an all-zero target, which is a different claim.
    """
    optimiser_filters = filters
    filters = publication_filters(filters)
    correction = verify(
        filters,
        material.mono_mix,
        float(material.fs),
        band_hz=judged_band_hz(material, diagnosis, params),
        diagnose_params=params.diagnose,
        exclude_bands_hz=params.exclude_bands_hz,
        accept_params=params.accept,
        realisation=params.realisation,
        priced_target_db=target,
    )
    verdict = assess(
        filters,
        correction,
        diagnosis.noise_floor_hz,
        params.accept,
        params.realisation,
        filter_floor_hz=diagnosis.filter_floor_hz,
        required_offset_db=required_gain_reduction_db(material, filters, params),
        target_db=target,
    )
    verdict.notes.append(
        f"verification transfer: published quantised device at {params.realisation.fs:g} Hz; "
        f"full-band mono mix from {material.fs:g} Hz extraction, complex response including phase; "
        "headroom uses the same transfer with ring-out and 16x peak interpolation"
    )
    verdict.notes.extend(target_notes)
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
        target_notes=target_notes,
        method=method,
        effective_params=effective_params,
    )
