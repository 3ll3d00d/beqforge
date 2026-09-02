"""Reducing a signal to the envelopes identification fits — AUTOMATED_DESIGN.md §3.2-§3.4.

The spectrogram a human reads by eye, reduced to three curves against frequency:

* **peak** — a high percentile over frames that clear an absolute margin above the measured
  floor. The question is what is the *most* energy that ever appears at this frequency, so a
  percentile rather than a mean; a mean is dominated by quiet passages and by whatever the
  title happens to contain.
* **quiet** — the same statistic over frames near the floor. Rumble plus noise, measured on
  the title itself, per codec, assuming nothing.
* **coherence** — per bin, how strongly its energy over time tracks a fixed reference band.
  Real bass events have simultaneous energy across frequency; noise does not. This replaces
  any absolute noise-floor threshold: where coherence collapses the fit weight goes to zero on
  its own.

Scene selection is absolute, never relative (§3.2). Taking the top N% of frames would, on a
bass-light title, select its loudest *quiet* frames and read the floor's own shape as a
rolloff — manufacturing false positives on exactly the material where they are most likely.
Selecting on an absolute margin instead yields few or no qualifying frames there, which is the
correct answer, so the criterion is part of the abstain logic rather than a step before it.
"""

import logging
from dataclasses import dataclass

import numpy as np
from scipy import signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractionParams:
    """Knobs for the reduction. Defaults are settled on the harness, not chosen by taste."""

    frame_samples: int = 1024
    """STFT window. At 1 kHz this is ~1 Hz bins over ~1 s, which resolves a knee across
    10-40 Hz while staying close to the duration of the events being measured."""

    overlap: float = 0.5
    """Fraction of a frame shared with the next."""

    band_hz: tuple[float, float] = (4.0, 470.0)
    """Usable band. The top is where the decimation anti-alias filter takes hold, measured."""

    scene_band_hz: tuple[float, float] = (10.0, 60.0)
    """Band whose energy decides whether a frame is a heavy scene.

    It must be dominated by the same sources as the band being measured. Measured on a real
    7.1 title, 40-200 Hz is 84% front L/C/R — dialogue and score — and 1.6% LFE, while 10-30 Hz
    is 50% LFE. Selecting on 40-200 Hz therefore picks the frames where the *dialogue* is loud
    and then measures sub-bass in them, which is not the same question.

    Rumble is not a reason to move this band up. Rumble is stationary, so it lifts every
    frame's energy equally and does not change which frames rank highest; what it changes is
    the floor, and therefore how many frames clear a fixed margin above it."""

    floor_percentile: float = 10.0
    """Frame-energy percentile taken as the title's own floor."""

    scene_margin_db: float = 45.0
    """How far above the floor a frame must sit to count as content. Absolute, per §3.2.

    Large, because sub-bass in a film has enormous dynamic range — 61 dB from p10 to p99 on the
    first real title — and the genuine bass events are the top 1-3% of frames. At +12 dB, 62%
    of frames qualified and the feature being looked for was diluted out of existence: a knee
    at 20 Hz measured +10.9 dB above 40 Hz over the top 1% of frames and -2.5 dB over that 62%.

    The dilution is worst on exactly the material §2.3 says matters most. §3.2 warns that
    *relative* selection manufactures false positives on a bass-light title; an absolute margin
    over the wrong band manufactures the mirror image, a false negative, and on a bass-light
    title the ratio of ordinary frames to genuine bass frames is highest of all.

    The value is an unresolved prior (§10). What can be said from measurement is that the
    recovered shape is stable from roughly +45 to +55 dB and degrades below +40."""

    quiet_margin_db: float = 3.0
    """How close to the floor a frame must sit to count as quiet."""

    envelope_percentile: float = 95.0
    """Percentile taken across qualifying frames, for both envelopes."""

    reference_band_hz: tuple[float, float] = (60.0, 120.0)
    """Fixed reference band for coherence (§3.4).

    Measured on real material, partial coherence against a low-frequency bin decays
    monotonically with separation: at 25 Hz it is 0.37 against 60-120 Hz, 0.16 against
    100-200, and ~0 against 235-470. An earlier default took the top octave of the usable
    band, reasoning that it was maximally far from any knee and so free of any prior about
    where corners live. That reasoning was wrong in effect: at that separation there is no
    coherence left to measure. See §10 — the lower edge remains an unresolved prior."""


@dataclass(frozen=True, slots=True)
class Envelopes:
    """What identification fits. All arrays share `freqs`."""

    freqs: np.ndarray
    peak_db: np.ndarray
    quiet_db: np.ndarray
    coherence: np.ndarray
    reference_band_hz: tuple[float, float]
    loud_frames: int
    quiet_frames: int
    total_frames: int

    @property
    def margin_db(self) -> np.ndarray:
        """Content-to-noise margin per bin — how far the content sits above the floor."""
        return self.peak_db - self.quiet_db

    @property
    def measurable(self) -> np.ndarray:
        """Bins where the peak envelope actually stands above the quiet one.

        Where it does not, there is no content to measure — only floor — and any number
        derived from the difference is noise. Fitting must weight these to zero rather than
        treat a large negative as a deep rolloff.
        """
        return (
            np.isfinite(self.peak_db)
            & np.isfinite(self.quiet_db)
            & (self.peak_db > self.quiet_db)
        )

    @property
    def content_db(self) -> np.ndarray:
        """Peak envelope with the quiet envelope removed in power.

        Rumble is present in both, so differencing cancels it. `-inf` where the two meet,
        which is honest: the alternative is a plausible-looking large negative that reads as a
        rolloff and is nothing of the kind. Check `measurable` before using this.
        """
        difference = 10.0 ** (self.peak_db / 10.0) - 10.0 ** (self.quiet_db / 10.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(
                self.measurable, 10.0 * np.log10(np.abs(difference)), -np.inf
            )

    def __str__(self) -> str:
        return (
            f"{self.loud_frames}/{self.total_frames} loud, "
            f"{self.quiet_frames} quiet, reference "
            f"{self.reference_band_hz[0]:.0f}-{self.reference_band_hz[1]:.0f} Hz, "
            f"median margin {np.median(self.margin_db):.1f} dB"
        )


def extract(
    samples: np.ndarray, fs: float, params: ExtractionParams | None = None
) -> Envelopes:
    """Reduce a signal to the envelopes of §3.3 and the coherence weighting of §3.4."""
    params = params or ExtractionParams()
    freqs, power = _spectrogram(samples, fs, params)
    in_scene_band = (freqs >= params.scene_band_hz[0]) & (
        freqs <= params.scene_band_hz[1]
    )
    band_energy_db = 10.0 * np.log10(power[in_scene_band].sum(axis=0) + 1e-300)

    floor_db = float(np.percentile(band_energy_db, params.floor_percentile))
    loud = band_energy_db >= floor_db + params.scene_margin_db
    quiet = band_energy_db <= floor_db + params.quiet_margin_db
    logger.debug(
        f"floor {floor_db:.1f} dB, {loud.sum()} loud and {quiet.sum()} quiet "
        f"of {len(band_energy_db)} frames"
    )

    peak_db = _envelope_db(power, loud, params.envelope_percentile)
    quiet_db = _envelope_db(power, quiet, params.envelope_percentile)
    reference = params.reference_band_hz
    coherence = _coherence(freqs, power, reference)

    envelopes = Envelopes(
        freqs=freqs,
        peak_db=peak_db,
        quiet_db=quiet_db,
        coherence=coherence,
        reference_band_hz=reference,
        loud_frames=int(loud.sum()),
        quiet_frames=int(quiet.sum()),
        total_frames=len(band_energy_db),
    )
    if not envelopes.loud_frames:
        logger.warning(
            f"No frame cleared {params.scene_margin_db:.0f} dB above the "
            f"{params.scene_band_hz[0]:.0f}-{params.scene_band_hz[1]:.0f} Hz floor: "
            "either the title has no heavy scenes or something stationary is filling that "
            "band. Either way there is nothing to identify — abstain."
        )
    logger.info(f"Extracted {envelopes}")
    return envelopes


def _spectrogram(
    samples: np.ndarray, fs: float, params: ExtractionParams
) -> tuple[np.ndarray, np.ndarray]:
    freqs, _, spectra = signal.stft(
        samples,
        fs=fs,
        nperseg=params.frame_samples,
        noverlap=int(params.frame_samples * params.overlap),
    )
    keep = (freqs >= params.band_hz[0]) & (freqs <= params.band_hz[1])
    return freqs[keep], (np.abs(spectra[keep]) ** 2)


def _envelope_db(
    power: np.ndarray, frames: np.ndarray, percentile: float
) -> np.ndarray:
    if not frames.any():
        return np.full(power.shape[0], -np.inf)
    return 10.0 * np.log10(np.percentile(power[:, frames], percentile, axis=1) + 1e-300)


def _coherence(
    freqs: np.ndarray, power: np.ndarray, reference_band_hz: tuple[float, float]
) -> np.ndarray:
    """Per-bin partial correlation of level against the reference band, holding the overall
    programme level fixed.

    The partial is what makes this a measurement rather than a tautology. Raw correlation
    scores 0.5-0.9 at *every* frequency on real material, because every bin rises and falls
    with the programme — it measures loud scenes against quiet ones, not whether a bin carries
    event-related content. Regressing out the total level leaves only what co-varies with the
    reference band beyond that common mode.

    Correlated in dB rather than in power so that a single loud event cannot dominate the
    statistic — the question is whether a bin rises and falls *with* the content, not whether
    it happens to share one big transient.
    """
    bins_db = 10.0 * np.log10(power + 1e-300)
    total_db = 10.0 * np.log10(power.sum(axis=0) + 1e-300)
    in_reference = (freqs >= reference_band_hz[0]) & (freqs <= reference_band_hz[1])

    residual_bins = _remove_trend(bins_db, total_db)
    residual_reference = _remove_trend(
        bins_db[in_reference].mean(axis=0)[None, :], total_db
    )[0]

    centred = residual_bins - residual_bins.mean(axis=1, keepdims=True)
    reference_centred = residual_reference - residual_reference.mean()
    denominator = np.linalg.norm(centred, axis=1) * np.linalg.norm(reference_centred)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(
            denominator > 0, (centred @ reference_centred) / denominator, 0.0
        )


def _remove_trend(rows: np.ndarray, predictor: np.ndarray) -> np.ndarray:
    """Residuals of each row after a least-squares fit against `predictor`."""
    design = np.vstack([predictor, np.ones_like(predictor)]).T
    coefficients, *_ = np.linalg.lstsq(design, rows.T, rcond=None)
    return rows - (design @ coefficients).T
