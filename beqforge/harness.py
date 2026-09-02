"""Synthetic ground truth — AUTOMATED_DESIGN.md §6.1 and build step 1.

Two constructions, because the catalogue supplies 15,208 positives and zero negatives:

* **Differential injection** — apply a known high-pass to a source and ask whether the
  estimator recovers it. The source's own unknown state cancels, so this works on any
  material with no claim about its provenance.
* **Constructed negatives** — synthesised material with content to DC by construction. The
  only source of an absolute false-positive rate, since nothing was ever removed.

`synthesise` deliberately produces *broadband* events rather than tones. Coherence weighting
(§3.4) keys on simultaneous energy across frequency, so a negative built from isolated low
tones would be abstained on rather than passed, which would measure the wrong thing.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
from scipy import signal

from beqanalyser.design import Alignment, HighPass
from beqanalyser.design.filters import high_pass_sos

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyntheticProfile:
    """A synthetic title, parameterised by the regimes §3.2 and §4.1 care about.

    `floor_db` and `rumble_db` are relative to the peak event level, so a profile with a high
    floor and sparse events reproduces the bass-light case where relative scene selection
    manufactures false positives.
    """

    duration_s: float = 600.0
    """Runtime. Long enough that percentile envelopes are stable."""

    event_rate_hz: float = 0.05
    """Broadband events per second — 0.05 is roughly one every 20 seconds."""

    event_decay_s: float = 0.4
    """Exponential decay time of an event."""

    event_level_spread_db: float = 18.0
    """Range of event peak levels, so some scenes clear an absolute margin and some do not."""

    floor_db: float = -60.0
    """Stationary broadband noise floor, relative to the loudest event."""

    rumble_db: float | None = None
    """Stationary low-frequency rumble level, or None for no rumble."""

    rumble_hz: float = 12.0
    """Corner of the lowpass shaping the rumble."""


@dataclass(frozen=True, slots=True)
class HarnessCase:
    """One scored case: a signal, and the truth about what was done to it."""

    name: str
    samples: np.ndarray
    fs: float
    injected: HighPass | None
    """The high-pass applied to the source, or None for a constructed negative."""

    @property
    def is_negative(self) -> bool:
        return self.injected is None


def synthesise(profile: SyntheticProfile, fs: float, seed: int = 0) -> np.ndarray:
    """A signal with content to DC by construction, at `fs`.

    Broadband transients over a stationary floor, optionally with rumble. Seeded, so a case
    can be reproduced from its profile and seed alone.
    """
    rng = np.random.default_rng(seed)
    n = int(round(profile.duration_s * fs))
    out = rng.standard_normal(n) * 10.0 ** (profile.floor_db / 20.0)

    count = max(1, int(round(profile.duration_s * profile.event_rate_hz)))
    starts = rng.integers(0, n, size=count)
    levels = 10.0 ** (-rng.uniform(0.0, profile.event_level_spread_db, count) / 20.0)
    decay_len = int(round(profile.event_decay_s * 6.0 * fs))
    envelope = np.exp(-np.arange(decay_len) / (profile.event_decay_s * fs))
    for start, level in zip(starts, levels, strict=True):
        stop = min(n, start + decay_len)
        burst = rng.standard_normal(stop - start) * envelope[: stop - start]
        out[start:stop] += burst * level

    if profile.rumble_db is not None:
        rumble = signal.sosfilt(
            signal.butter(2, profile.rumble_hz, btype="low", fs=fs, output="sos"),
            rng.standard_normal(n),
        )
        rumble *= 10.0 ** (profile.rumble_db / 20.0) / (np.std(rumble) or 1.0)
        out += rumble

    peak = np.max(np.abs(out))
    return out / peak if peak else out


def apply_high_pass(samples: np.ndarray, hp: HighPass, fs: float) -> np.ndarray:
    """Inject a known rolloff. The ground truth for differential injection."""
    return signal.sosfilt(high_pass_sos(hp, fs), samples)


def injection_sweep(
    source: np.ndarray,
    fs: float,
    corners_hz: tuple[float, ...],
    alignments: tuple[Alignment, ...] = (
        Alignment.BUTTERWORTH,
        Alignment.LINKWITZ_RILEY,
    ),
    orders: tuple[int, ...] = (2, 4, 8),
    name: str = "source",
) -> Iterator[HarnessCase]:
    """Every (alignment, order, corner) applied to one source, plus the source itself.

    The untouched source is yielded first as a negative. It is not a claim that the source is
    unfiltered — it is the baseline the injected cases are read against, which is what makes
    the test differential.
    """
    yield HarnessCase(f"{name}/baseline", source, fs, None)
    for alignment in alignments:
        for order in orders:
            if alignment.is_linkwitz_riley and order % 2:
                continue
            for corner in corners_hz:
                hp = HighPass(alignment, order, corner)
                yield HarnessCase(
                    f"{name}/{hp}", apply_high_pass(source, hp, fs), fs, hp
                )
