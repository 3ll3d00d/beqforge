"""Per-channel diagnostics — where the evidence for a rolloff actually lives.

§3.1 identifies from the summed mix because the sum is what is listened to. That holds for
what has to be *corrected*; it does not hold for where the evidence is. On the second title
tried, the whole rolloff is an LFE high-pass at ~20 Hz and the LFE contributes 0.4% of mix
power at 8 Hz, so the wall is absent from the sum below ~15 Hz and identification from the
sum returns an unrepresentable answer.

Three measurements, each answering a question no aggregate of the sum can:

* `mix_shares` — which channel a given frequency's energy comes from, so "invisible in the
  sum" becomes a number rather than an inference.
* `stratified_response` — whether an attenuation is *level-independent*, which is what makes
  it a filter rather than content. This is R2 of §6.4.
* `band_tracking` — whether energy below the knee is programme-correlated content or a
  stationary floor. This sets the terminus R1 refers to as "the noise floor".

The last two are measured on whichever channel dominates the passband, and they run whether
or not any channel was called filtered. They ask about the material, not about a filter, and
gating them on a knee made the guard unreachable on the sparse material it exists to catch.

Nothing here decides anything; it produces the numbers the pipeline and the report use.
"""

import logging
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import signal

from beqanalyser.design.material import Material

logger = logging.getLogger(__name__)

WELCH_NPERSEG = 4096
"""Long enough to resolve ~0.25 Hz at the 1 kHz analysis rate."""


@dataclass(frozen=True, slots=True)
class DiagnoseParams:
    """Choices the diagnostics make. Priors until a corpus settles them."""

    band_hz: tuple[float, float] = (4.0, 200.0)
    """Range the diagnostics report over."""

    passband_hz: tuple[float, float] = (22.0, 35.0)
    """Reference band a channel's own response is expressed relative to.

    Above any plausible knee and below where mains content starts dominating. A channel's
    attenuation is only meaningful against its own passband — comparing channels in absolute
    terms says which is louder, not which is filtered."""

    knee_slope_db_per_octave: float = 14.0
    """Slope over a half-octave window above which a channel is called filtered.

    **The weakest threshold in the system.** Across the audible channels of three titles —
    those clearing `min_passband_share` — it has to catch title 3's LFE at 15.9 dB/octave and
    spare title 2's unfiltered L at 13.5, so max slope alone separates the two populations by
    2.4 dB/octave. At the original 20.0 it missed title 3 entirely, and a 2nd-order Butterworth
    at 12 dB/octave is still below anything safe to set here.

    Slope is the wrong discriminator and this value is a stopgap. `stratified_response` already
    measures the property that actually distinguishes a filter from a natural envelope — a
    filter's relative shape does not vary with scene loudness (§6.4 R2) — and running it per
    audible channel rather than only on the channel already chosen would classify on evidence
    instead of on a 2.4 dB/octave gap. See §12."""

    strata: tuple[tuple[float, float], ...] = (
        (40.0, 80.0),
        (80.0, 99.0),
        (99.0, 100.0),
    )
    """Percentile bands of passband level the stratified response is measured over.

    A linear filter's relative response is identical in every stratum. Content's is not."""

    min_passband_share: float = 0.05
    """Share of summed-mix passband power below which a channel cannot be the rolloff.

    A steep slope is not evidence of a filter if the channel supplies nothing to begin with:
    the surrounds fall away below 20 Hz at 24-34 dB/octave simply because they carry almost no
    bass, while contributing 1-2% of passband power. Restoring a channel that is inaudible in
    the passband cannot be what makes the mix flat, and inverting its apparent attenuation by
    tens of dB would manufacture content that was never there.

    This is the automatic form of an exclusion that was manual on the first title."""

    level_tolerance_db: float = 6.0
    """Spread across strata above which an attenuation is not a fixed filter."""

    tracking_window_s: float = 4.0
    """Envelope smoothing for `band_tracking`. Scene-scale, not transient-scale."""

    tracking_floor: float = 0.5
    """Correlation with the passband below which a band is not carrying content."""


@dataclass(frozen=True, slots=True)
class ChannelDiagnosis:
    """One channel's response, share of the mix, and whether it looks filtered."""

    name: str
    response_db: np.ndarray
    """Mean spectrum in dB relative to this channel's own passband."""

    share: np.ndarray
    """Fraction of summed-mix power this channel supplies, per bin."""

    max_slope_db_per_octave: float
    max_slope_hz: float
    passband_share: float
    """Share of summed-mix power this channel supplies across the passband."""

    is_filtered: bool

    def __str__(self) -> str:
        if self.is_filtered:
            verdict = "filtered"
        elif self.max_slope_db_per_octave >= 20.0:
            verdict = "steep but inaudible"
        else:
            verdict = "no knee"
        return (
            f"{self.name:4s} max slope {self.max_slope_db_per_octave:5.1f} dB/oct "
            f"at {self.max_slope_hz:5.1f} Hz, {self.passband_share * 100:4.1f}% of "
            f"passband -> {verdict}"
        )


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """What the per-channel decomposition says about this title."""

    freqs: np.ndarray
    mix_db: np.ndarray
    channels: dict[str, ChannelDiagnosis]
    stratified: dict[str, np.ndarray] = field(default_factory=dict)
    """Per-stratum response of the passband-dominant channel, keyed by stratum label."""

    level_spread_db: np.ndarray | None = None
    """Spread across strata per bin. Large means the attenuation is not a fixed filter."""

    filter_floor_hz: float = math.nan
    """Below this the attenuation stops being level-independent — R2.

    Not where the correction must stop. It is where inversion stops being *identification*
    of a filter and becomes shaping, which is a claim about confidence, not about the target.
    """

    noise_floor_hz: float = math.nan
    """Below this there is no programme-correlated content left — R1's terminus.

    NaN means every band down to the bottom tracked the passband, so the correction is
    expected to reach the bottom of the analysis band. A band that could not be measured is
    *not* NaN — it terminates the search like a band that failed, because being unable to
    see content is not the same as seeing content.
    """

    @property
    def filtered_channels(self) -> list[str]:
        return [name for name, c in self.channels.items() if c.is_filtered]


def mean_spectrum(
    samples: np.ndarray, fs: float, nperseg: int = WELCH_NPERSEG
) -> tuple[np.ndarray, np.ndarray]:
    """Welch mean power spectrum in dB, positive frequencies only."""
    freqs, power = signal.welch(samples, fs=fs, nperseg=nperseg, noverlap=nperseg // 2)
    keep = freqs > 0
    return freqs[keep], 10.0 * np.log10(power[keep] + 1e-300)


def band_slope(
    values_db: np.ndarray, freqs: np.ndarray, low_hz: float, high_hz: float
) -> float:
    """Least-squares slope in dB per octave over a band. Positive falls toward the bottom."""
    band = (freqs >= low_hz) & (freqs <= high_hz)
    if band.sum() < 3:
        return math.nan
    octaves = np.log2(freqs[band])
    return float(np.polyfit(octaves, values_db[band], 1)[0])


def steepest_slope(
    values_db: np.ndarray, freqs: np.ndarray, band_hz: tuple[float, float]
) -> tuple[float, float]:
    """The steepest half-octave slope in a band, and where it is.

    A knee is local. A slope taken across the whole band averages the wall together with the
    plateau either side of it and reports neither.
    """
    best, at = 0.0, math.nan
    candidates = freqs[(freqs >= band_hz[0]) & (freqs <= band_hz[1] / math.sqrt(2))]
    for low in candidates:
        slope = band_slope(values_db, freqs, low, low * math.sqrt(2))
        if math.isfinite(slope) and slope > best:
            best, at = slope, float(low)
    return best, at


def mix_shares(material: Material, freqs: np.ndarray) -> dict[str, np.ndarray]:
    """Fraction of summed-mix power each channel supplies, per bin.

    Uses the same gains `tools/extract.py` applied when building the mix, so the shares sum
    to ~1 and can be read directly as "where this frequency's energy comes from".
    """
    from beqanalyser.design.material import LFE_GAIN, MAIN_GAIN

    contributions: dict[str, np.ndarray] = {}
    for name, samples in material.channels.items():
        gain = LFE_GAIN if name == "LFE" else MAIN_GAIN
        _, power_db = mean_spectrum(samples, material.fs)
        contributions[name] = 10.0 ** (power_db / 10.0) * gain * gain
    total = sum(contributions.values())
    return {name: value / total for name, value in contributions.items()}


def stratified_response(
    samples: np.ndarray,
    fs: float,
    params: DiagnoseParams,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Response relative to the passband, measured separately per scene-loudness stratum.

    This is the level-independence test of §6.4 R2. A linear filter's relative response is
    the same however loud the scene; content's is not. On the second title the LFE measured
    -63 dB re passband at 6 Hz in median scenes, -40 in loud ones and -36 in the loudest 1%,
    which rules out a fixed filter *and* a fixed noise floor in one measurement — where the
    depth of the attenuation alone rules out neither.
    """
    frames = np.lib.stride_tricks.sliding_window_view(samples, WELCH_NPERSEG)[
        :: WELCH_NPERSEG // 2
    ]
    window = np.hanning(WELCH_NPERSEG)
    power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
    freqs = np.fft.rfftfreq(WELCH_NPERSEG, 1.0 / fs)
    passband = (freqs >= params.passband_hz[0]) & (freqs <= params.passband_hz[1])
    level = 10.0 * np.log10(power[:, passband].mean(axis=1) + 1e-300)

    responses: dict[str, np.ndarray] = {}
    for low, high in params.strata:
        chosen = (level >= np.percentile(level, low)) & (
            level <= np.percentile(level, high)
        )
        if chosen.sum() < 8:
            continue
        spectrum = 10.0 * np.log10(power[chosen].mean(axis=0) + 1e-300)
        responses[f"p{low:g}-{high:g}"] = spectrum - spectrum[passband].mean()
    return freqs, responses


def band_tracking(
    samples: np.ndarray,
    fs: float,
    band_hz: tuple[float, float],
    params: DiagnoseParams,
) -> float:
    """Correlation between a band's scene envelope and the passband's.

    Real bass events have simultaneous energy across frequency; a stationary floor does not.
    Restricted to frames where the passband is actually doing something, so the score is not
    manufactured by both bands falling silent together.
    """

    def envelope(low: float, high: float) -> np.ndarray:
        sos = signal.butter(4, [low, high], btype="band", fs=fs, output="sos")
        filtered = signal.sosfiltfilt(sos, samples)
        width = int(params.tracking_window_s * fs)
        smoothed = np.convolve(filtered**2, np.ones(width) / width, mode="valid")
        return 10.0 * np.log10(smoothed + 1e-30)

    reference = envelope(*params.passband_hz)
    target = envelope(*band_hz)
    live = reference > (np.percentile(reference, 99) - 30.0)
    if live.sum() < 100:
        return math.nan
    return float(np.corrcoef(reference[live], target[live])[0, 1])


def diagnose(material: Material, params: DiagnoseParams | None = None) -> Diagnosis:
    """Decompose the mix per channel and locate the two floors R1 and R2 depend on."""
    params = params or DiagnoseParams()
    freqs, mix_db = mean_spectrum(material.mono_mix, material.fs)
    band = (freqs >= params.band_hz[0]) & (freqs <= params.band_hz[1])
    freqs, mix_db = freqs[band], mix_db[band]
    shares = mix_shares(material, freqs)

    channels: dict[str, ChannelDiagnosis] = {}
    for name, samples in material.channels.items():
        _, response = mean_spectrum(samples, material.fs)
        response = response[band]
        passband = (freqs >= params.passband_hz[0]) & (freqs <= params.passband_hz[1])
        response = response - response[passband].mean()
        slope, at = steepest_slope(response, freqs, params.band_hz)
        share = shares[name][band] if len(shares[name]) != len(freqs) else shares[name]
        channels[name] = ChannelDiagnosis(
            name=name,
            response_db=response,
            share=share,
            max_slope_db_per_octave=slope,
            max_slope_hz=at,
            passband_share=float(share[passband].mean()),
            is_filtered=(
                slope >= params.knee_slope_db_per_octave
                and float(share[passband].mean()) >= params.min_passband_share
            ),
        )
        logger.info(f"  {channels[name]}")

    filtered = [name for name, c in channels.items() if c.is_filtered]
    # The floors are measured on the channel that dominates the passband, whether or not any
    # channel was called filtered. Neither measurement needs a knee: "is this level-
    # independent" and "is this programme-correlated" are questions about the material, and
    # nesting them inside the filtered branch made the guard unreachable on exactly the case
    # it exists for. Content high-passed at 30 Hz over a -26 dB floor is found at order 8
    # (slope 40.7 dB/oct, floor at 15.6 Hz) and missed entirely at order 2 (13.6 dB/oct, no
    # channel filtered, no floor, `flatten` free to ask for +22 dB at 5 Hz) — the same
    # material either way, separated only by a steepness the floor does not depend on.
    if not filtered:
        logger.info("No channel shows a knee; the sum is the only available evidence")
    if not channels:
        return Diagnosis(freqs=freqs, mix_db=mix_db, channels=channels)

    # the channel that dominates the passband, not whichever came first in the dict: on the
    # first title `filtered` is [L, R, C, LFE] and the mains carry 6-8% each against the LFE's
    # 76%, so stratifying the first one measures a channel nobody hears down there
    dominant = max(channels, key=lambda name: channels[name].passband_share)
    subject = material.channels[dominant]
    strata_freqs, strata = stratified_response(subject, material.fs, params)
    if not strata:
        logger.warning(
            f"{dominant} has too few frames in any loudness stratum to test level "
            "independence; no floor measured"
        )
        return Diagnosis(freqs=freqs, mix_db=mix_db, channels=channels)
    stacked = np.vstack(list(strata.values()))
    spread = np.ptp(stacked, axis=0)
    # searched downward from the *bottom* of the passband, not from the top of the spectrum
    # or the top of the passband. Above the passband the strata diverge because loud scenes
    # have a different content spectrum, not because anything was filtered, and the spread is
    # already climbing at the passband's upper edge — starting there stops on the first step.
    consistent = spread <= params.level_tolerance_db
    region = (strata_freqs >= params.band_hz[0]) & (
        strata_freqs <= params.passband_hz[0]
    )
    filter_floor = _lowest_run(strata_freqs[region], consistent[region])

    noise_floor = math.nan
    for low, high in _octave_bands(params.band_hz[0], params.passband_hz[0]):
        tracking = band_tracking(subject, material.fs, (low, high), params)
        # `not >=` rather than `<`, so a band that could not be measured at all fails the
        # same way one that failed does. NaN is not evidence of content, and reading it as
        # such is how a floor gets missed in the direction that costs something.
        if not tracking >= params.tracking_floor:
            noise_floor = high
            break

    logger.info(
        f"Filtered: {', '.join(filtered) if filtered else 'none'} "
        f"(floors measured on {dominant}); level-independent above "
        f"{filter_floor:.1f} Hz, content down to "
        f"{'the bottom of the band' if math.isnan(noise_floor) else f'{noise_floor:.1f} Hz'}"
    )
    return Diagnosis(
        freqs=freqs,
        mix_db=mix_db,
        channels=channels,
        stratified={k: np.interp(freqs, strata_freqs, v) for k, v in strata.items()},
        level_spread_db=np.interp(freqs, strata_freqs, spread),
        filter_floor_hz=filter_floor,
        noise_floor_hz=noise_floor,
    )


def _lowest_run(freqs: np.ndarray, mask: np.ndarray) -> float:
    """Lowest frequency of the contiguous run of `mask` ending at the top of the array.

    Callers pass a region ending at the passband, so this walks down from a frequency the
    channel is known to be unfiltered at. An isolated island of agreement further down is
    noise agreeing with itself, not the filter still being a filter, and must not be joined
    to the run above it.
    """
    if not mask.any():
        return float(freqs[-1])
    index = len(mask) - 1
    while index >= 0 and mask[index]:
        index -= 1
    return float(freqs[min(index + 1, len(freqs) - 1)])


def _octave_bands(low: float, high: float) -> list[tuple[float, float]]:
    """Descending octave-ish bands between `high` and `low`, widest first."""
    bands: list[tuple[float, float]] = []
    top = high
    while top / math.sqrt(2) > low:
        bands.append((max(low, top / math.sqrt(2)), top))
        top /= math.sqrt(2)
    return bands
