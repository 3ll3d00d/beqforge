"""Offline coefficient optimisation; no device or audio dependencies."""

import hashlib
import json
from dataclasses import asdict, dataclass
from itertools import product
from typing import Protocol

import numpy as np
from scipy.optimize import minimize_scalar

from beq_common import __version__
from beq_common.biquad import HighShelf, LowShelf, PeakingEQ


class Precision(Protocol):
    """Storage conversion and adjacent representable values, independently of rate."""

    name: str

    def quantise(self, values: np.ndarray) -> np.ndarray: ...
    def neighbours(self, value: float) -> tuple[float, ...]: ...


@dataclass(frozen=True, slots=True)
class Float32:
    name: str = "float32"

    def quantise(self, values: np.ndarray) -> np.ndarray:
        return np.asarray(values).astype(np.float32).astype(np.float64)

    def neighbours(self, value: float) -> tuple[float, ...]:
        x = np.float32(value)
        return (
            float(np.nextafter(x, np.float32(-np.inf))),
            float(x),
            float(np.nextafter(x, np.float32(np.inf))),
        )


@dataclass(frozen=True, slots=True)
class FixedPoint:
    """Signed fixed-point storage, including the sign bit in integer_bits."""

    integer_bits: int = 5
    fractional_bits: int = 23

    def __post_init__(self):
        if self.integer_bits < 1 or self.fractional_bits < 0:
            raise ValueError("invalid fixed-point precision")

    @property
    def name(self) -> str:
        return f"fixed{self.integer_bits}.{self.fractional_bits}"

    def quantise(self, values: np.ndarray) -> np.ndarray:
        step = 2.0**-self.fractional_bits
        result = np.rint(np.asarray(values) / step) * step
        limit = 2.0 ** (self.integer_bits - 1)
        if np.any(result < -limit) or np.any(result >= limit):
            raise ValueError("coefficient outside storage range")
        return result

    def neighbours(self, value: float) -> tuple[float, ...]:
        step = 2.0**-self.fractional_bits
        return tuple(value + i * step for i in (-1, 0, 1))


@dataclass(frozen=True, slots=True)
class Section:
    type: str
    freq: float
    q: float
    gain: float

    def sos(self, rate: int) -> np.ndarray:
        if (
            self.type not in ("PeakingEQ", "LowShelf", "HighShelf")
            or not np.all(np.isfinite([self.freq, self.q, self.gain]))
            or not 0 < self.freq < rate / 2
            or self.q <= 0
        ):
            raise ValueError("invalid RBJ section")
        constructor = {
            "PeakingEQ": PeakingEQ,
            "LowShelf": LowShelf,
            "HighShelf": HighShelf,
        }[self.type]
        return np.asarray(
            constructor(rate, self.freq, self.q, self.gain).get_sos()[0], dtype=float
        )


def stable(sos: np.ndarray) -> bool:
    return bool(
        np.all(np.isfinite(sos))
        and np.all(sos[:, 3] == 1)
        and np.all(1 + sos[:, 4] + sos[:, 5] > 0)
        and np.all(1 - sos[:, 4] + sos[:, 5] > 0)
        and np.all(1 - sos[:, 5] > 0)
    )


def magnitude(sos: np.ndarray, frequencies: np.ndarray, rate: int) -> np.ndarray:
    z = np.exp(
        -2j * np.longdouble(np.pi) * np.asarray(frequencies, dtype=np.longdouble) / rate
    )
    result = np.zeros(z.shape, dtype=np.longdouble)
    for b0, b1, b2, _, a1, a2 in np.asarray(sos, dtype=np.longdouble):
        result += 20 * np.log10(
            np.abs((b0 + z * (b1 + z * b2)) / (1 + z * (a1 + z * a2)))
        )
    return np.asarray(result, dtype=float)


@dataclass(frozen=True, slots=True)
class Settings:
    margin_db: float = 0.5
    band_hz: tuple[float, float] = (2.0, 200.0)
    passes: int = 6
    grid_points: int = 512
    validation_points: int = 8192
    numerical_tolerance_db: float = 1e-6

    def __post_init__(self):
        if (
            not np.all(
                np.isfinite(
                    [
                        self.margin_db,
                        *self.band_hz,
                        self.numerical_tolerance_db,
                    ]
                )
            )
            or self.margin_db <= 0
            or not 0 < self.band_hz[0] < self.band_hz[1]
            or self.passes < 1
            or self.grid_points < 32
            or self.validation_points < 256
            or self.numerical_tolerance_db <= 0
        ):
            raise ValueError("invalid optimisation settings")


# outcomes which carry coefficients to publish
PUBLISHED_OUTCOMES = ("replacement", "improvement")


@dataclass(frozen=True, slots=True)
class Result:
    outcome: str
    rate: int
    precision: str
    margin_db: float
    original_error_db: float
    transport_precision: str = "float64"
    band_hz: tuple[float, float] = (2.0, 200.0)
    candidate_error_db: float | None = None
    guard_error_db: float | None = None
    replacement: tuple[tuple[float, ...], ...] | None = None
    evaluations: int = 0
    source_digest: str = ""
    version: str = __version__


def _maximum(reference, candidate, rate, band, points):
    f = np.geomspace(*band, points)

    def error(x):
        return np.abs(
            magnitude(candidate, np.atleast_1d(x), rate)
            - magnitude(reference, np.atleast_1d(x), rate)
        )

    e = error(f)
    if not np.all(np.isfinite(e)):
        return float("inf")
    worst = float(np.max(e))
    for i in np.flatnonzero((e[1:-1] > e[:-2]) & (e[1:-1] >= e[2:])) + 1:
        opt = minimize_scalar(
            lambda x: -float(error(x)[0]),
            bounds=(f[i - 1], f[i + 1]),
            method="bounded",
            options={"xatol": 1e-9},
        )
        worst = max(worst, -float(opt.fun))
    return worst


def _validated_maximum(reference, candidate, rate, band, settings):
    coarse = _maximum(reference, candidate, rate, band, settings.validation_points)
    fine = _maximum(reference, candidate, rate, band, settings.validation_points * 2)
    return max(coarse, fine), bool(
        np.isfinite(fine) and abs(fine - coarse) <= settings.numerical_tolerance_db
    )


def optimise(
    reference,
    *,
    rate: int,
    precision: Precision | None = None,
    transport: Precision | None = None,
    sent=None,
    settings: Settings | None = None,
) -> Result:
    """Return custom SOS when the original exceeds the margin and a candidate improves on it.

    Candidates are assessed over the matching band only. Outcomes for a search: ``replacement``
    when the candidate meets the margin, ``improvement`` when it does not but is strictly better
    than the original, otherwise ``no_replacement``. Both ``replacement`` and ``improvement``
    carry the coefficients and must be stable and survive publication/reload. The error outside
    the matching band is reported as ``guard_error_db`` but does not affect the outcome.

    reference and sent use normalised SOS [b0,b1,b2,1,a1,a2], subtractive feedback.
    Maxima are dense-grid/refined numerical estimates, not certified uniform bounds.
    """
    if rate not in (48000, 96000):
        raise ValueError("supported internal rates are 48000 and 96000")
    p, cfg = precision or Float32(), settings or Settings()
    ref = np.array(reference, dtype=float, copy=True)
    original = np.array(ref if sent is None else sent, dtype=float, copy=True)
    if (
        ref.ndim != 2
        or ref.shape[1] != 6
        or not len(ref)
        or original.shape != ref.shape
        or not np.all(np.isfinite(original))
        or not np.all(original[:, 3] == 1)
        or not stable(ref)
    ):
        raise ValueError("invalid or unstable reference cascade")
    if cfg.band_hz[1] >= rate / 2:
        raise ValueError("matching band must be below Nyquist")

    def store(x):
        # Decimal publication and reload, followed by transport and storage.
        x = np.array([[float(format(v, ".17g")) for v in row] for row in x])
        return p.quantise(transport.quantise(x) if transport else x)

    base = store(original)
    baseline, baseline_converged = (
        _validated_maximum(ref, base, rate, cfg.band_hz, cfg)
        if stable(base)
        else (float("inf"), True)
    )
    source_digest = hashlib.sha256(
        json.dumps(
            {
                "reference": ref.tolist(),
                "sent": original.tolist(),
                "rate": rate,
                "storage": p.name,
                "transport": transport.name if transport else "float64",
                "settings": asdict(cfg),
                "version": __version__,
            },
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()

    def result(outcome, **kwargs):
        return Result(
            outcome,
            rate,
            p.name,
            cfg.margin_db,
            baseline,
            transport_precision=transport.name if transport else "float64",
            band_hz=cfg.band_hz,
            source_digest=source_digest,
            **kwargs,
        )

    if not baseline_converged:
        return result("unresolved")
    if baseline <= cfg.margin_db:
        if cfg.margin_db - baseline < cfg.numerical_tolerance_db:
            return result("unresolved")
        return result("within_margin")
    if np.isfinite(baseline) and baseline - cfg.margin_db < cfg.numerical_tolerance_db:
        return result("unresolved")
    current = base.copy()
    frequencies = np.geomspace(*cfg.band_hz, cfg.grid_points)
    target = magnitude(ref, frequencies, rate)

    def score(x):
        return (
            float(np.max(np.abs(magnitude(x, frequencies, rate) - target)))
            if stable(x)
            else float("inf")
        )

    best, evaluations = score(current), 0
    indices = [0, 1, 2, 4, 5]
    for _ in range(cfg.passes):
        changed = False
        for section in range(len(current)):
            chosen, value = current.copy(), best
            options = [p.neighbours(current[section, i]) for i in indices]
            for combination in product(*options):
                trial = current.copy()
                trial[section, indices] = combination
                try:
                    trial = store(trial)
                except ValueError:
                    continue
                evaluations += 1
                cost = score(trial)
                if cost < value:
                    chosen, value = trial, cost
            if value < best:
                current, best, changed = chosen, value, True
        if not changed:
            break
    measured, converged = (
        _validated_maximum(ref, current, rate, cfg.band_hz, cfg)
        if stable(current)
        else (float("inf"), False)
    )
    # Guard both sides of the match band, including frequencies near DC and Nyquist.
    bands = [
        (min(1e-4, cfg.band_hz[0] / 2), cfg.band_hz[0]),
        (cfg.band_hz[1], (cfg.band_hz[1] + rate / 2) / 2),
    ]
    bands.append((bands[-1][1], rate / 2))
    endpoints = np.array([0.0, rate / 2])

    def guard_error(x) -> tuple[float, bool]:
        results = [_validated_maximum(ref, x, rate, b, cfg) for b in bands]
        value = max(v for v, _ in results)
        endpoint_error = np.max(
            np.abs(magnitude(x, endpoints, rate) - magnitude(ref, endpoints, rate))
        )
        value = (
            max(value, float(endpoint_error))
            if np.isfinite(endpoint_error)
            else float("inf")
        )
        return value, all(ok for _, ok in results)

    # recorded for information only, decisions are made on the matching band alone
    guard, _ = guard_error(current)
    publishable = stable(current) and np.array_equal(store(current), current)
    if abs(measured - cfg.margin_db) < cfg.numerical_tolerance_db or not converged:
        outcome = "unresolved"
    elif publishable and measured <= cfg.margin_db:
        outcome = "replacement"
    elif publishable and measured < baseline - cfg.numerical_tolerance_db:
        # outside the margin but better than what would be loaded today (an original which
        # can't be represented has an infinite error so any publishable candidate is better)
        outcome = "improvement"
    else:
        outcome = "no_replacement"
    return result(
        outcome,
        candidate_error_db=measured,
        guard_error_db=guard,
        replacement=tuple(tuple(float(v) for v in row) for row in current)
        if outcome in PUBLISHED_OUTCOMES
        else None,
        evaluations=evaluations,
    )
