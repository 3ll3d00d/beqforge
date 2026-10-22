"""E10: the content-goal validation protocol's synthetic cases and scorer (TODO row 3).

`plans/E10-validation-protocol.md` is the predeclaration; this is its instrument for the
synthetic families. Kept out of the production pipeline, like `harness`, whose corpus it leaves
untouched: the corpus and the frozen protocol keep running as regression checks.

Each case stores its source (the programme before the recipe shaped it), the programme as
recorded, the programme as observed (after whatever the recipe did to it) and the additive
noise, per channel. The scorer reads truth from those arrays alone: where the observed programme
stands above the noise, how far the recipe moved it from its source, and where only noise is
left. So whether a case needs a correction is computed per goal, never labelled by hand, and
every score is taken on the published device response.
"""

import math
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
from scipy import signal
from scipy.stats import beta

from beqforge import Alignment, BiquadSpec, HighPass
from beqforge.harness import SyntheticProfile, apply_high_pass, synthesise

PROTOCOL_VERSION = "e10-v3"
"""v1 read the goal deficit from the observed spectrum alone; v2 pivoted a tilted goal at the
reference's bottom, not where the deficit begins; see `truth`."""

GOALS: dict[str, tuple[float, float]] = {
    "flat": (0.0, 1.5),
    "gentle": (-1.5, 1.5),
    "tight": (0.0, 0.75),
}
"""Goal name: (`target_tilt_db_per_octave`, `goal_tolerance_db`), predeclared."""

DEVELOPMENT_SEEDS = range(1, 1000)
HELD_OUT_SEEDS = range(100001, 101000)
HELD_OUT_PER_FAMILY = 36
"""Seeds a held-out run takes from the start of its block: 0 of 36 bounds a family's rate below
9.7%, and the pooled negatives reach the 72 a 5% bound needs (the protocol's sample sizes)."""

FAMILIES = (
    "broadband",
    "sparse_dialogue",
    "stationary_noise",
    "coloured_floor",
    "nonstationary_floor",
    "correlated_noise",
    "finite_stopband",
    "partial_channels",
    "cancellation",
    "natural_droop",
    "continuous_bass",
    "filtered",
)

FS = 1000
DURATION_S = 240.0
REFERENCE_HZ = (80.0, 160.0)
"""Where every recipe leaves the programme alone: the plateau the goal is measured from."""

PIVOT_DB = 0.5
"""How far under the plateau the programme must sit to be part of the deficit a tilted goal
pivots on: `filters.correction_band_hz`'s threshold for a target's active span."""

FLOOR_HZ = 5.0
"""The lowest frequency scored: the pipeline's verification floor."""

NOISE_LIFT_DB = 3.0
MIN_SPAN_OCTAVES = 1.0 / 3.0
SMOOTHING_OCTAVES = 1.0 / 6.0


@dataclass(frozen=True, slots=True)
class E10Case:
    """One synthetic case: what the programme was, what was observed, and the noise."""

    name: str
    family: str
    seed: int
    source: dict[str, np.ndarray]
    """The programme before the recipe shaped it: what a correction would restore. Differs from
    `recorded` where the shaping is part of the recording (a natural droop, a cancellation, a
    programme recorded through a filter)."""

    recorded: dict[str, np.ndarray]
    """The programme as recorded, per channel, without noise: the truth a recipe started from."""

    observed: dict[str, np.ndarray]
    """The programme after the recipe's change (identical to `recorded` when there is none)."""

    noise: dict[str, np.ndarray]
    change: str = "none"
    """What the recipe did, for the record: a filter, a stopband, the channels it touched."""

    fs: int = FS
    coverage: str = "complete_programme"

    def material(self):
        from beqforge.material import Material

        channels = {
            name: self.observed[name] + self.noise[name] for name in self.observed
        }
        return Material(self.name, self.fs, _mix(channels), channels, self.coverage)


def _mix(channels: dict[str, np.ndarray]) -> np.ndarray:
    from beqforge.material import LFE_GAIN, MAIN_GAIN

    return sum(
        (LFE_GAIN if name == "LFE" else MAIN_GAIN) * samples
        for name, samples in channels.items()
    )


def _high_pass(rng: np.random.Generator, orders: tuple[int, ...]) -> HighPass:
    alignment = (
        Alignment.LINKWITZ_RILEY if rng.random() < 0.5 else Alignment.BUTTERWORTH
    )
    allowed = [o for o in orders if alignment == Alignment.BUTTERWORTH or o % 2 == 0]
    order = int(rng.choice(allowed))
    corner = float(np.exp(rng.uniform(np.log(15.0), np.log(40.0))))
    return HighPass(alignment, order, corner)


def _shaped_noise(
    rng: np.random.Generator, n: int, colour: str, fs: int = FS
) -> np.ndarray:
    """Unit-RMS noise with a pink, brown or codec-like (banded, stepped) spectrum."""
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1.0 / fs)
    freqs[0] = freqs[1]
    if colour == "pink":
        spectrum /= np.sqrt(freqs)
    elif colour == "brown":
        spectrum /= freqs
    else:
        # a lossy encoder's quantisation noise: a level per 4 Hz band, steps of up to 6 dB
        bands = (freqs // 4.0).astype(int)
        steps = rng.uniform(-6.0, 6.0, bands.max() + 1)
        spectrum *= 10.0 ** (steps[bands] / 20.0)
    noise = np.fft.irfft(spectrum, n)
    return noise / (np.std(noise) or 1.0)


def e10_case(family: str, seed: int, duration_s: float = DURATION_S) -> E10Case:
    """One reproducible case: its family, and every parameter drawn from its seed."""
    if family not in FAMILIES:
        raise ValueError(f"unknown E10 family {family!r}; have {FAMILIES}")
    rng = np.random.default_rng((seed, FAMILIES.index(family), 10))
    n = int(duration_s * FS)

    def programme(**overrides) -> np.ndarray:
        drawn = {
            "event_rate_hz": float(rng.uniform(0.04, 0.12)),
            "event_level_spread_db": float(rng.uniform(12.0, 24.0)),
            "floor_db": float(rng.uniform(-70.0, -50.0)),
        }
        profile = SyntheticProfile(duration_s=duration_s, **{**drawn, **overrides})
        return synthesise(profile, FS, int(rng.integers(1 << 31))) * 0.3

    def white(level: float = 1e-5) -> dict[str, np.ndarray]:
        return {name: rng.standard_normal(n) * level for name in ("L", "LFE")}

    def below(samples: np.ndarray, db_down: float) -> float:
        return float(np.std(samples)) * 10.0 ** (-db_down / 20.0)

    recorded = {"L": programme(), "LFE": programme()}
    source = recorded
    observed = dict(recorded)
    noise = white()
    change = "none"

    if family == "sparse_dialogue":
        recorded = {
            name: programme(
                event_rate_hz=float(rng.uniform(0.003, 0.01)),
                floor_db=float(rng.uniform(-30.0, -15.0)),
                event_level_spread_db=3.0,
            )
            for name in ("L", "LFE")
        }
        source = recorded
        observed = dict(recorded)
    elif family == "stationary_noise":
        recorded = {name: np.zeros(n) for name in ("L", "LFE")}
        source = recorded
        observed = dict(recorded)
        colour = str(rng.choice(("pink", "brown", "codec")))
        noise = {name: _shaped_noise(rng, n, colour) * 0.01 for name in ("L", "LFE")}
        change = f"{colour} noise only"
    elif family in ("coloured_floor", "nonstationary_floor"):
        hp = _high_pass(rng, (8, 12, 16))
        observed = {name: apply_high_pass(s, hp, FS) for name, s in recorded.items()}
        colour = str(rng.choice(("pink", "brown", "codec")))
        down = float(rng.uniform(30.0, 60.0))
        noise = {}
        for name, samples in recorded.items():
            floor = _shaped_noise(rng, n, colour) * below(samples, down)
            if family == "nonstationary_floor":
                # pumping: the floor rises with the programme, as a compressor's would
                level = np.convolve(np.abs(samples), np.ones(FS) / FS, mode="same")
                floor *= 0.25 + level / (np.mean(level) or 1.0)
            noise[name] = floor
        change = f"{hp}; {colour} floor {down:.0f} dB down"
    elif family == "correlated_noise":
        hp = _high_pass(rng, (8, 12))
        recorded = {name: apply_high_pass(s, hp, FS) for name, s in recorded.items()}
        observed = dict(recorded)
        bed = _shaped_noise(rng, n, "pink") * below(recorded["L"], 40.0)
        noise = {name: bed.copy() for name in ("L", "LFE")}
        change = f"recorded through {hp}; one pink bed in every channel"
    elif family == "finite_stopband":
        hp = _high_pass(rng, (4, 6, 8))
        stopband = float(rng.choice((-40.0, -60.0)))
        leak = 10.0 ** (stopband / 20.0)
        observed = {
            name: apply_high_pass(s, hp, FS) + leak * s for name, s in recorded.items()
        }
        change = f"{hp}, stopband {stopband:.0f} dB"
    elif family == "partial_channels":
        hp = _high_pass(rng, (2, 3, 4))
        touched = str(rng.choice(("L", "LFE")))
        observed = {
            name: apply_high_pass(s, hp, FS) if name == touched else s
            for name, s in recorded.items()
        }
        change = f"{hp} on {touched} only"
    elif family == "cancellation":
        depth = float(rng.uniform(0.3, 0.8))
        low = signal.sosfilt(
            signal.butter(4, 60.0, fs=FS, output="sos"), recorded["LFE"]
        )
        from beqforge.material import LFE_GAIN, MAIN_GAIN

        # the mains carry the LFE's low band inverted, cancelling `depth` of it in the mix
        recorded = {
            "L": recorded["L"] - depth * (LFE_GAIN / MAIN_GAIN) * low,
            "LFE": recorded["LFE"],
        }
        observed = dict(recorded)
        change = f"mains cancel {depth:.0%} of the LFE below 60 Hz"
    elif family == "natural_droop":
        hp = _high_pass(rng, (2, 3, 4))
        recorded = {name: apply_high_pass(s, hp, FS) for name, s in recorded.items()}
        observed = dict(recorded)
        change = f"recorded through {hp}"
    elif family == "continuous_bass":
        recorded = {
            name: programme(
                event_rate_hz=float(rng.uniform(1.0, 2.0)),
                event_level_spread_db=6.0,
                rumble_db=-20.0,
                rumble_hz=40.0,
            )
            for name in ("L", "LFE")
        }
        source = recorded
        observed = dict(recorded)
        if seed % 2:
            hp = _high_pass(rng, (2, 3, 4))
            observed = {
                name: apply_high_pass(s, hp, FS) for name, s in recorded.items()
            }
            change = f"{hp}"
    elif family == "filtered":
        hp = _high_pass(rng, (2, 3, 4))
        observed = {name: apply_high_pass(s, hp, FS) for name, s in recorded.items()}
        change = f"{hp}"

    return E10Case(
        f"{family}/{seed}", family, seed, source, recorded, observed, noise, change
    )


def cases(
    families: tuple[str, ...],
    seeds: Iterator[int] | range,
    duration_s: float = DURATION_S,
) -> Iterator[E10Case]:
    for family in families:
        for seed in seeds:
            yield e10_case(family, seed, duration_s)


# ---- truth and scoring -------------------------------------------------------------------


def _smoothed(freqs: np.ndarray, values_db: np.ndarray) -> np.ndarray:
    """A sixth-octave running mean in power, so a bin's verdict is not one Welch estimate's."""
    power = 10.0 ** (values_db / 10.0)
    out = np.empty_like(values_db)
    half = SMOOTHING_OCTAVES / 2.0
    for i, f in enumerate(freqs):
        window = (freqs >= f * 2.0**-half) & (freqs <= f * 2.0**half)
        out[i] = 10.0 * np.log10(np.mean(power[window]) + 1e-300)
    return out


def _span_octaves(freqs: np.ndarray, mask: np.ndarray) -> float:
    """The widest contiguous run of `mask`, in octaves."""
    widest, start = 0.0, None
    for i, on in enumerate(mask):
        if on and start is None:
            start = i
        if start is not None and (not on or i == len(mask) - 1):
            stop = i if on else i - 1
            widest = max(widest, math.log2(freqs[stop] / freqs[start]))
            start = None
    return widest


@dataclass(frozen=True, slots=True)
class Truth:
    """What a case's arrays say, at one goal, on a common log-frequency axis."""

    freqs: np.ndarray
    programme_db: np.ndarray
    """The observed programme as the recipe left it relative to its source, placed at the
    observed plateau's level: the change alone, without one realisation's chance shape. Where
    there is no plateau, the observed spectrum as measured."""

    noise_db: np.ndarray
    goal_db: np.ndarray
    tolerance_db: float
    truth_band: np.ndarray
    """Bins from the reference down, contiguously, where the programme stands 3 dB over the noise."""

    noise_only: np.ndarray
    """Bins below the reference where the noise is louder than the programme."""

    needs_correction: bool
    """Somewhere in the truth band the programme sits more than the tolerance under the goal,
    over a third of an octave or more."""

    observed_db: np.ndarray | None = None
    """The observed programme as measured, chance shape and all: what the designer sees."""

    pivot_hz: float = REFERENCE_HZ[0]
    """Where the goal's tilt begins: the top of the deficit (`deficit_top_hz`)."""

    extras: dict = field(default_factory=dict)


def truth(case: E10Case, goal: str) -> Truth:
    """Read the case's arrays at `goal`: computed, never labelled (the protocol's goals).

    The deficit is the observed programme's spectrum less its source's, from the same
    realisation, normalised to zero on the reference. v1 read it from the observed spectrum
    alone, so a sixth-octave estimate's scatter (2.5-3.5 dB at the bottom of an unchanged
    broadband case) passed for a deficit or an overshoot (plans/E10-validation-protocol.md,
    "First development run"). The truth band and the noise-only bins still come from the
    observed programme against the noise: audibility is about levels, not about the change."""
    from beqforge.diagnose import mean_spectrum
    from beqforge.verify import house_curve_db

    tilt, tolerance = GOALS[goal]
    freqs = np.geomspace(FLOOR_HZ, REFERENCE_HZ[1], 160)
    axis, programme = mean_spectrum(_mix(case.observed), case.fs)
    _, noise = mean_spectrum(_mix(case.noise), case.fs)
    programme = np.interp(freqs, axis, _smoothed(axis, programme))
    noise = np.interp(freqs, axis, _smoothed(axis, noise))
    reference = (freqs >= REFERENCE_HZ[0]) & (freqs <= REFERENCE_HZ[1])
    audible = programme - noise > 3.0
    below = freqs < REFERENCE_HZ[0]
    if not audible[reference].all():
        # no programme on the plateau: nothing to measure a goal from, nothing to restore
        empty = np.zeros_like(freqs, dtype=bool)
        return Truth(
            freqs,
            programme,
            noise,
            np.full_like(freqs, np.nan),
            tolerance,
            empty,
            below & ~audible,
            False,
        )
    level = float(np.median(programme[reference]))
    band = np.zeros_like(freqs, dtype=bool)
    for i in range(int(np.flatnonzero(reference)[0]) - 1, -1, -1):
        if not audible[i]:
            break
        band[i] = True
    noise_only = below & (noise > programme)
    observed = programme
    _, source = mean_spectrum(_mix(case.source), case.fs)
    deficit = programme - np.interp(freqs, axis, _smoothed(axis, source))
    programme = level + deficit - float(np.median(deficit[reference]))
    pivot = deficit_top_hz(freqs, programme - level, band)
    goal_db = level + house_curve_db(freqs, pivot, tilt)
    short = band & (programme < goal_db - tolerance)
    return Truth(
        freqs,
        programme,
        noise,
        goal_db,
        tolerance,
        band,
        noise_only,
        _span_octaves(freqs, short) > MIN_SPAN_OCTAVES,
        observed,
        pivot,
    )


def deficit_top_hz(freqs: np.ndarray, change_db: np.ndarray, band: np.ndarray) -> float:
    """Where the content's deficit ends, reading up from the bottom of the truth band.

    A tilted goal is about the recovery, not the track: it tilts below where the deficit
    begins and leaves the programme above it as it is, as the designer's goal does (it pivots
    at its judged band's top, `pipeline._judged_top_hz`). v2 pivoted at the reference's bottom,
    so a title missing bass below 40 Hz was held 1.5 dB under its own level there at the
    gentle goal, and the designer's answer read as overshoot. The pivot is read from the
    case's change, never from the design. With no deficit at the bottom it is the band's
    bottom: no tilt over the band, so nothing to restore."""
    inside = np.flatnonzero(band)
    if not inside.size:
        return REFERENCE_HZ[0]
    short = change_db[inside] < -PIVOT_DB
    if not short[0]:
        return float(freqs[inside[0]])
    settled = np.flatnonzero(~short)
    return float(freqs[inside[settled[0]]]) if settled.size else REFERENCE_HZ[0]


def published_response_db(filters, realisation, freqs: np.ndarray) -> np.ndarray:
    """What the device plays: published rounding, then coefficient quantisation."""
    from beqforge.filters import biquad_sos, magnitude_db, publication_filters

    sos = realisation.quantise(biquad_sos(publication_filters(filters), realisation.fs))
    return magnitude_db(sos, freqs, realisation.fs)


def score(case: E10Case, goal: str, report, params) -> dict:
    """The protocol's failure classes for one case at one goal, on the published response."""
    selected = report.accepted
    if selected is None:
        return score_selection(
            case, goal, None, None, None, params, list(report.evidence_notes)[:3]
        )
    return score_selection(
        case,
        goal,
        selected.label,
        list(selected.filters),
        selected.verdict.drift_db,
        params,
    )


def rescore(row: dict, params, duration_s: float = DURATION_S) -> dict:
    """A stored row scored again by this instrument, from the filters it kept: no new design."""
    filters = (
        None if row["filters"] is None else [BiquadSpec(*f) for f in row["filters"]]
    )
    return score_selection(
        e10_case(row["family"], row["seed"], duration_s),
        row["goal"],
        row["selected"],
        filters,
        row["drift_db"],
        params,
        row["decline_notes"],
    ) | {"seconds": row.get("seconds")}


def score_selection(
    case: E10Case,
    goal: str,
    label: str | None,
    filters: list[BiquadSpec] | None,
    drift: float | None,
    params,
    decline_notes: list[str] | None = None,
) -> dict:
    """`score`'s rows from what was selected (None for an abstention) rather than a report."""
    known = truth(case, goal)
    row: dict = {
        "name": case.name,
        "family": case.family,
        "seed": case.seed,
        "goal": goal,
        "change": case.change,
        "needs_correction": known.needs_correction,
        "selected": label,
        "sections": None if filters is None else len(filters),
        "decline_notes": [] if label is not None else list(decline_notes or []),
    }
    response = (
        np.zeros_like(known.freqs)
        if filters is None
        else published_response_db(filters, params.realisation, known.freqs)
    )
    lifted = response[known.noise_only]
    row["noise_exposed"] = bool(known.noise_only.any())
    row["noise_lift_db"] = round(float(lifted.max()), 2) if lifted.size else 0.0
    row["noise_lift"] = bool(label is not None and row["noise_lift_db"] > NOISE_LIFT_DB)
    row["unnecessary"] = bool(label is not None and not known.needs_correction)
    corrected = known.programme_db + response
    band = known.truth_band
    if band.any():
        # lifted past the goal (or past where the programme already stood over it, as at a
        # cancellation's bump) in both readings: what the recipe left, and what is actually
        # there. Either alone mistakes the source's chance shape for an overshoot: filling a
        # chance dip in the programme rises over the first, restoring a chance peak the recipe
        # cut rises over the second
        tolerance = known.tolerance_db
        left = corrected > np.maximum(known.goal_db, known.programme_db) + tolerance
        seen = known.observed_db + response
        there = seen > np.maximum(known.goal_db, known.observed_db) + tolerance
        over = band & left & there
        gap = np.maximum(known.goal_db - corrected, 0.0)[band]
        short = band & (corrected < known.goal_db - known.tolerance_db)
        row["overshoot"] = bool(label is not None and over.any())
        row["shortfall_median_db"] = round(float(np.median(gap)), 2)
        row["shortfall_worst_db"] = round(float(gap.max()), 2)
        row["missed"] = bool(
            known.needs_correction
            and (label is None or _span_octaves(known.freqs, short) > MIN_SPAN_OCTAVES)
        )
        row["truth_band_hz"] = [
            round(float(known.freqs[band].min()), 1),
            round(float(known.freqs[band].max()), 1),
        ]
    else:
        row.update(
            overshoot=False,
            shortfall_median_db=None,
            shortfall_worst_db=None,
            missed=False,
            truth_band_hz=None,
        )
    # enough to rescore the row under a revised instrument without designing it again
    row["filters"] = (
        None
        if filters is None
        else [[f.type, f.freq_hz, f.gain_db, f.q] for f in filters]
    )
    row["drift_db"] = drift
    # a finite drift is already inside every curve above, which is the published, quantised
    # response; `max_drift_db` is the fitter's preference, not a gate (`AcceptParams`). What
    # no curve can show is a cascade the device cannot realise at all
    row["device_failure"] = bool(
        label is not None and drift is not None and math.isinf(drift)
    )
    return row


CLASSES = ("noise_lift", "unnecessary", "overshoot", "missed", "device_failure")
SAFETY = ("noise_lift", "unnecessary", "overshoot")


def clopper_pearson(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Exact two-sided binomial interval, as `tools/negative_corpus.py` reports."""
    if n == 0:
        return 0.0, 1.0
    alpha = 1.0 - confidence
    low = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    high = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return low, high


def summarise(rows: list[dict]) -> dict:
    """Each class's count, rate and interval, pooled and per family, at each goal.

    A safety class is counted over the cases exposed to it: noise lift over cases with
    noise-only bins, unnecessary intervention over cases that need no correction, overshoot
    over every case; missed recovery over the cases that need one.
    """

    def tally(subset: list[dict]) -> dict:
        exposed = {
            "noise_lift": [r for r in subset if r["noise_exposed"]],
            "unnecessary": [r for r in subset if not r["needs_correction"]],
            "overshoot": subset,
            "missed": [r for r in subset if r["needs_correction"]],
            "device_failure": [r for r in subset if r["selected"] is not None],
        }
        out = {}
        for name in CLASSES:
            k = sum(r[name] for r in exposed[name])
            n = len(exposed[name])
            low, high = clopper_pearson(k, n)
            out[name] = {
                "k": k,
                "n": n,
                "upper": round(high, 3),
                "lower": round(low, 3),
            }
        gaps = [
            r["shortfall_median_db"]
            for r in subset
            if r["needs_correction"] and r["shortfall_median_db"] is not None
        ]
        out["shortfall_median_db"] = round(float(np.median(gaps)), 2) if gaps else None
        return out

    summary: dict = {}
    for goal in sorted({r["goal"] for r in rows}):
        at_goal = [r for r in rows if r["goal"] == goal]
        summary[goal] = {
            "pooled": tally(at_goal),
            "families": {
                family: tally([r for r in at_goal if r["family"] == family])
                for family in sorted({r["family"] for r in at_goal})
            },
        }
    return summary
