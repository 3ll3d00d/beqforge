"""High-pass synthesis and inversion to a publishable biquad cascade.

The output stage of AUTOMATED_DESIGN.md §5. Two routes to the same target:

* `invert_to_shelves` — closed form, exact, when the protective filter shares the identified
  rolloff's alignment and order. An RBJ low shelf is a biquad with zeros at `f*sqrt(A)` and
  poles at `f/sqrt(A)`, both at the shelf's Q, so a target section whose zeros and poles share
  a Q *is* a low shelf.
* `fit_to_shelves` — numerical minimax fit, for everything else.

Everything below the public boundary takes plain ndarrays.
"""

import logging
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count
from dataclasses import dataclass

import numpy as np
from scipy import optimize, signal

from beqanalyser import HighShelf, LowShelf, PeakingEQ
from beqanalyser.design import (
    Alignment,
    BiquadSpec,
    ExactInversionUnavailable,
    HighPass,
    PolePair,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FitStats:
    """Cost of the fitting stage, so performance work can be aimed rather than guessed.

    The optimiser is the whole budget: `fit_to_biquads` runs one `_fit_structure` per split of
    the section budget per seed, and `fit_minimal_biquads` calls that for every section count
    up to its own. The call count is therefore `seeds * M * (M + 1) / 2`, which is easy to
    raise by one parameter and hard to notice.
    """

    calls: int = 0
    seconds: float = 0.0
    cost_evaluations: int = 0

    def reset(self) -> None:
        self.calls = 0
        self.seconds = 0.0
        self.cost_evaluations = 0

    def __str__(self) -> str:
        per = self.seconds / self.calls if self.calls else 0.0
        return (
            f"{self.calls} optimiser runs, {self.seconds:.1f} s "
            f"({per:.1f} s each), {self.cost_evaluations:,} cost evaluations"
        )


FIT_STATS = FitStats()
"""Process-wide fitting cost. Reset it at the start of a run."""


_REAL_POLE_TOLERANCE = 1e-9
"""Imaginary part below which an analogue pole is treated as real."""


def _prototype_poles(alignment: Alignment, order: int) -> np.ndarray:
    """Poles of the normalised analogue low-pass prototype.

    Linkwitz-Riley of order 2N is Butterworth of order N applied twice, so its prototype is
    the Butterworth prototype with every pole repeated.
    """
    if alignment is Alignment.BUTTERWORTH:
        return signal.buttap(order)[1]
    if alignment is Alignment.LINKWITZ_RILEY:
        half = signal.buttap(order // 2)[1]
        return np.concatenate([half, half])
    norm = "phase" if alignment is Alignment.BESSEL_PHASE else "mag"
    return signal.besselap(order, norm=norm)[1]


def section_poles(hp: HighPass) -> tuple[list[PolePair], list[float]]:
    """Decompose a high-pass into its second-order sections plus any first-order remainder.

    Returns the conjugate pairs as (natural frequency, Q), and the corner frequencies of any
    real poles. An odd-order filter always leaves exactly one real pole.
    """
    wc = 2.0 * math.pi * hp.corner_hz
    # the low-pass to high-pass transform maps each prototype pole p to wc / p
    poles = wc / _prototype_poles(hp.alignment, hp.order)
    pairs: list[PolePair] = []
    real_ws: list[float] = []
    for p in poles:
        if abs(p.imag) <= _REAL_POLE_TOLERANCE * abs(p):
            real_ws.append(abs(p.real))
        elif p.imag > 0:  # take one of each conjugate pair
            w0 = abs(p)
            pairs.append(PolePair(w0 / (2.0 * math.pi), w0 / (2.0 * abs(p.real))))
    # two real poles also form a second-order section — Linkwitz-Riley of order 2N is
    # Butterworth of order N twice, so an even-order LR is entirely coincident real pairs
    real_ws.sort()
    while len(real_ws) >= 2:
        w1, w2 = real_ws.pop(0), real_ws.pop(0)
        w0 = math.sqrt(w1 * w2)
        pairs.append(PolePair(w0 / (2.0 * math.pi), w0 / (w1 + w2)))
    pairs.sort(key=lambda pair: pair.q)
    return pairs, [w / (2.0 * math.pi) for w in real_ws]


def high_pass_sos(hp: HighPass, fs: float) -> np.ndarray:
    """Digital second-order sections for a high-pass at `fs`."""
    if hp.alignment is Alignment.BUTTERWORTH:
        return signal.butter(hp.order, hp.corner_hz, btype="high", fs=fs, output="sos")
    if hp.alignment is Alignment.LINKWITZ_RILEY:
        half = signal.butter(
            hp.order // 2, hp.corner_hz, btype="high", fs=fs, output="sos"
        )
        return np.vstack([half, half])
    norm = "phase" if hp.alignment is Alignment.BESSEL_PHASE else "mag"
    return signal.bessel(
        hp.order, hp.corner_hz, btype="high", fs=fs, output="sos", norm=norm
    )


def magnitude_db(sos: np.ndarray, freqs: np.ndarray, fs: float) -> np.ndarray:
    """Magnitude response in dB of a cascade at the given frequencies.

    Evaluated directly rather than through `scipy.signal.sosfreqz`, whose per-call overhead
    dominates the fitting loop by an order of magnitude. Same arithmetic, same coefficients.
    """
    sections = np.atleast_2d(np.asarray(sos, dtype=np.float64))
    z1 = np.exp(-2j * np.pi * np.asarray(freqs, dtype=np.float64) / fs)
    z2 = z1 * z1
    b = sections[:, :3]
    a = sections[:, 3:]
    num = b[:, 0, None] + b[:, 1, None] * z1 + b[:, 2, None] * z2
    den = a[:, 0, None] + a[:, 1, None] * z1 + a[:, 2, None] * z2
    return np.sum(20.0 * np.log10(np.abs(num / den) + 1e-300), axis=0)


def biquad_sos(specs: list[BiquadSpec], fs: float) -> np.ndarray:
    """Realise a publishable cascade as second-order sections at `fs`."""
    ctors = {"low_shelf": LowShelf, "high_shelf": HighShelf, "peaking_eq": PeakingEQ}
    rows: list[list[float]] = []
    for spec in specs:
        rows.extend(ctors[spec.type](fs, spec.freq_hz, spec.q, spec.gain_db).get_sos())
    return np.array(rows)


def inversion_target_db(
    rolloff: HighPass, protect: HighPass, freqs: np.ndarray, fs: float
) -> np.ndarray:
    """`1/H_rolloff . H_protect` in dB.

    The exact target the published cascade approximates. Unbounded at DC without `protect`,
    which is why the termination is an explicit input rather than an emergent consequence.

    Deliberately not normalised. Both filters are high-passes, so the ratio tends to 0 dB well
    above either corner on its own; pinning it to exactly 0 dB at the top of the axis would
    inject an offset against a shelf cascade that only approaches 0 dB asymptotically.
    """
    return magnitude_db(high_pass_sos(protect, fs), freqs, fs) - magnitude_db(
        high_pass_sos(rolloff, fs), freqs, fs
    )


def invert_to_shelves(rolloff: HighPass, protect: HighPass) -> list[BiquadSpec]:
    """The exact inverse of `rolloff`, terminated by `protect`, as RBJ low shelves.

    Exact only when the two share an alignment and order, so that every section's zeros and
    poles carry the same Q. That is a design rule rather than a coincidence: the protective
    filter's alignment is ours to choose, so choose the one that makes the output exact.

    Raises `ExactInversionUnavailable` when the closed form does not apply — an odd order
    leaves a first-order section, which no RBJ shelf expresses.
    """
    if rolloff.alignment is not protect.alignment or rolloff.order != protect.order:
        raise ExactInversionUnavailable(
            f"{rolloff} and {protect} differ in alignment or order; "
            "the closed form needs a shared Q per section"
        )
    if protect.corner_hz >= rolloff.corner_hz:
        raise ExactInversionUnavailable(
            f"protective corner {protect.corner_hz} must sit below the rolloff "
            f"corner {rolloff.corner_hz}"
        )
    zeros, zero_reals = section_poles(rolloff)
    poles, pole_reals = section_poles(protect)
    if zero_reals or pole_reals:
        raise ExactInversionUnavailable(
            f"{rolloff} has a first-order section; no RBJ shelf expresses it"
        )
    # matched alignment and order means the two decompose into the same Qs in the same
    # order, so section i of the rolloff pairs with section i of the protective filter
    gain = 40.0 * math.log10(rolloff.corner_hz / protect.corner_hz)
    return [
        BiquadSpec(
            type="low_shelf",
            freq_hz=math.sqrt(zero.freq_hz * pole.freq_hz),
            gain_db=gain,
            q=zero.q,
        )
        for zero, pole in zip(zeros, poles, strict=True)
    ]


def correction_band_hz(
    target_db: np.ndarray,
    freqs: np.ndarray,
    evidence_floor_hz: float,
    threshold_db: float = 0.5,
) -> tuple[float, float]:
    """The span over which a target actually asks for something.

    Sections belong where the correction is, not merely inside the band the residual is scored
    over. A bass correction that is flat above 25 Hz has no business placing a section at
    105 Hz, and one that does is spending budget to achieve nothing.

    Widened upward by half an octave but **never downward below `evidence_floor_hz`**. The
    asymmetry is the point. A section reaching up is harmless — its skirt still does its work
    lower down. A section placed below the lowest measured frequency has its defining
    parameters in a region where nothing was observed: only its skirt is fitted, and its corner
    and Q rest on no evidence at all. Unbounded, the fit does exactly that — it once returned a
    low shelf at 3.22 Hz with +45 dB of gain to express a correction that is under 5 dB
    anywhere above 10 Hz, using the shelf's transition as a ramp rather than using it as a
    shelf.
    """
    active = np.abs(target_db) >= threshold_db
    if not active.any():
        return evidence_floor_hz, float(freqs[-1])
    low, high = float(freqs[active].min()), float(freqs[active].max())
    return max(evidence_floor_hz, low), min(float(freqs[-1]), high * 1.5)


FitTask = tuple
"""Positional arguments for one `_fit_structure` call."""

PARALLEL_FITS = True
"""Run independent fits in worker processes. Set False to profile or debug serially."""


def _physical_cores() -> int:
    """Cores, not hardware threads.

    `cpu_count()` reports threads: on an 8-core machine with SMT it says 16. Sizing a pool of
    CPU-bound fits by that number oversubscribes the machine two to one — capping at "all but
    one" of 16 put 15 processes on 8 cores and saturated it completely, which is the opposite
    of leaving headroom.
    """
    try:
        seen: set[tuple[str, str]] = set()
        physical = core = None
        with open("/proc/cpuinfo") as handle:
            for line in handle:
                key, _, value = line.partition(":")
                key, value = key.strip(), value.strip()
                if key == "physical id":
                    physical = value
                elif key == "core id":
                    core = value
                if physical is not None and core is not None:
                    seen.add((physical, core))
                    physical = core = None
        if seen:
            return len(seen)
    except OSError:
        pass
    return cpu_count()


FIT_WORKERS = int(os.environ.get("BEQ_FIT_WORKERS") or max(1, _physical_cores() - 1))
"""Worker ceiling for the fit pool, in physical cores and one short of the machine.

The fits are CPU-bound and saturate whatever they are given for minutes at a time, so taking
the whole machine makes it unusable for anything else — including the shell watching the run.
Scaling is only ~35% efficient at this width anyway, so the last core costs a few percent of
wall time and buys back a responsive box. Override with `BEQ_FIT_WORKERS`."""


def _fit_task(task: "FitTask") -> tuple[list[BiquadSpec], float, float, int]:
    """Picklable entry point for one fit."""
    return _fit_structure(*task)


def _run_fits(tasks: list["FitTask"]) -> list[tuple[list[BiquadSpec], float]]:
    """Run independent fits, in parallel when there is more than one.

    The fits are the entire cost of the design stage and they do not interact, so this is the
    one place parallelism buys anything. Results are returned in submission order and the
    seeds are fixed, so the answer is identical to the serial one — the pool changes how long
    it takes, never what it decides.
    """
    if len(tasks) > 1 and PARALLEL_FITS:
        workers = max(1, min(len(tasks), FIT_WORKERS))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_fit_task, tasks))
    else:
        results = [_fit_task(task) for task in tasks]
    for _, _, seconds, evaluations in results:
        FIT_STATS.calls += 1
        FIT_STATS.seconds += seconds
        FIT_STATS.cost_evaluations += evaluations
    return [(specs, residual) for specs, residual, _, _ in results]


def _structure_tasks(
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    sections: int,
    band_hz: tuple[float, float] | None,
    placement: tuple[float, float] | None,
    max_q: float,
    max_gain_db: float,
    realisation: "Realisation | None",
    seeds: tuple[int, ...],
) -> list["FitTask"]:
    """Every shelf/peak split of a section budget, from every seed."""
    return [
        (
            target_db,
            freqs,
            fs,
            shelves,
            sections - shelves,
            band_hz,
            placement,
            max_q,
            max_gain_db,
            realisation,
            seed,
        )
        for shelves in range(1, sections + 1)
        for seed in seeds
    ]


def fit_minimal_biquads(
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    max_sections: int,
    residual_target_db: float,
    band_hz: tuple[float, float] | None = None,
    placement_band_hz: tuple[float, float] | None = None,
    max_q: float = 6.0,
    max_gain_db: float = 30.0,
    realisation: "Realisation | None" = None,
    seeds: tuple[int, ...] = (0, 1, 2),
    min_contribution_db: float = 1.0,
    max_drift_db: float | None = None,
) -> tuple[list[BiquadSpec], float]:
    """The fewest sections that reach `residual_target_db`, or the best within the budget.

    `fit_to_biquads` spends whatever budget it is given, so asking it for four sections when
    three will do parks the fourth somewhere harmless at a fraction of a dB. A section that
    does nothing is not free: it occupies a slot, it has to be published, and it invites the
    reader to believe it means something.

    `max_drift_db` screens the candidates on the statistic that will actually judge them.
    The cost function scores quantisation drift at the optimiser's exact coefficients, but a
    published cascade is rounded first, and the two differ: on the third title the most
    accurate cascade in the budget measured 0.43 dB in the fit and 3.44 dB at the p90 of the
    rounding it will undergo, so selecting on residual alone chose a filter the acceptance
    model then rejected, over a slightly less accurate one that passes.

    Widening the *cost* to cover that was tried and is worse on every axis (see
    `_fit_structure`) — a max over sampled roundings is non-smooth and degrades the search.
    Measuring it once per surviving candidate instead costs a few evaluations rather than
    millions, which is where a statistic this expensive belongs.
    """
    placement = placement_band_hz or band_hz
    grouped: list[list["FitTask"]] = [
        _structure_tasks(
            target_db,
            freqs,
            fs,
            sections,
            band_hz,
            placement,
            max_q,
            max_gain_db,
            realisation,
            seeds,
        )
        for sections in range(1, max_sections + 1)
    ]
    # Every section count is enumerated up front rather than tried in turn. Serially the loop
    # stopped as soon as one met the target; in parallel that early exit would leave most of
    # the machine idle waiting for the smallest problem. The selection rule below is the same
    # one, applied after the fact, so the chosen cascade is unchanged.
    flat = [task for tasks in grouped for task in tasks]
    results = _run_fits(flat)

    at = 0
    per_sections: list[tuple[list[BiquadSpec], float]] = []
    for tasks in grouped:
        window = results[at : at + len(tasks)]
        at += len(tasks)
        per_sections.append(min(window, key=lambda r: r[1]))

    pruned = [
        _prune(candidate, target_db, freqs, fs, band_hz, min_contribution_db)
        for candidate in per_sections
    ]
    realisable = _realisable(pruned, freqs, realisation, max_drift_db)

    # `realisable` may be a subset, so the section count is read off the cascade rather than
    # from its position: after screening, the first survivor is not necessarily the 1-section
    # fit, and reporting it as one would misdescribe the answer in the run's own log.
    for specs, residual in realisable:
        if residual <= residual_target_db:
            logger.info(
                f"{len(specs)} section(s) reach {residual:.3f} dB; "
                f"the remaining {max_sections - len(specs)} are not spent"
            )
            return specs, residual
    return min(realisable, key=lambda r: r[1])


def _realisable(
    candidates: list[tuple[list[BiquadSpec], float]],
    freqs: np.ndarray,
    realisation: "Realisation | None",
    max_drift_db: float | None,
) -> list[tuple[list[BiquadSpec], float]]:
    """Those that survive the publication rounding, or all of them if none does.

    Falling back to the whole set rather than to nothing is deliberate: the acceptance model
    is what declines, and it can say *why*. Returning no candidate here would abstain without
    a reason attached, which §2.5 asks for the opposite of.
    """
    if realisation is None or max_drift_db is None:
        return candidates
    kept = []
    for specs, residual in candidates:
        drift = float(np.percentile(drift_distribution(specs, freqs, realisation), 90))
        if drift <= max_drift_db:
            kept.append((specs, residual))
        else:
            logger.info(
                f"{len(specs)} section(s) at {residual:.3f} dB drift {drift:.2f} dB "
                f"once published, over the {max_drift_db:.1f} dB limit; not selected"
            )
    if not kept:
        logger.warning(
            "no cascade in the budget survives publication rounding; keeping the most "
            "accurate so the acceptance model can say so"
        )
        return candidates
    return kept


def _prune(
    candidate: tuple[list[BiquadSpec], float],
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    band_hz: tuple[float, float] | None,
    min_contribution_db: float,
) -> tuple[list[BiquadSpec], float]:
    """Drop sections that do nothing, provided the residual does not suffer.

    `fit_to_biquads` spends whatever budget it is handed, so a cascade fitted at four sections
    can arrive with one contributing 0.01 dB. Asking for fewer sections instead is not the
    same thing — the *fit* may genuinely need the freedom, and only afterwards is it visible
    that a section ended up doing nothing. Two of three titles reached a good shape and were
    then rejected for carrying a section worth 0.34 and 0.01 dB.
    """
    specs, residual = candidate
    if len(specs) < 2:
        return candidate
    mask = (
        np.ones_like(freqs, dtype=bool)
        if band_hz is None
        else (freqs >= band_hz[0]) & (freqs <= band_hz[1])
    )
    full = magnitude_db(biquad_sos(specs, fs), freqs, fs)
    kept = [
        section
        for index, section in enumerate(specs)
        if _contribution(specs, index, full, freqs, fs, mask) >= min_contribution_db
    ]
    if len(kept) == len(specs) or not kept:
        return candidate
    pruned = float(
        np.max(np.abs(magnitude_db(biquad_sos(kept, fs), freqs, fs) - target_db)[mask])
    )
    if pruned > residual + min_contribution_db:
        return candidate
    logger.info(
        f"dropped {len(specs) - len(kept)} section(s) contributing under "
        f"{min_contribution_db:g} dB; residual {residual:.3f} -> {pruned:.3f} dB"
    )
    return kept, pruned


def _contribution(
    specs: list[BiquadSpec],
    index: int,
    full: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    mask: np.ndarray,
) -> float:
    without = [s for j, s in enumerate(specs) if j != index]
    if not without:
        return float(np.max(np.abs(full)[mask]))
    reduced = magnitude_db(biquad_sos(without, fs), freqs, fs)
    return float(np.max(np.abs(full - reduced)[mask]))


def fit_to_biquads(
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    sections: int,
    band_hz: tuple[float, float] | None = None,
    placement_band_hz: tuple[float, float] | None = None,
    max_q: float = 6.0,
    max_gain_db: float = 30.0,
    realisation: "Realisation | None" = None,
    seeds: tuple[int, ...] = (0, 1, 2),
) -> tuple[list[BiquadSpec], float]:
    """Minimax fit of `sections` publishable biquads to an arbitrary target.

    The fallback for when `invert_to_shelves` does not apply. Searches every split of the
    budget between low shelves and peaking sections, since a shelf-only cascade cannot always
    reach the target — a steep rolloff terminated by a shallower protective filter needs the
    peaking sections to carry the transition.

    The objective is multimodal and the search is stochastic, so it is run from several seeds
    and the best kept. That matters more than it looks: on an extreme target — a high-order
    rolloff terminated by a much lower-order protective filter, spanning 100 dB — results vary
    by an order of magnitude between seeds, and a single lucky run is not evidence the fit is
    good. Trust `residual_db`, not the section count. Matching the protective filter's
    alignment and order to the rolloff avoids this path entirely (see `invert_to_shelves`).

    Returns the cascade and its maximum absolute error in dB over `band_hz`, which is the
    `residual_db` the contract asks for. Deterministic: the seeds are fixed, so repeat calls on
    identical input reproduce the same answer.
    """
    placement = placement_band_hz or band_hz
    results = _run_fits(
        _structure_tasks(
            target_db,
            freqs,
            fs,
            sections,
            band_hz,
            placement,
            max_q,
            max_gain_db,
            realisation,
            seeds,
        )
    )
    best = min(results, key=lambda r: r[1])
    logger.debug(
        f"Fitted {sections} sections to {best[1]:.4f} dB "
        f"({sum(s.type == 'low_shelf' for s in best[0])} shelves)"
    )
    return best


@dataclass(frozen=True, slots=True)
class Realisation:
    """How the published cascade will actually be realised, for robustness scoring.

    A fit scored only in float64 will happily use large opposing sections that cancel — the
    magnitude is right and the residual says so. On hardware those cancellations do not
    survive coefficient quantisation: measured on one target, a pair of +13.6 and -16.9 dB
    peaks at the same frequency drifts 2.8 dB, while a cascade of the same order with no
    cancellation drifts 0.16 dB. Sensitivity tracks how much the sections rely on each other,
    not their Q.
    """

    fs: float = 96000.0
    """Worst-case publish rate. Higher is worse: the poles sit nearer z=1."""

    coefficient_bits: int = 28
    integer_bits: int = 5
    """Fixed-point format of the target device. 5.23 is the conservative case."""

    drift_samples: int = 48
    """Perturbations used to measure drift as a distribution rather than a point.

    A cascade is published as text and loaded at whatever precision the device accepts, so
    the coefficients that reach the hardware are not the optimiser's. Evaluated once at the
    exact output, a four-section cancelling cascade measured 1.23 dB of drift; jittered
    within the rounding it will actually undergo, the same cascade ranges 1.23 to 18.86 dB.
    The single figure was the luckiest sample in a 15x spread, which is precisely the
    fragility §5.1 exists to reject."""

    publication_precision: tuple[float, float, float] = (0.005, 0.005, 0.0005)
    """Half-step of the precision a filter is published at: frequency, gain, Q.

    A cascade is published as text and reloaded, so the coefficients that reach the hardware
    are not the optimiser's. `accept` judges drift at the 90th percentile over this rounding,
    and the fit has to be scored against the same thing or the optimiser is steering by a
    statistic it is not measured on."""

    def quantise(self, sos: np.ndarray) -> np.ndarray:
        step = 2.0 ** (self.integer_bits - self.coefficient_bits)
        rounded = np.round(np.asarray(sos) / step) * step
        rounded[:, 3] = 1.0
        return rounded


def drift_distribution(
    filters: list[BiquadSpec],
    grid: np.ndarray,
    realisation: Realisation,
) -> np.ndarray:
    """Coefficient drift over the roundings the published filter might undergo.

    Deterministically seeded, so a cascade scores the same every run.
    """
    rng = np.random.default_rng(0)
    freq_step, gain_step, q_step = realisation.publication_precision

    def drift_of(specs: list[BiquadSpec]) -> float:
        sos = biquad_sos(specs, realisation.fs)
        return float(
            np.max(
                np.abs(
                    magnitude_db(realisation.quantise(sos), grid, realisation.fs)
                    - magnitude_db(sos, grid, realisation.fs)
                )
            )
        )

    samples = [drift_of(filters)]
    for _ in range(realisation.drift_samples):
        jittered = [
            BiquadSpec(
                section.type,
                section.freq_hz + rng.uniform(-freq_step, freq_step),
                section.gain_db + rng.uniform(-gain_step, gain_step),
                max(section.q + rng.uniform(-q_step, q_step), 1e-3),
            )
            for section in filters
        ]
        samples.append(drift_of(jittered))
    return np.array(samples)


def _fit_structure(
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    shelves: int,
    peaks: int,
    band_hz: tuple[float, float] | None,
    placement_hz: tuple[float, float] | None,
    max_q: float,
    max_gain_db: float,
    realisation: "Realisation | None",
    seed: int,
) -> tuple[list[BiquadSpec], float, float, int]:
    """One stochastic fit of a fixed shelf/peak split, with its own cost.

    Returns its timing and evaluation count rather than accumulating into `FIT_STATS`: these
    run in worker processes, where a module-level counter would be incremented in the wrong
    interpreter and silently report zero.
    """
    started = time.perf_counter()
    evaluations = 0
    sections = shelves + peaks
    mask = (
        np.ones_like(freqs, dtype=bool)
        if band_hz is None
        else (freqs >= band_hz[0]) & (freqs <= band_hz[1])
    )
    # Evaluate wide, place narrow. The residual has to be scored well above the correction,
    # or a section drifts upward and puts a bump where nothing penalises it — a fit scored on
    # 5-200 Hz once placed a +15.2 dB peak at 378 Hz. But sections must be *placed* only where
    # the correction actually is, or spare budget gets parked in the midrange.
    low = float(placement_hz[0]) if placement_hz else float(freqs[0])
    high = float(placement_hz[1]) if placement_hz else float(freqs[-1])
    bounds = [(low, high), (0.1, max_q), (-max_gain_db, max_gain_db)] * sections

    def cost(p: np.ndarray) -> float:
        nonlocal evaluations
        evaluations += 1
        specs = _unpack(p, shelves, peaks)
        err = magnitude_db(biquad_sos(specs, fs), freqs, fs) - target_db
        worst = float(np.max(np.abs(err[mask])))
        if realisation is not None:
            # Drift at the exact coefficients, deliberately, though `accept` gates on the p90
            # over publication rounding and the two are therefore not the same statistic.
            # Widening this one to match was tried and is worse on every axis. Adding the two
            # antipodal roundings to the max, on the third title's flatten target:
            #
            #   point only          28.2 s   residual 0.432   3 sections   drift p90 1.893
            #   same sign both ways 64.8 s   residual 0.771   2 sections   drift p90 2.712
            #   alternating signs   55.5 s   residual 0.591   2 sections   drift p90 2.590
            #
            # A max over samples makes the objective non-smooth, and the optimiser converges
            # to a worse point on accuracy *and* on the drift the term was added to control,
            # at twice the cost of a stage that is already ~90% of the run. A sensitivity
            # penalty that helped would have to be smooth — the derivative of the response
            # with respect to the coefficients — not a maximum over jittered evaluations.
            device = biquad_sos(specs, realisation.fs)
            drift = magnitude_db(
                realisation.quantise(device), freqs, realisation.fs
            ) - magnitude_db(device, freqs, realisation.fs)
            worst = max(worst, float(np.max(np.abs(drift[mask]))))
        return worst

    coarse = optimize.differential_evolution(
        cost, bounds, seed=seed, maxiter=600, popsize=20, tol=1e-10, polish=True
    )
    fine = optimize.minimize(
        cost,
        coarse.x,
        method="Nelder-Mead",
        options={"maxiter": 60000, "maxfev": 60000, "xatol": 1e-10, "fatol": 1e-12},
    )
    best = fine.x if fine.fun < coarse.fun else coarse.x
    specs, residual = _unpack(best, shelves, peaks), cost(best)
    return specs, residual, time.perf_counter() - started, evaluations


def _unpack(params: np.ndarray, shelves: int, peaks: int) -> list[BiquadSpec]:
    rows = np.asarray(params, dtype=np.float64).reshape(shelves + peaks, 3)
    return [
        BiquadSpec(
            type="low_shelf" if i < shelves else "peaking_eq",
            freq_hz=float(f),
            gain_db=float(g),
            q=float(q),
        )
        for i, (f, q, g) in enumerate(rows)
    ]


def residual_db(
    specs: list[BiquadSpec],
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    band_hz: tuple[float, float] | None = None,
) -> float:
    """Maximum absolute error in dB of a cascade against its target, over `band_hz`.

    The definition designer-interface.md v1.0 §3 fixes for `residual_db`.
    """
    err = magnitude_db(biquad_sos(specs, fs), freqs, fs) - target_db
    if band_hz is not None:
        err = err[(freqs >= band_hz[0]) & (freqs <= band_hz[1])]
    return float(np.max(np.abs(err)))
