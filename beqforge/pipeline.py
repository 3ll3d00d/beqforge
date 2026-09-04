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
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np

from beqanalyser.design import BiquadSpec
from beqanalyser.design.accept import AcceptParams, Verdict, assess
from beqanalyser.design.design import DesignParams, design
from beqanalyser.design.diagnose import (
    Diagnosis,
    DiagnoseParams,
    diagnose,
    mean_spectrum,
)
from beqanalyser.design.extraction import ExtractionParams, extract
from beqanalyser.design.filters import (
    FIT_STATS,
    FitStats,
    Realisation,
    biquad_sos,
    fit_minimal_biquads,
    magnitude_db,
)
from beqanalyser.design.identify import IdentifyParams, Identification, identify_rolloff
from beqanalyser.design.material import LFE_GAIN, MAIN_GAIN, Material
from beqanalyser.design.verify import Correction, verify

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
DESIGN_GRID = np.logspace(math.log10(3.0), math.log10(400.0), 400)


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

    flatten_reference_hz: float = 40.0
    """Frequency `flatten` levels the mix against. Above the knee, below bass management."""

    flatten_taper_ratio: float = 1.25
    """How far above the reference the target is tapered to nothing, as a frequency ratio.

    A quarter of an octave. Wide enough that the transition is smooth against a 400-point
    log grid, narrow enough that it does not reach down into the correction."""

    restore_caps_db: tuple[float, ...] = (25.0, 35.0, 45.0)
    """Ceilings on the counterfactual restoration, one candidate each.

    A sweep rather than a choice: how far a channel's attenuation can be inverted before it
    is inverting something that is not a filter is exactly what is not known in advance, and
    the acceptance model is better placed to reject the wrong ones than a prior is."""

    max_sections: int = 4
    residual_target_db: float = 0.5
    max_gain_db: float = 26.0
    fit_seeds: tuple[int, ...] = (0, 1)
    verify_band_hz: tuple[float, float] = (5.0, 45.0)
    exclude_bands_hz: tuple[tuple[float, float], ...] = ()
    """Authored features to drop, still manual (§3.1, §10).

    Reaches every stage that reads the spectrum: the `flatten` target, the verification band,
    and identification. It used to reach the first two only, because `IdentifyParams` carries
    a field of the same name that nothing set — so `--exclude 12 25` removed a hand-authored
    feature from the target and from the judgement while `identify_rolloff` went on fitting
    it, which is the failure §3.5 records as dragging a corner from 13 Hz to 20."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """One design and everything known about it."""

    label: str
    filters: list[BiquadSpec]
    target_db: np.ndarray
    fit_error_db: float
    correction: Correction
    verdict: Verdict
    target_notes: tuple[str, ...] = ()
    """What bounded the target, if anything.

    §4.1 argues a limit that binds is a signal and not merely a limit — a correction whose
    shape is being set by the noise floor or by a boost cap says the title is in the marginal
    regime. Nothing recorded that, so a target held flat by the guard and one that genuinely
    flattened out looked identical in the output.
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


@dataclass(frozen=True, slots=True)
class Report:
    """The whole run."""

    material: Material
    diagnosis: Diagnosis
    identification: Identification | None
    candidates: list[Candidate]
    timings: Timings
    fit_stats: FitStats

    @property
    def accepted(self) -> Candidate | None:
        """The best of the candidates the acceptance model let through.

        Ranked on the statistic the model actually judged — wobble against the material's own
        roughness — rather than on `spread_db`, which includes a tilt the tilt clause has
        already ruled on. Deliberately shallow either way: the acceptance model does the work,
        and a scalar score that could overrule it would reintroduce exactly the
        aggregate-blindness R1 exists to defeat.
        """
        passing = [c for c in self.candidates if c.verdict.passed]
        if not passing:
            return None
        return min(passing, key=lambda c: (c.verdict.wobble_db, len(c.filters)))


@dataclass(frozen=True, slots=True)
class Proposal:
    """One strategy's suggestion: a curve to fit, or a cascade already known exactly."""

    label: str
    target_db: np.ndarray | None = None
    filters: list[BiquadSpec] | None = None
    residual_db: float = 0.0
    notes: tuple[str, ...] = ()
    """What bound this target, if anything. Carried through to the `Candidate`."""


def _taper(freqs: np.ndarray, reference_hz: float, ratio: float) -> np.ndarray:
    """Raised cosine falling from 1 at `reference_hz` to 0 at `reference_hz * ratio`.

    In log-frequency, and raised cosine rather than linear, so the target has a continuous
    derivative where it stops as well as a continuous value. A fit is scored on the target it
    is handed; anything the target does that a biquad cascade cannot follow is charged to the
    cascade's residual and read as a bad fit.
    """
    position = np.log2(np.asarray(freqs) / reference_hz) / math.log2(ratio)
    return 0.5 * (1.0 + np.cos(math.pi * np.clip(position, 0.0, 1.0)))


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
    keep = np.ones_like(freqs, dtype=bool)
    for low, high in params.exclude_bands_hz:
        keep &= ~((freqs >= low) & (freqs <= high))
    freqs, response = freqs[keep], response[keep]
    response = response - np.interp(params.flatten_reference_hz, freqs, response)
    deficit = np.convolve(np.maximum(-response, 0.0), np.ones(15) / 15, mode="same")

    target = np.interp(DESIGN_GRID, freqs, deficit, left=deficit[0], right=0.0)
    # Tapered to nothing above the reference, not cut off there. The mix keeps falling above
    # the reference — by 5 to 11.6 dB over 45-200 Hz on the three titles — and that fall is
    # the programme, not a deficit, so the target has to stop. Stopping it with a hard zero
    # left a step of 0.58, 0.69 and 1.08 dB across a single grid point 0.55 Hz wide, inside
    # the 5-200 Hz band the residual is scored over. No cascade of biquads follows a step
    # that narrow, so the minimax residual was bounded below by half of it — 0.54 dB on the
    # third title, above `residual_target_db` — and the fit could never stop early, spending
    # the whole section budget to chase an artefact of where the target was truncated.
    target *= _taper(
        DESIGN_GRID, params.flatten_reference_hz, params.flatten_taper_ratio
    )
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
        withheld = float(np.max(target[below])) - held if below.any() else 0.0
        target = np.where(below, held, target)
        if withheld >= 0.5:
            notes.append(
                f"noise floor binds: the mix asks for a further {withheld:.1f} dB below "
                f"{floor:.1f} Hz, held flat because nothing down there tracks the passband"
            )
    if target.max() > params.max_gain_db:
        notes.append(
            f"boost cap binds: the target reaches {target.max():.1f} dB and is held at "
            f"{params.max_gain_db:.1f} dB"
        )
    target = np.clip(target, 0.0, params.max_gain_db)
    if target.max() < 1.0:
        return []
    return [Proposal("flatten", target_db=target, notes=tuple(notes))]


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
    proposals: list[Proposal] = []
    for cap in params.restore_caps_db:
        target = counterfactual_target(material, diagnosis, cap, params)
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
            proposals.append(Proposal(f"counterfactual/{cap:.0f}dB", target_db=target))
    return proposals


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
        DesignParams(max_sections=params.max_sections, realisation=params.realisation),
    )
    if not result.filters:
        logger.info(f"  parametric declined: {result.decline_reason}")
        return []
    return [
        Proposal("parametric", filters=result.filters, residual_db=result.residual_db)
    ]


STRATEGIES = {
    "flatten": flatten_targets,
    "counterfactual": counterfactual_targets,
    "parametric": parametric_targets,
}
"""Every way of deriving a target, by name. All equal citizens of the same pipeline."""


def counterfactual_target(
    material: Material,
    diagnosis: Diagnosis,
    restore_cap_db: float,
    params: PipelineParams,
) -> np.ndarray:
    """Mix deficit if the filtered channels had never been filtered.

    The inversion is applied to the channel in isolation and the mix rebuilt, so the answer
    accounts for the other channels continuing to supply whatever they supply. That matters:
    a channel 23 dB under the mains contributes nothing to the sum until it is restored, and
    a target computed on the channel alone would not know that.
    """
    freqs = diagnosis.freqs
    restored = material.mono_mix.copy()
    for name in diagnosis.filtered_channels:
        samples = material.channels[name]
        response = diagnosis.channels[name].response_db
        boost = np.clip(-np.minimum(response, 0.0), 0.0, restore_cap_db)
        knee = freqs > params.diagnose.passband_hz[0]
        boost = np.where(knee, 0.0, boost)
        spectrum = np.fft.rfft(samples)
        bins = np.fft.rfftfreq(len(samples), 1.0 / material.fs)
        gain = np.interp(bins, freqs, boost, left=boost[0], right=0.0)
        lifted = np.fft.irfft(spectrum * 10.0 ** (gain / 20.0), n=len(samples))
        mix_gain = LFE_GAIN if name == "LFE" else MAIN_GAIN
        restored = restored + mix_gain * (lifted - samples)

    _, before = mean_spectrum(material.mono_mix, material.fs)
    grid, after = mean_spectrum(restored, material.fs)
    deficit = np.maximum(after - before, 0.0)
    target = np.interp(DESIGN_GRID, grid, deficit, left=deficit[0], right=0.0)
    target = np.maximum(np.convolve(target, np.ones(9) / 9, mode="same"), 0.0)
    target[DESIGN_GRID > params.diagnose.passband_hz[1]] = 0.0
    return target


def _fit(target: np.ndarray, params: PipelineParams) -> tuple[list[BiquadSpec], float]:
    return fit_minimal_biquads(
        target,
        DESIGN_GRID,
        PUBLISH_FS,
        params.max_sections,
        params.residual_target_db,
        band_hz=(5.0, 200.0),
        placement_band_hz=(5.0, 40.0),
        max_gain_db=params.max_gain_db,
        realisation=params.realisation,
        seeds=params.fit_seeds,
    )


def run(material: Material, params: PipelineParams | None = None) -> Report:
    """Diagnose, propose, fit, judge."""
    params = params or PipelineParams()
    timings = Timings()
    FIT_STATS.reset()
    logger.info("=" * 80)
    logger.info(f"Material: {material}")

    logger.info("=" * 80)
    logger.info("Per-channel decomposition")
    with timings.stage("diagnose"):
        diagnosis = diagnose(material, params.diagnose)

    with timings.stage("extract"):
        envelopes = extract(material.mono_mix, float(material.fs), params.extraction)
    identification: Identification | None = None
    # the run's exclusions are the run's, whichever stage reads the spectrum
    identify_params = dataclasses.replace(
        params.identify,
        exclude_bands_hz=tuple(
            dict.fromkeys((*params.identify.exclude_bands_hz, *params.exclude_bands_hz))
        ),
    )
    with timings.stage("identify"):
        try:
            identification = identify_rolloff(envelopes, identify_params)
        except ValueError as unusable:
            logger.warning(f"Sum-based identification unavailable: {unusable}")

    logger.info("=" * 80)
    logger.info(f"Strategies: {', '.join(params.strategies)}")
    proposals: list[Proposal] = []
    for name in params.strategies:
        strategy = STRATEGIES.get(name)
        if strategy is None:
            raise ValueError(
                f"unknown strategy {name!r}; have {', '.join(sorted(STRATEGIES))}"
            )
        with timings.stage(f"target/{name}"):
            produced = strategy(material, diagnosis, envelopes, identification, params)
        logger.info(f"  {name}: {len(produced)} proposal(s)")
        proposals.extend(produced)

    candidates: list[Candidate] = []
    for proposal in proposals:
        if proposal.filters is not None:
            filters, error = proposal.filters, proposal.residual_db
        else:
            with timings.stage(f"fit/{proposal.label}"):
                filters, error = _fit(proposal.target_db, params)
        with timings.stage(f"judge/{proposal.label}"):
            candidates.append(
                _judge(
                    proposal.label,
                    filters,
                    proposal.target_db
                    if proposal.target_db is not None
                    else np.zeros_like(DESIGN_GRID),
                    error,
                    material,
                    diagnosis,
                    params,
                    proposal.notes,
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
    )


def _judge(
    label: str,
    filters: list[BiquadSpec],
    target: np.ndarray,
    error: float,
    material: Material,
    diagnosis: Diagnosis,
    params: PipelineParams,
    target_notes: tuple[str, ...] = (),
) -> Candidate:
    correction = verify(
        filters,
        material.mono_mix,
        float(material.fs),
        band_hz=params.verify_band_hz,
        exclude_bands_hz=params.exclude_bands_hz,
    )
    verdict = assess(
        filters,
        correction,
        diagnosis.noise_floor_hz,
        params.accept,
        params.realisation,
        filter_floor_hz=diagnosis.filter_floor_hz,
    )
    logger.info(f"  {label}: {verdict}")
    for note in target_notes:
        logger.info(f"    {note}")
    return Candidate(
        label=label,
        filters=filters,
        target_db=target,
        fit_error_db=error,
        correction=correction,
        verdict=verdict,
        target_notes=target_notes,
    )
