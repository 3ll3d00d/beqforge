"""Synthetic ground truth.

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

from beqanalyser import PeakingEQ
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

    event_colour_db: float = 12.0
    """Spread of the per-event spectral emphasis, in dB.

    Without it every event is white and its bins are statistically independent, so nothing
    co-varies beyond the common programme level and the coherence of §3.4 has nothing to
    measure. Real bass events differ in character — an explosion and a door slam do not share
    a spectrum — and that shared per-event shape is what coherence keys on.

    Applied as a pair of random peaking sections rather than a single tilt. A tilt is a
    see-saw about its pivot, which makes bins either side move in opposition and leaves a
    reference band straddling the pivot with nothing to correlate against; real events have
    *local* emphasis, so nearby bins co-vary more strongly than distant ones.
    """

    event_colour_sections: int = 2
    """Number of random peaking sections shaping each event."""

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
    nyquist = fs / 2.0
    for start, level in zip(starts, levels, strict=True):
        stop = min(n, start + decay_len)
        burst = rng.standard_normal(stop - start) * envelope[: stop - start]
        burst = signal.sosfilt(_colour(profile, rng, fs, nyquist), burst)
        out[start:stop] += burst * level / (np.std(burst) or 1.0)

    if profile.rumble_db is not None:
        rumble = signal.sosfilt(
            signal.butter(2, profile.rumble_hz, btype="low", fs=fs, output="sos"),
            rng.standard_normal(n),
        )
        rumble *= 10.0 ** (profile.rumble_db / 20.0) / (np.std(rumble) or 1.0)
        out += rumble

    peak = np.max(np.abs(out))
    return out / peak if peak else out


def _colour(
    profile: SyntheticProfile, rng: np.random.Generator, fs: float, nyquist: float
) -> np.ndarray:
    """Random peaking sections giving one event its spectral character."""
    rows: list[list[float]] = []
    for _ in range(profile.event_colour_sections):
        freq = float(np.exp(rng.uniform(np.log(8.0), np.log(0.6 * nyquist))))
        gain = float(rng.uniform(-0.5, 0.5) * profile.event_colour_db)
        rows.extend(PeakingEQ(fs, freq, 1.0, gain).get_sos())
    return np.array(rows)


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


@dataclass(frozen=True, slots=True)
class EvidenceCase:
    """Predeclared source/noise truth, kept out of the production pipeline."""

    name: str
    source: np.ndarray
    content: np.ndarray
    noise: np.ndarray
    fs: int
    injected: HighPass | None = None
    coverage: str = "complete_programme"

    def material(self):
        from beqanalyser.design.material import LFE_GAIN, Material

        samples = self.content + self.noise
        return Material(
            self.name, self.fs, LFE_GAIN * samples, {"LFE": samples}, self.coverage
        )


def evidence_cases(seed: int = 947, duration_s: float = 240) -> Iterator[EvidenceCase]:
    """Frozen R5 protocol: development seed 101, held-out seed 947; no threshold tuning.

    Natural colouring is intentionally observationally indistinguishable from filtering.
    The negative is defined by source provenance, not by a detector's preferred spectrum.
    """
    fs = 1000
    rng = np.random.default_rng(seed)
    n = int(duration_s * fs)
    scene = np.arange(n) // (4 * fs)
    levels = np.where(scene % 3 == 0, 0.0, np.where(scene % 3 == 1, 0.06, 0.3))
    source = rng.standard_normal(n) * levels
    noise = rng.standard_normal(n) * 1e-5
    hp = HighPass(Alignment.BUTTERWORTH, 4, 24.0)
    natural = apply_high_pass(source, hp, fs)
    coloured_noise = apply_high_pass(rng.standard_normal(n) * 0.01, hp, fs)
    # Source emphasis varies with level; applying one fixed filter cannot remove this.
    low = signal.sosfilt(signal.butter(2, 35, fs=fs, output="sos"), source)
    varying = source + np.where(scene % 3 == 1, 5.0, 0.0) * low
    steep = HighPass(Alignment.BUTTERWORTH, 12, 32.0)
    yield EvidenceCase("broadband", source, source, noise, fs)
    yield EvidenceCase("natural_bass_light", natural, natural, noise, fs)
    yield EvidenceCase(
        "stationary_coloured_noise", np.zeros(n), np.zeros(n), coloured_noise, fs
    )
    yield EvidenceCase("varying_source", varying, varying, noise, fs)
    yield EvidenceCase(
        "varying_filtered", varying, apply_high_pass(varying, hp, fs), noise, fs, hp
    )
    yield EvidenceCase(
        "steep_leakage", source, apply_high_pass(source, steep, fs), noise, fs, steep
    )
    end = n // 3
    yield EvidenceCase(
        "excerpt",
        varying[:end],
        apply_high_pass(varying, hp, fs)[:end],
        noise[:end],
        fs,
        hp,
        "excerpt",
    )


def score_evidence_case(case: EvidenceCase, report, params) -> dict:
    """Score the selected published device, never a detector or fit residual.

    False acceptance means *any* selected intervention on a constructed negative, even if
    the output carefully qualifies its claims. Recovery truth never enters selection.
    """
    from beqanalyser.design.diagnose import mean_spectrum
    from beqanalyser.design.filters import biquad_sos, magnitude_db, publication_filters

    selected = report.accepted
    negative = case.injected is None
    result = {
        "name": case.name,
        "negative": negative,
        "excerpt": case.coverage == "excerpt",
        "selected": None if selected is None else selected.label,
        "false_acceptance": bool(negative and selected is not None),
        "abstained": selected is None,
        "recovery_rms_db": None,
        "max_boost_noise_dominated_db": None,
        "evidence_score": None
        if selected is None
        else selected.correction_support_score,
        "candidate_failures": {c.label: c.verdict.failures for c in report.candidates},
        "notes": list(report.evidence_notes),
    }
    if selected is None:
        return result
    freqs = np.geomspace(5, 2 * (case.injected.corner_hz if case.injected else 24), 200)
    filters = publication_filters(selected.filters)
    # Device response includes actual coefficient quantisation, the same object judged by run.
    actual = magnitude_db(
        params.realisation.quantise(biquad_sos(filters, params.realisation.fs)),
        freqs,
        params.realisation.fs,
    )
    if case.injected is not None:
        _, transfer = signal.sosfreqz(
            high_pass_sos(case.injected, case.fs), worN=freqs, fs=case.fs
        )
        inverse = -20 * np.log10(np.maximum(np.abs(transfer), 1e-30))
        result["recovery_rms_db"] = float(np.sqrt(np.mean((actual - inverse) ** 2)))
    axis, content = mean_spectrum(case.content, case.fs)
    _, noise = mean_spectrum(case.noise, case.fs)
    noisy = np.interp(freqs, axis, noise - content) > 0
    result["max_boost_noise_dominated_db"] = (
        float(np.max(actual[noisy])) if noisy.any() else 0.0
    )
    return result
