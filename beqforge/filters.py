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
    target_db: np.ndarray, freqs: np.ndarray, threshold_db: float = 0.5
) -> tuple[float, float]:
    """The span over which a target actually asks for something, widened by half an octave.

    Sections belong where the correction is, not merely inside the band the residual is scored
    over. A bass correction that is flat above 25 Hz has no business placing a section at
    105 Hz, and one that does is spending budget to achieve nothing.
    """
    active = np.abs(target_db) >= threshold_db
    if not active.any():
        return float(freqs[0]), float(freqs[-1])
    low, high = float(freqs[active].min()), float(freqs[active].max())
    return max(float(freqs[0]), low / 1.5), min(float(freqs[-1]), high * 1.5)


def fit_minimal_biquads(
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    max_sections: int,
    residual_target_db: float,
    band_hz: tuple[float, float] | None = None,
    placement_band_hz: tuple[float, float] | None = None,
    max_q: float = 6.0,
    realisation: "Realisation | None" = None,
    seeds: tuple[int, ...] = (0, 1, 2),
) -> tuple[list[BiquadSpec], float]:
    """The fewest sections that reach `residual_target_db`, or the best within the budget.

    `fit_to_biquads` spends whatever budget it is given, so asking it for four sections when
    three will do parks the fourth somewhere harmless at a fraction of a dB. A section that
    does nothing is not free: it occupies a slot, it has to be published, and it invites the
    reader to believe it means something.
    """
    best: tuple[list[BiquadSpec], float] | None = None
    for sections in range(1, max_sections + 1):
        candidate = fit_to_biquads(
            target_db,
            freqs,
            fs,
            sections,
            band_hz,
            placement_band_hz,
            max_q,
            realisation,
            seeds,
        )
        if best is None or candidate[1] < best[1]:
            best = candidate
        if candidate[1] <= residual_target_db:
            logger.info(
                f"{sections} section(s) reach {candidate[1]:.3f} dB; "
                f"not spending the remaining {max_sections - sections}"
            )
            return candidate
    assert best is not None
    return best


def fit_to_biquads(
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    sections: int,
    band_hz: tuple[float, float] | None = None,
    placement_band_hz: tuple[float, float] | None = None,
    max_q: float = 6.0,
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
    best: tuple[list[BiquadSpec], float] | None = None
    for shelves in range(1, sections + 1):
        for seed in seeds:
            candidate = _fit_structure(
                target_db,
                freqs,
                fs,
                shelves,
                sections - shelves,
                band_hz,
                placement,
                max_q,
                realisation,
                seed,
            )
            if best is None or candidate[1] < best[1]:
                best = candidate
    assert best is not None
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

    def quantise(self, sos: np.ndarray) -> np.ndarray:
        step = 2.0 ** (self.integer_bits - self.coefficient_bits)
        rounded = np.round(np.asarray(sos) / step) * step
        rounded[:, 3] = 1.0
        return rounded


def _fit_structure(
    target_db: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    shelves: int,
    peaks: int,
    band_hz: tuple[float, float] | None,
    placement_hz: tuple[float, float] | None,
    max_q: float,
    realisation: "Realisation | None",
    seed: int,
) -> tuple[list[BiquadSpec], float]:
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
    bounds = [(low, high), (0.1, max_q), (-25.0, 45.0)] * sections

    def cost(p: np.ndarray) -> float:
        specs = _unpack(p, shelves, peaks)
        err = magnitude_db(biquad_sos(specs, fs), freqs, fs) - target_db
        worst = float(np.max(np.abs(err[mask])))
        if realisation is not None:
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
    return _unpack(best, shelves, peaks), cost(best)


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
