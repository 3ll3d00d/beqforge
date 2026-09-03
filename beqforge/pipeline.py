"""The repeatable process: material in, a judged filter and its reasoning out.

Two routes to a target, chosen by what the material actually shows rather than by a switch:

* **Counterfactual** — when `diagnose` finds a filtered channel. Measure that channel's
  attenuation against its own passband, invert it, re-sum against the untouched channels and
  read the deficit off the mix. This is what produced the accepted answer on the second
  title, where the sum carries no usable evidence below ~15 Hz.
* **Sum-based** — `identify_rolloff` on the mono mix, as §3.5. Used when no channel shows a
  knee, which is the case the soft-hinge model was written for.

Both are run whenever both are available and the disagreement is reported, because a
disagreement is information: it says the rolloff is confined to a channel the sum cannot see.

Candidates are then generated, judged against §6.4, and the survivors ranked. The ranking is
deliberately shallow — the acceptance model does the work, and a scalar score that could
overrule it would reintroduce exactly the aggregate-blindness R1 exists to defeat.
"""

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
from beqanalyser.design.extraction import extract
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
    identify: IdentifyParams = field(default_factory=IdentifyParams)
    accept: AcceptParams = field(default_factory=AcceptParams)
    realisation: Realisation = field(default_factory=Realisation)

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
    """Authored features to drop, still manual (§3.1, §10)."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """One design and everything known about it."""

    label: str
    filters: list[BiquadSpec]
    target_db: np.ndarray
    fit_error_db: float
    correction: Correction
    verdict: Verdict

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
    counterfactual_target: np.ndarray | None
    candidates: list[Candidate]
    timings: Timings
    fit_stats: FitStats

    @property
    def accepted(self) -> Candidate | None:
        passing = [c for c in self.candidates if c.verdict.passed]
        if not passing:
            return None
        return min(passing, key=lambda c: (c.correction.spread_db, len(c.filters)))


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
    """Diagnose, target, design, judge."""
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
        envelopes = extract(material.mono_mix, float(material.fs))
    identification: Identification | None = None
    with timings.stage("identify"):
        try:
            identification = identify_rolloff(envelopes, params.identify)
        except ValueError as unusable:
            logger.warning(f"Sum-based identification unavailable: {unusable}")

    candidates: list[Candidate] = []
    target = None

    if diagnosis.filtered_channels:
        logger.info("=" * 80)
        logger.info(
            f"Counterfactual targets from {', '.join(diagnosis.filtered_channels)}"
        )
        # Targets are derived for every cap first and identical ones collapsed. A cap only
        # changes the target when it actually binds; on the first title no channel is
        # attenuated by 25 dB, so all three caps describe the same deficit and fitting each
        # of them separately spent two thirds of the run recomputing one answer.
        derived: list[tuple[str, np.ndarray]] = []
        for cap in params.restore_caps_db:
            with timings.stage(f"target/{cap:.0f}dB"):
                target = counterfactual_target(material, diagnosis, cap, params)
            if target.max() < 1.0:
                logger.info(
                    f"  cap {cap:.0f} dB: deficit under 1 dB, nothing to correct"
                )
                continue
            for label, seen in derived:
                if np.allclose(seen, target, atol=1e-6):
                    logger.info(
                        f"  cap {cap:.0f} dB: target identical to {label}; not refitting"
                    )
                    break
            else:
                derived.append((f"{cap:.0f}dB", target))

        for label, target in derived:
            with timings.stage(f"fit/{label}"):
                filters, error = _fit(target, params)
            with timings.stage(f"judge/{label}"):
                candidates.append(
                    _judge(
                        f"counterfactual/{label}",
                        filters,
                        target,
                        error,
                        material,
                        diagnosis,
                        params,
                    )
                )

    if identification is not None and identification.detected:
        logger.info("=" * 80)
        logger.info("Sum-based design")
        with timings.stage("fit/sum-based"):
            result = design(
                identification,
                envelopes,
                DesignParams(
                    max_sections=params.max_sections, realisation=params.realisation
                ),
            )
        if result.filters:
            grid_target = np.interp(
                DESIGN_GRID, DESIGN_GRID, np.zeros_like(DESIGN_GRID)
            )
            candidates.append(
                _judge(
                    "sum-based",
                    result.filters,
                    grid_target,
                    result.residual_db,
                    material,
                    diagnosis,
                    params,
                )
            )
        else:
            logger.info(f"  declined: {result.decline_reason}")

    logger.info(f"Fitting cost: {FIT_STATS}")
    return Report(
        material=material,
        diagnosis=diagnosis,
        identification=identification,
        counterfactual_target=target,
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
    )
    logger.info(f"  {label}: {verdict}")
    return Candidate(
        label=label,
        filters=filters,
        target_db=target,
        fit_error_db=error,
        correction=correction,
        verdict=verdict,
    )
