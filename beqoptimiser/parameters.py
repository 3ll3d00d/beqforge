"""Optimise a cascade's parameters, not its coefficients, for several device profiles at once.

`core.optimise` searches one cascade's coefficients for one rate and precision and publishes
custom SOS. A BEQ is published and loaded as parameters (beqdesigner's projects and exports,
the catalogue, ezbeq rebuilding RBJ coefficients at each device's rate), so this searches each
section's frequency, Q and gain instead: the result is a filter every consumer already carries,
realised by every device from the same numbers.

* **Whose RBJ.** beqdesigner (`model/iir.py`), `beq_common.biquad` and ezbeq (`ezbeq/iir.py`)
  compute identical coefficients, bit for bit, for parameters on the publication grid (checked
  on 20,000 random peaks and shelves at both rates, October 2026). Off it they differ: ezbeq
  rounds Q to 4 and gain to 3 decimal places before computing, the others do not. So the search
  never leaves the grid, and `Section.sos` (`beq_common.biquad`) models every consumer.
* **The grid.** What beqdesigner shows and the exports keep: frequency to 0.01 Hz, Q to 0.0001,
  gain to 0.01 dB. A shelf's Q is searched, as stored; S is only a way of displaying it.
* **Reference and realisation.** Each section's ideal float64 RBJ response from the authored
  parameters is the reference, per rate. A profile realises the candidate parameters as RBJ
  coefficients at its rate in float64, published as 17-digit decimals and stored at its
  precision, as a device holds coefficients computed from parameters. The original is the
  authored parameters on the grid, realised the same way.
* **Several profiles.** The search minimises the worst matching-band error over the profiles,
  and refuses any step that makes a profile worse than both its original error and the margin,
  so helping one device cannot quietly cost another.
* **Bounds.** Each parameter may move only as far as keeps the filter the author's (default
  ±1% frequency, ±2% Q, ±0.1 dB gain, about the authored value).
* **Search.** Deterministic compass search on the integer grid: each parameter of each section
  tries ± a step, steps halving from half its bound to one grid unit, then every ±1 combination
  of each section's three parameters until nothing improves. Identical adjacent sections (a
  repeated shelf) move together and stay identical.
* **Outcomes.** As `core.optimise`, on the worst profile: ``within_margin`` with no search,
  ``replacement`` when every profile meets the margin, ``improvement`` when the worst is
  strictly better than the original's, otherwise ``no_replacement``; ``unresolved`` near a
  boundary or when an error estimate does not converge. A cascade with nothing searchable that
  needs a search is ``no_replacement``.
"""

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from itertools import product

import numpy as np

from .core import Precision, Section, _validated_maximum, magnitude, stable

# The version of what this module computes; cached parameter results are keyed by it. Bump it
# when a change alters any result, and only then.
PARAMETER_VERSION = "0.1.1"

SEARCHABLE = ("PeakingEQ", "LowShelf", "HighShelf")
RATES = (48000, 96000)
# The publication grid, in units per parameter: 0.01 Hz, Q 0.0001, 0.01 dB.
GRID = (100, 10000, 100)


@dataclass(frozen=True, slots=True)
class Fixed:
    """A biquad the search may not change (a pass filter, a gain stage), as normalised SOS
    [b0, b1, b2, 1, a1, a2] (subtractive feedback) for each rate a profile may use. It counts
    in the cascade's response and is realised at each profile's precision like the rest."""

    coefficients: tuple[tuple[int, tuple[float, ...]], ...]

    @classmethod
    def of(cls, by_rate: dict[int, Sequence[float]]) -> "Fixed":
        return cls(
            tuple(
                (int(rate), tuple(float(v) for v in sos))
                for rate, sos in sorted(by_rate.items())
            )
        )

    def sos(self, rate: int) -> np.ndarray:
        for r, row in self.coefficients:
            if r == rate:
                values = np.asarray(row, dtype=float)
                if values.shape != (6,) or values[3] != 1:
                    raise ValueError("fixed section must be normalised SOS")
                return values
        raise ValueError(f"fixed section has no coefficients for {rate} Hz")


@dataclass(frozen=True, slots=True)
class ParameterSettings:
    margin_db: float = 0.5
    band_hz: tuple[float, float] = (2.0, 200.0)
    freq_bound: float = 0.01
    q_bound: float = 0.02
    gain_bound_db: float = 0.1
    grid_points: int = 512
    validation_points: int = 8192
    numerical_tolerance_db: float = 1e-6
    max_evaluations: int = 20000

    def __post_init__(self):
        values = [
            self.margin_db,
            *self.band_hz,
            self.freq_bound,
            self.q_bound,
            self.gain_bound_db,
            self.numerical_tolerance_db,
        ]
        if (
            not np.all(np.isfinite(values))
            or self.margin_db <= 0
            or not 0 < self.band_hz[0] < self.band_hz[1]
            or not 0 <= self.freq_bound < 1
            or not 0 <= self.q_bound < 1
            or self.gain_bound_db < 0
            or self.grid_points < 32
            or self.validation_points < 256
            or self.numerical_tolerance_db <= 0
            or self.max_evaluations < 1
        ):
            raise ValueError("invalid parameter optimisation settings")


@dataclass(frozen=True, slots=True)
class ProfileError:
    """One profile's matching-band error before and after, and the candidate's guard
    (out-of-band) error, reported and never decided on."""

    rate: int
    precision: str
    original_error_db: float
    candidate_error_db: float | None = None
    guard_error_db: float | None = None


@dataclass(frozen=True, slots=True)
class ParameterResult:
    outcome: str
    margin_db: float
    band_hz: tuple[float, float]
    original_error_db: float
    profiles: tuple[ProfileError, ...]
    candidate_error_db: float | None = None
    sections: tuple[Section | Fixed, ...] | None = None
    evaluations: int = 0
    source_digest: str = ""
    version: str = PARAMETER_VERSION


PUBLISHED_OUTCOMES = ("replacement", "improvement")


def _on_grid(section: Section) -> Section:
    return Section(
        section.type,
        round(section.freq, 2),
        round(section.q, 4),
        round(section.gain, 2),
    )


def _units(section: Section) -> tuple[int, int, int]:
    return tuple(
        round(v * g)
        for v, g in zip((section.freq, section.q, section.gain), GRID, strict=True)
    )


def _section(kind: str, units: Sequence[int]) -> Section:
    # rounded so the float is exactly what a two- or four-decimal text says
    return Section(
        kind,
        round(units[0] / GRID[0], 2),
        round(units[1] / GRID[1], 4),
        round(units[2] / GRID[2], 2),
    )


def _bounds(section: Section, cfg: ParameterSettings) -> list[tuple[int, int]]:
    """Inclusive grid-unit bounds about the authored value, never past it to a sign change
    or a non-positive frequency or Q."""
    spans = (
        abs(section.freq) * cfg.freq_bound,
        abs(section.q) * cfg.q_bound,
        cfg.gain_bound_db,
    )
    bounds = []
    for value, span, grid, floor in zip(
        (section.freq, section.q, section.gain), spans, GRID, (1, 1, None), strict=True
    ):
        low = math.ceil(round((value - span) * grid, 6))
        high = math.floor(round((value + span) * grid, 6))
        if floor is not None:
            low = max(low, floor)
        centre = round(value * grid)
        bounds.append((min(low, centre), max(high, centre)))
    return bounds


def _store(sos: np.ndarray, precision: Precision) -> np.ndarray:
    """Decimal publication and reload, then the profile's storage."""
    loaded = np.array([[float(format(v, ".17g")) for v in row] for row in sos])
    return precision.quantise(loaded)


def _guard(reference, candidate, rate, cfg) -> float:
    """The worst error outside the matching band, near DC and Nyquist included, as
    `core.optimise` reports it."""
    bands = [
        (min(1e-4, cfg.band_hz[0] / 2), cfg.band_hz[0]),
        (cfg.band_hz[1], (cfg.band_hz[1] + rate / 2) / 2),
    ]
    bands.append((bands[-1][1], rate / 2))
    value = max(
        _validated_maximum(reference, candidate, rate, b, cfg)[0] for b in bands
    )
    endpoints = np.array([0.0, rate / 2])
    # A high-pass is exactly zero at DC, -inf dB, in the reference and in a candidate that
    # keeps its zero: that agreement is no error, where core's subtraction makes it NaN, an
    # infinite guard error and numpy warnings. A zero only one of them has is still infinite.
    with np.errstate(divide="ignore", invalid="ignore"):
        got = magnitude(candidate, endpoints, rate)
        want = magnitude(reference, endpoints, rate)
        endpoint = float(np.max(np.where(got == want, 0.0, np.abs(got - want))))
    return max(value, endpoint) if np.isfinite(endpoint) else float("inf")


class _Profile:
    """One profile's reference and its realised cascade's response, section by section, so
    a trial recomputes only the sections it changes."""

    def __init__(self, rate, precision, cascade, frequencies):
        self.rate, self.precision, self.frequencies = rate, precision, frequencies
        self.reference = np.array([s.sos(rate) for s in cascade])
        self.target = magnitude(self.reference, frequencies, rate)
        self.rows = [None] * len(cascade)
        self.responses = np.zeros((len(cascade), len(frequencies)))

    def realise(self, sos: np.ndarray) -> np.ndarray | None:
        try:
            stored = _store(sos[None, :], self.precision)
        except ValueError:
            return None
        return stored if stable(stored) else None

    def response(self, stored: np.ndarray) -> np.ndarray:
        return magnitude(stored, self.frequencies, self.rate)


def optimise_parameters(
    sections: Sequence[Section | Fixed],
    *,
    profiles: Sequence[tuple[int, Precision]],
    settings: ParameterSettings | None = None,
) -> ParameterResult:
    """Search the sections' frequency, Q and gain for the profiles jointly; see the module
    docstring for what is searched, how it is judged and what each outcome means."""
    cfg = settings or ParameterSettings()
    cascade = tuple(sections)
    if not cascade or not all(isinstance(s, (Section, Fixed)) for s in cascade):
        raise ValueError("sections must be a non-empty sequence of Section or Fixed")
    for s in cascade:
        if isinstance(s, Section) and s.type not in SEARCHABLE:
            raise ValueError(f"unsupported section type {s.type!r}")
    chosen: list[tuple[int, Precision]] = []
    for rate, precision in profiles:
        if rate not in RATES:
            raise ValueError("supported profile rates are 48000 and 96000")
        if cfg.band_hz[1] >= rate / 2:
            raise ValueError("matching band must be below Nyquist")
        if (rate, precision.name) not in [(r, p.name) for r, p in chosen]:
            chosen.append((rate, precision))
    if not chosen:
        raise ValueError("at least one profile is required")

    frequencies = np.geomspace(*cfg.band_hz, cfg.grid_points)
    states = [_Profile(rate, p, cascade, frequencies) for rate, p in chosen]
    for state in states:
        if not stable(state.reference):
            raise ValueError("invalid or unstable reference cascade")

    # identical adjacent sections move together: a repeated shelf stays one shelf x n
    groups: list[list[int]] = []
    for i, s in enumerate(cascade):
        if isinstance(s, Section):
            if groups and cascade[groups[-1][-1]] == s and groups[-1][-1] == i - 1:
                groups[-1].append(i)
            else:
                groups.append([i])
    authored = [cascade[g[0]] for g in groups]
    start = [list(_units(_on_grid(s))) for s in authored]
    bounds = [_bounds(s, cfg) for s in authored]

    def rows_for(state, group, units):
        """Each section of a group realised at the state's profile, or None if unusable."""
        stored = state.realise(_section(authored[group].type, units).sos(state.rate))
        return stored

    # the original: authored parameters on the grid, every fixed section as given
    usable = True
    for state in states:
        for i, s in enumerate(cascade):
            if isinstance(s, Fixed):
                stored = state.realise(s.sos(state.rate))
            else:
                group = next(k for k, g in enumerate(groups) if i in g)
                stored = rows_for(state, group, start[group])
            if stored is None:
                usable = False
                stored = np.array([[np.nan] * 3 + [1.0, np.nan, np.nan]])
            state.rows[i] = stored[0]
            state.responses[i] = state.response(stored) if usable else np.nan

    originals = []
    converged_all = True
    for state in states:
        realised = np.array(state.rows)
        if usable and stable(realised):
            error, converged = _validated_maximum(
                state.reference, realised, state.rate, cfg.band_hz, cfg
            )
        else:
            error, converged = float("inf"), True
        originals.append(error)
        converged_all &= converged
    baseline = max(originals)
    source_digest = hashlib.sha256(
        json.dumps(
            {
                "sections": [asdict(s) | {"kind": type(s).__name__} for s in cascade],
                "profiles": [[rate, p.name] for rate, p in chosen],
                "settings": asdict(cfg),
                "version": PARAMETER_VERSION,
            },
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()

    def result(outcome, profile_errors=None, **kwargs):
        return ParameterResult(
            outcome,
            cfg.margin_db,
            cfg.band_hz,
            baseline,
            profile_errors
            or tuple(
                ProfileError(s.rate, s.precision.name, e)
                for s, e in zip(states, originals, strict=True)
            ),
            source_digest=source_digest,
            **kwargs,
        )

    if not converged_all:
        return result("unresolved")
    if baseline <= cfg.margin_db:
        if cfg.margin_db - baseline < cfg.numerical_tolerance_db:
            return result("unresolved")
        return result("within_margin")
    if np.isfinite(baseline) and baseline - cfg.margin_db < cfg.numerical_tolerance_db:
        return result("unresolved")
    if not groups or not usable:
        # nothing to search, or a fixed section no profile can hold
        return result("no_replacement")

    # a profile may get worse, but never past both its original error and the margin
    ceilings = [max(e, cfg.margin_db) for e in originals]
    current = [list(u) for u in start]
    evaluations = 0

    def try_group(group, units):
        """(worst error, per-profile rows and responses) for one group moved, or None."""
        nonlocal evaluations
        evaluations += 1
        changes = []
        worst = 0.0
        for state, ceiling in zip(states, ceilings, strict=True):
            stored = rows_for(state, group, units)
            if stored is None:
                return None
            response = state.response(stored)
            total = state.responses.sum(axis=0) + (
                len(groups[group]) * response
                - state.responses[groups[group]].sum(axis=0)
            )
            error = float(np.max(np.abs(total - state.target)))
            if error > ceiling:
                return None
            worst = max(worst, error)
            changes.append((stored[0], response))
        return worst, changes

    def apply(group, units, changes):
        current[group] = list(units)
        for state, (row, response) in zip(states, changes, strict=True):
            for i in groups[group]:
                state.rows[i] = row
                state.responses[i] = response

    def score():
        return max(
            float(np.max(np.abs(s.responses.sum(axis=0) - s.target))) for s in states
        )

    best = score()

    def improve(group, candidates) -> bool:
        nonlocal best
        chosen_units, chosen_changes, chosen_score = None, None, best
        for units in candidates:
            if evaluations >= cfg.max_evaluations:
                break
            if any(
                not lo <= u <= hi
                for u, (lo, hi) in zip(units, bounds[group], strict=True)
            ):
                continue
            trial = try_group(group, units)
            if trial is not None and trial[0] < chosen_score:
                chosen_units, chosen_changes, chosen_score = units, trial[1], trial[0]
        if chosen_units is None:
            return False
        apply(group, chosen_units, chosen_changes)
        best = chosen_score
        return True

    widest = max(hi - lo for b in bounds for lo, hi in b)
    step = max(1, widest // 2)
    while step >= 1 and evaluations < cfg.max_evaluations:
        moved = True
        while moved and evaluations < cfg.max_evaluations:
            moved = False
            for group in range(len(groups)):
                for parameter in range(3):
                    span = bounds[group][parameter][1] - bounds[group][parameter][0]
                    if span < step:
                        continue
                    candidates = []
                    for sign in (-1, 1):
                        units = list(current[group])
                        units[parameter] += sign * step
                        candidates.append(tuple(units))
                    moved |= improve(group, candidates)
        step //= 2
    moved = True
    while moved and evaluations < cfg.max_evaluations:
        moved = False
        for group in range(len(groups)):
            base = current[group]
            candidates = [
                tuple(u + d for u, d in zip(base, delta, strict=True))
                for delta in product((-1, 0, 1), repeat=3)
                if any(delta)
            ]
            moved |= improve(group, candidates)

    new_sections = list(cascade)
    for group, members in enumerate(groups):
        for i in members:
            new_sections[i] = _section(authored[group].type, current[group])
    profile_errors = []
    measured_all, converged_all, within_ceilings = [], True, True
    for state, original, ceiling in zip(states, originals, ceilings, strict=True):
        realised = np.array(state.rows)
        if not stable(realised):
            measured, converged = float("inf"), False
        else:
            measured, converged = _validated_maximum(
                state.reference, realised, state.rate, cfg.band_hz, cfg
            )
        within_ceilings &= measured <= ceiling + cfg.numerical_tolerance_db
        measured_all.append(measured)
        converged_all &= converged
        profile_errors.append(
            ProfileError(
                state.rate,
                state.precision.name,
                original,
                measured,
                _guard(state.reference, realised, state.rate, cfg)
                if np.isfinite(measured)
                else float("inf"),
            )
        )
    worst = max(measured_all)
    changed = any(current[g] != start[g] for g in range(len(groups)))
    if abs(worst - cfg.margin_db) < cfg.numerical_tolerance_db or not converged_all:
        outcome = "unresolved"
    elif changed and within_ceilings and worst <= cfg.margin_db:
        outcome = "replacement"
    elif changed and within_ceilings and worst < baseline - cfg.numerical_tolerance_db:
        outcome = "improvement"
    else:
        outcome = "no_replacement"
    return result(
        outcome,
        tuple(profile_errors),
        candidate_error_db=worst,
        sections=tuple(new_sections) if outcome in PUBLISHED_OUTCOMES else None,
        evaluations=evaluations,
    )
