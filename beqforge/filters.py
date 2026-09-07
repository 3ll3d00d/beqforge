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
from contextlib import contextmanager
from multiprocessing import cpu_count
from dataclasses import dataclass, field

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


_Z_POWERS: dict[tuple[int, float], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
"""`z**-1` and `z**-2` per grid, since a fit evaluates one grid millions of times.

Keyed on the *identity* of the frequency array rather than its contents, and the array itself
is kept in the value. That is what makes the key safe: holding a reference stops the array
being collected, so its `id` cannot be reused by a different array, and the `is` check below
is then exact rather than probabilistic. Hashing 400 floats per call would cost more than a
few of the exponentials it saves.

Small and cleared wholesale. A fit works one grid; the entries are 400-point arrays; and a
cache that needs an eviction policy here would be solving a problem nobody has.

The one thing it assumes is that a grid is not rewritten in place after it has been evaluated
against. Every grid here is built by `logspace`/`geomspace` and read thereafter, and a
frequency axis that mutated under a cascade would be a bug on its own terms; but the failure
would be silent, so it is stated rather than left to be discovered.
"""

_Z_POWERS_LIMIT = 8


def _z_powers(freqs: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    key = (id(freqs), fs)
    held = _Z_POWERS.get(key)
    if held is not None and held[0] is freqs:
        return held[1], held[2]
    z1 = np.exp(-2j * np.pi * np.asarray(freqs, dtype=np.float64) / fs)
    z2 = z1 * z1
    if len(_Z_POWERS) >= _Z_POWERS_LIMIT:
        _Z_POWERS.clear()
    _Z_POWERS[key] = (freqs, z1, z2)
    return z1, z2


def magnitude_db(sos: np.ndarray, freqs: np.ndarray, fs: float) -> np.ndarray:
    """Magnitude response in dB of a cascade at the given frequencies.

    Evaluated directly rather than through `scipy.signal.sosfreqz`, whose per-call overhead
    dominates the fitting loop by an order of magnitude. Same arithmetic, same coefficients.

    The twiddles are memoised because they depend on the grid and not on the cascade, while
    the fitting loop varies only the cascade: `np.exp` over 400 points was a quarter of this
    function, recomputed identically some ten million times a run. The arithmetic below is
    untouched — `abs(num / den)` rather than the ratio of squared magnitudes, which would be
    a shade faster in principle, measured *slower* in practice, and is not bit-identical
    (1.07e-14 dB). A stage this hot is exactly where an inexact rewrite is least worth its
    risk: the optimiser compares costs, so a last-bit difference can pick a different cascade.
    """
    sections = np.atleast_2d(np.asarray(sos, dtype=np.float64))
    z1, z2 = _z_powers(freqs, fs)
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


@contextmanager
def _fit_pool(tasks_expected: int):
    """One pool for a whole escalation, rather than one per section tier.

    `_run_fits` used to build and tear down an executor per call, which cost nothing when a
    call was the entire fitting stage. Escalating the section budget turns that one call into
    four, and the churn showed up as ~8 s a tier on the title where nothing settles early —
    enough to make escalation a net loss there while it was a large win elsewhere.

    Yields None when there is nothing to parallelise, so the serial path stays serial and
    `PARALLEL_FITS = False` still means what it says.
    """
    if tasks_expected > 1 and PARALLEL_FITS:
        workers = max(1, min(tasks_expected, FIT_WORKERS))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            yield pool
    else:
        yield None


def _run_fits(
    tasks: list["FitTask"],
    pool: "ProcessPoolExecutor | None" = None,
) -> list[tuple[list[BiquadSpec], float, float]]:
    """Run independent fits, in parallel when there is more than one.

    The fits are the entire cost of the design stage and they do not interact, so this is the
    one place parallelism buys anything. Results are returned in submission order and the
    seeds are fixed, so the answer is identical to the serial one — the pool changes how long
    it takes, never what it decides.

    Each result carries its own wall time as well as its cascade, so a caller fitting several
    targets at once can say what each of them cost. `FIT_STATS` only ever knew the total.

    `pool` lets a caller spanning several submissions keep one executor across all of them;
    without it, this owns a pool for the duration of the call as it always did.
    """
    if pool is not None:
        results = list(pool.map(_fit_task, tasks))
    elif len(tasks) > 1 and PARALLEL_FITS:
        workers = max(1, min(len(tasks), FIT_WORKERS))
        with ProcessPoolExecutor(max_workers=workers) as owned:
            results = list(owned.map(_fit_task, tasks))
    else:
        results = [_fit_task(task) for task in tasks]
    for _, _, seconds, evaluations in results:
        FIT_STATS.calls += 1
        FIT_STATS.seconds += seconds
        FIT_STATS.cost_evaluations += evaluations
    return [(specs, residual, seconds) for specs, residual, seconds, _ in results]


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


@dataclass(frozen=True, slots=True)
class FitRequest:
    """One target to fit, with the placement band that belongs to it.

    Placement is per-target rather than per-run: `design` derives it from the target's own
    active span, while the pipeline fixes it. Batching targets together therefore has to carry
    it alongside each one instead of sharing a single value.
    """

    target_db: np.ndarray
    placement_band_hz: tuple[float, float] | None = None
    label: str = ""


@dataclass(slots=True, eq=False)
class _Escalation:
    """One target's state while the section budget is escalated across all of them."""

    request: FitRequest
    screened: list[tuple[list[BiquadSpec], float, bool]] = field(default_factory=list)
    """Per section count, ascending: the pruned cascade, its residual, and whether it
    survives publication rounding."""

    seconds: float = 0.0
    answer: tuple[list[BiquadSpec], float] | None = None

    def settle(self, residual_target_db: float, max_sections: int) -> None:
        """Take the fewest sections that both publish and reach the target, if any yet do.

        Sound to apply before the higher counts have been fitted. The full enumeration returns
        the *first* entry in ascending order that clears both bars, and fitting more sections
        only ever appends later entries — drift screening is per candidate, so nothing fitted
        later can change whether an earlier one passed. If one has already cleared both, it is
        the answer the whole budget would have produced.
        """
        for specs, residual, publishable in self.screened:
            if publishable and residual <= residual_target_db:
                logger.info(
                    f"{self.request.label or 'target'}: {len(specs)} section(s) reach "
                    f"{residual:.3f} dB; the remaining {max_sections - len(specs)} are "
                    "not spent"
                )
                self.answer = (specs, residual)
                return

    def finish(self) -> None:
        """Nothing cleared both bars, so fall back the way the full enumeration does.

        Preferring the cascades that survive rounding, and taking the whole set when none
        does — returning nothing here would abstain without a reason attached, and §2.5 asks
        for the opposite of that.
        """
        kept = [(s, r) for s, r, publishable in self.screened if publishable]
        if not kept:
            logger.warning(
                "no cascade in the budget survives publication rounding; keeping the most "
                "accurate so the acceptance model can say so"
            )
            kept = [(s, r) for s, r, _ in self.screened]
        self.answer = min(kept, key=lambda r: r[1])


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

    One target. `fit_minimal_biquads_all` is the same thing over several, and is what the
    pipeline uses; alone, a target escalating on its own leaves most of the machine idle.
    """
    return fit_minimal_biquads_all(
        [FitRequest(target_db, placement_band_hz)],
        freqs,
        fs,
        max_sections,
        residual_target_db,
        band_hz=band_hz,
        max_q=max_q,
        max_gain_db=max_gain_db,
        realisation=realisation,
        seeds=seeds,
        min_contribution_db=min_contribution_db,
        max_drift_db=max_drift_db,
    )[0]


def fit_minimal_biquads_all(
    requests: list[FitRequest],
    freqs: np.ndarray,
    fs: float,
    max_sections: int,
    residual_target_db: float,
    band_hz: tuple[float, float] | None = None,
    max_q: float = 6.0,
    max_gain_db: float = 30.0,
    realisation: "Realisation | None" = None,
    seeds: tuple[int, ...] = (0, 1, 2),
    min_contribution_db: float = 1.0,
    max_drift_db: float | None = None,
) -> list[tuple[list[BiquadSpec], float]]:
    """Fit every target, escalating the section budget across all of them together.

    Two things at once, and they only work as a pair.

    **Escalate rather than enumerate.** The budget goes as the cube of `max_sections` — the
    four-section tier alone is 59% of it — and most targets never need it: of eleven fits over
    the four titles, five settle at two sections and seven at three. Fitting a tier only when
    the tiers below it have failed to settle spends about half the CPU. `settle` argues why
    that is the same answer rather than an approximation of it.

    **One tier, every target.** Escalating a single target starves the pool: its first tier is
    two tasks for seven workers, which is why this was enumerated up front in the first place.
    Escalating all of them in step puts every undecided target's tier into one submission, so
    the width comes from the number of targets rather than from spending budget nothing needs.
    A run fits four targets, so a tier is 8 to 32 tasks instead of 2 to 8.

    Deterministic and order-preserving: `_run_fits` returns in submission order, tasks are
    seeded, and results are handed back to the target that asked for them.
    """
    states = [_Escalation(request) for request in requests]
    widest = len(requests) * max_sections * len(seeds)
    with _fit_pool(widest) as pool:
        _escalate(
            states,
            pool,
            freqs,
            fs,
            max_sections,
            residual_target_db,
            band_hz,
            max_q,
            max_gain_db,
            realisation,
            seeds,
            min_contribution_db,
            max_drift_db,
        )

    for state in states:
        if state.answer is None:
            state.finish()
        if state.request.label:
            logger.info(
                f"  {state.request.label}: {len(state.answer[0])} section(s) at "
                f"{state.answer[1]:.3f} dB, {state.seconds:.0f} CPU-s"
            )
    return [state.answer for state in states]


def _escalate(
    states: list["_Escalation"],
    pool: "ProcessPoolExecutor | None",
    freqs: np.ndarray,
    fs: float,
    max_sections: int,
    residual_target_db: float,
    band_hz: tuple[float, float] | None,
    max_q: float,
    max_gain_db: float,
    realisation: "Realisation | None",
    seeds: tuple[int, ...],
    min_contribution_db: float,
    max_drift_db: float | None,
) -> None:
    """Fit one group of section counts at a time, across every target not yet settled."""
    for group in _tiers(max_sections):
        pending = [state for state in states if state.answer is None]
        if not pending:
            break
        tasks: list["FitTask"] = []
        owners: list[tuple[_Escalation, int]] = []
        for sections in group:
            for state in pending:
                built = _structure_tasks(
                    state.request.target_db,
                    freqs,
                    fs,
                    sections,
                    band_hz,
                    state.request.placement_band_hz or band_hz,
                    max_q,
                    max_gain_db,
                    realisation,
                    seeds,
                )
                tasks.extend(built)
                owners.extend([(state, sections)] * len(built))
        results = _run_fits(tasks, pool)
        # section counts are screened in ascending order whatever order they were submitted
        # in, because `settle` takes the first entry that clears both bars and "first" has to
        # mean fewest sections
        for (state, _), window in sorted(
            _by_owner(owners, results).items(), key=lambda item: item[0][1]
        ):
            best = min(window, key=lambda r: r[1])
            state.seconds += sum(seconds for _, _, seconds in window)
            specs, residual = _prune(
                (best[0], best[1]),
                state.request.target_db,
                freqs,
                fs,
                band_hz,
                min_contribution_db,
            )
            state.screened.append(
                (
                    specs,
                    residual,
                    _publishable(specs, residual, freqs, realisation, max_drift_db),
                )
            )
        for state in pending:
            state.settle(residual_target_db, max_sections)


def _tiers(max_sections: int) -> list[tuple[int, ...]]:
    """Section counts to fit in one submission, and what to defer behind the decision.

    Everything below the top count together, then the top count only if nothing settled.

    Escalating one count at a time was the obvious design and is measurably worse. Two things
    work against it. The budget is dominated by its top tier — relative cost runs 7, 38, 105,
    218 across four sections, so 59% of it is the last one and the only decision worth a
    barrier is whether that one is needed. And a tier is uniform: every task in it has the
    same section count and so the same duration, which packs into `ceil(n / workers)` rounds
    with an idle tail, where the mixed durations of a whole budget fill each other's gaps.
    Measured on the title where nothing settles early, one-at-a-time spent 218 s of fitting
    against 187 s for the same work submitted together — and holding a single pool across the
    tiers, tried first on the assumption that the cost was executor churn, changed nothing.

    Grouped this way, a target that settles anywhere below the top still skips the tier that
    is most of the budget, and a target that does not pays one barrier rather than three.
    """
    if max_sections <= 1:
        return [(1,)]
    return [tuple(range(1, max_sections)), (max_sections,)]


def _by_owner(
    owners: list[_Escalation], results: list[tuple[list[BiquadSpec], float, float]]
) -> dict[_Escalation, list[tuple[list[BiquadSpec], float, float]]]:
    """Results back to the target that asked for them, in submission order."""
    grouped: dict[_Escalation, list] = {}
    for owner, result in zip(owners, results, strict=True):
        grouped.setdefault(owner, []).append(result)
    return grouped


def _publishable(
    specs: list[BiquadSpec],
    residual: float,
    freqs: np.ndarray,
    realisation: "Realisation | None",
    max_drift_db: float | None,
) -> bool:
    """Whether this cascade survives the rounding it will be published at.

    Per candidate, so it can be asked as each section count arrives rather than only once the
    whole budget has been spent. That is what lets the escalation stop early and still reach
    the answer the full enumeration would.
    """
    if realisation is None or max_drift_db is None:
        return True
    drift = float(np.percentile(drift_distribution(specs, freqs, realisation), 90))
    if drift <= max_drift_db:
        return True
    logger.info(
        f"{len(specs)} section(s) at {residual:.3f} dB drift {drift:.2f} dB "
        f"once published, over the {max_drift_db:.1f} dB limit; not selected"
    )
    return False


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
    return best[0], best[1]


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
        sos = biquad_sos(specs, fs)
        response = magnitude_db(sos, freqs, fs)
        worst = float(np.max(np.abs((response - target_db)[mask])))
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
            #
            # The realised cascade is the published one whenever the two rates agree, which
            # they do by default — `PUBLISH_FS` and `Realisation.fs` are both 96 kHz. Built
            # and evaluated again regardless, that was a second `biquad_sos` and a third
            # `magnitude_db` per evaluation, some ten million times a run, for an answer
            # already in hand. Branching rather than assuming, so a `Realisation` at another
            # rate still gets its own.
            if realisation.fs == fs:
                device, undrifted = sos, response
            else:
                device = biquad_sos(specs, realisation.fs)
                undrifted = magnitude_db(device, freqs, realisation.fs)
            drift = (
                magnitude_db(realisation.quantise(device), freqs, realisation.fs)
                - undrifted
            )
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
