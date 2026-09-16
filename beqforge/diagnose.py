"""Per-channel and coherent-mix features, with explicitly conditional interpretation.

Level invariance is neither necessary nor sufficient for a mastering filter. Tracking can
come from stopband leakage. Quiet-frame contrast can price a correction only under the
noise-proxy assumptions in AGENTS.md's "Evidence and confidence" notes. None identifies an
unknown source spectrum.
"""

import logging
import math
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
from scipy import ndimage, signal

from beqanalyser.design.material import Material

if TYPE_CHECKING:
    from beqanalyser.design.extraction import ExtractionParams

logger = logging.getLogger(__name__)

REFERENCE_POINTS = 400
"""Log-spaced samples the plateau reference is taken over."""

WELCH_NPERSEG = 4096
"""Long enough to resolve ~0.25 Hz at the 1 kHz analysis rate."""


@dataclass(frozen=True, slots=True)
class DiagnoseParams:
    """Choices the diagnostics make. Priors until a corpus settles them."""

    band_hz: tuple[float, float] = (4.0, 200.0)
    """Range the diagnostics report over."""

    exclude_bands_hz: tuple[tuple[float, float], ...] = ()
    """Authored intervals omitted from references and diagnostic evidence."""

    reference_percentile: float = 90.0
    """Percentile of a channel's own response, in log frequency, taken as its reference level.

    This replaces a fixed reference band, which could not work. The band it replaced was
    22-35 Hz, justified as "above any plausible knee and below where mains content starts
    dominating" — which is §2.1's forbidden move written down, since it makes a knee above
    22 Hz unrepresentable rather than unusual. Measured, the band is not a passband on any
    channel of any title tried: it slopes at +0.8 to +40 dB/octave, and on the fourth title
    the mains fall at +40 dB/octave straight through it, because that title's wall is at
    19-21 Hz and the "reference" sits on its shoulder. Referencing there understated those
    channels' attenuation by 13-17 dB.

    A single fixed band cannot be right for both a full-range channel and the LFE in any
    case: the LFE carries its own lowpass, measured at 32-62 Hz across four titles, so a band
    high enough to clear a mains knee is already on the LFE's downslope.

    Sampling uniformly in log frequency weights each octave equally, so the LFE's passband is
    not swamped by the two octaves above its lowpass; a high percentile rather than the
    maximum so a narrow authored feature — the first title's +14 dB hump at 20 Hz — does not
    become the reference."""

    reference_tolerance_db: float = 3.0
    """How far below the reference still counts as plateau, for the reported extent."""

    reference_min_octaves: float = 1 / 3
    """Minimum contiguous width; narrower authored peaks cannot supply a reference."""

    reference_max_slope_db_per_octave: float = 3.0
    """Maximum absolute trend of a usable plateau; steeper monotonic spectra abstain."""

    knee_slope_db_per_octave: float = 14.0
    """Proposal heuristic for a steep channel, never proof of mastering attenuation."""

    strata: tuple[tuple[float, float], ...] = (
        (40.0, 80.0),
        (80.0, 99.0),
        (99.0, 100.0),
    )
    """Percentile bands of passband level the stratified response is measured over.

    A common source envelope can be invariant; changing source spectra survive a fixed filter."""

    level_tolerance_db: float = 6.0
    """Descriptive spread boundary, not a test of whether mastering applied a filter."""

    tracking_window_s: float = 4.0
    """Envelope smoothing for `band_tracking`. Scene-scale, not transient-scale."""

    tracking_floor: float = 0.5
    """Conditional tracking requirement; leakage and common noise can also correlate."""


@dataclass(frozen=True, slots=True)
class ChannelDiagnosis:
    """One channel's response, share of the mix, and whether it looks filtered."""

    name: str
    response_db: np.ndarray
    """Mean spectrum in dB relative to this channel's own plateau."""

    share: np.ndarray
    """Signed Re(channel × conjugate(sum)) / power(sum), including cross terms."""

    max_slope_db_per_octave: float
    max_slope_hz: float
    passband_share: float
    """Mean signed contribution over the mix plateau, for reporting only."""

    is_filtered: bool
    """Legacy name for a steep-channel proposal heuristic, not a mastering claim."""

    plateau_hz: tuple[float, float] = (math.nan, math.nan)
    """Where this channel sits within `reference_tolerance_db` of its own reference level.

    Reported because it is the assumption every attenuation figure rests on, and it is not a
    constant: measured across four titles the lower edge runs 12.8-36.7 Hz and the LFE's
    upper edge 31.7-62.2 Hz. A plateau whose lower edge sits at or above the channel's knee
    means the reference is on the knee's shoulder and the attenuation is understated."""

    share_se: np.ndarray | None = None
    """Across-block standard error of signed coherent contribution; unavailable is NaN."""

    tracking: np.ndarray | None = None
    """Envelope correlation below the own-channel plateau; not an SNR estimate."""

    level_spread_db: np.ndarray | None = None
    contrast_db: np.ndarray | None = None
    contrast_se_db: np.ndarray | None = None
    """Temporal contrast and its bootstrap error, never a causal noise separation."""

    def boost_allowance(self, z: float, tracking_floor: float) -> np.ndarray:
        """Conditional per-channel allowance; missing measurements license no restoration."""
        if (
            self.contrast_db is None
            or self.contrast_se_db is None
            or self.tracking is None
        ):
            return np.zeros_like(self.response_db)
        valid = (
            np.isfinite(self.contrast_se_db)
            & np.isfinite(self.contrast_db)
            & (self.tracking >= tracking_floor)
        )
        return np.where(
            valid, np.maximum(self.contrast_db - z * self.contrast_se_db, 0), 0
        )

    def __str__(self) -> str:
        if self.is_filtered:
            verdict = "steep rolloff (cause unknown)"
        elif self.max_slope_db_per_octave >= 20.0:
            verdict = "steep, reference unavailable"
        else:
            verdict = "no knee"
        return (
            f"{self.name:4s} max slope {self.max_slope_db_per_octave:5.1f} dB/oct "
            f"at {self.max_slope_hz:5.1f} Hz, plateau {self.plateau_hz[0]:5.1f}-"
            f"{self.plateau_hz[1]:5.1f} Hz, {self.passband_share * 100:4.1f}% of "
            f"mix plateau -> {verdict}"
        )


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """What the per-channel decomposition says about this title."""

    freqs: np.ndarray
    mix_db: np.ndarray
    channels: dict[str, ChannelDiagnosis]
    stratified: dict[str, np.ndarray] = field(default_factory=dict)
    """Per-stratum response of the actual combined signal, keyed by stratum label."""

    level_spread_db: np.ndarray | None = None
    """Spread of the combined signal; does not distinguish source from mastering."""

    filter_floor_hz: float = math.nan
    """Legacy name: boundary of mix level invariance, not an identification boundary."""

    noise_floor_hz: float = math.nan
    """Legacy name: mix tracking boundary, conditional on absence of stopband leakage.

    NaN means all tested bands tracked; unavailable measurements terminate the search.
    """

    @property
    def filtered_channels(self) -> list[str]:
        """Channels eligible for a proposal, subject to their own measured allowance."""
        return [name for name, c in self.channels.items() if c.is_filtered]


def mean_spectrum(
    samples: np.ndarray, fs: float, nperseg: int = WELCH_NPERSEG
) -> tuple[np.ndarray, np.ndarray]:
    """Welch mean power spectrum in dB, positive frequencies only."""
    nperseg = min(nperseg, len(samples))
    freqs, power = signal.welch(samples, fs=fs, nperseg=nperseg, noverlap=nperseg // 2)
    keep = freqs > 0
    return freqs[keep], 10.0 * np.log10(power[keep] + 1e-300)


def unexcluded(freqs: np.ndarray, bands: tuple[tuple[float, float], ...]) -> np.ndarray:
    """Inclusive omissions on the original axis; never compress before discovering regions."""
    keep = np.ones_like(freqs, dtype=bool)
    for low, high in bands:
        if not 0 < low <= high:
            raise ValueError("exclusions require 0 < low <= high")
        keep &= ~((freqs >= low) & (freqs <= high))
    return keep


def retained_regions(freqs: np.ndarray, keep: np.ndarray, bands=()) -> list[np.ndarray]:
    """Connected bins, also split by omissions narrower than the sampling interval."""
    indices = np.flatnonzero(keep)
    breaks = np.diff(indices) != 1
    for low, high in bands:
        breaks |= (freqs[indices[:-1]] <= high) & (freqs[indices[1:]] >= low)
    return np.split(indices, np.flatnonzero(breaks) + 1)


def smooth_unexcluded(
    values: np.ndarray, freqs: np.ndarray, bands, width: int
) -> np.ndarray:
    """Smooth each retained segment separately; omitted bins request zero correction."""
    result = np.zeros_like(values)
    for region in retained_regions(
        freqs, unexcluded(freqs, bands) & np.isfinite(values), bands
    ):
        if not len(region):
            continue
        kernel = min(width, len(region))
        result[region] = np.convolve(
            values[region], np.ones(kernel) / kernel, mode="same"
        )
    return result


def plateau_reference(
    values_db: np.ndarray,
    freqs: np.ndarray,
    params: DiagnoseParams,
    exclude_bands_hz: tuple[tuple[float, float], ...] = (),
) -> tuple[float, tuple[float, float]]:
    """A channel's own reference level, and the band over which it holds it.

    The level a channel's attenuation is measured against has to come from that channel on
    that title. See `DiagnoseParams.reference_percentile` for why a fixed band cannot do it.
    """
    grid = np.geomspace(params.band_hz[0], params.band_hz[1], REFERENCE_POINTS)
    bands = (*params.exclude_bands_hz, *exclude_bands_hz)
    source = unexcluded(freqs, bands) & np.isfinite(values_db)
    if not source.any():
        return math.nan, (math.nan, math.nan)
    curve = np.interp(grid, freqs[source], values_db[source], left=np.nan, right=np.nan)
    curve[~unexcluded(grid, bands)] = np.nan
    # Median discovery over roughly one sixth octave suppresses estimator-bin scatter
    # without turning a narrow authored peak into the reference. Level uses the raw curve.
    discovery = np.full_like(curve, np.nan)
    for region in retained_regions(grid, np.isfinite(curve), bands):
        if len(region):
            discovery[region] = ndimage.median_filter(
                curve[region], size=11, mode="nearest"
            )
    finite = np.isfinite(curve)
    if not finite.any():
        return math.nan, (math.nan, math.nan)
    threshold = float(np.percentile(curve[finite], params.reference_percentile))
    within = finite & (np.abs(discovery - threshold) <= params.reference_tolerance_db)
    regions = retained_regions(grid, within, bands)
    candidates = []
    for region in regions:
        if len(region) < 3:
            continue
        width = float(np.log2(grid[region[-1]] / grid[region[0]]))
        slope = band_slope(curve, grid, grid[region[0]], grid[region[-1]])
        if (
            width < params.reference_min_octaves
            or abs(slope) > params.reference_max_slope_db_per_octave
        ):
            continue
        candidates.append(
            (width, -float(np.ptp(curve[region])), -int(region[0]), region)
        )
    if not candidates:
        return math.nan, (math.nan, math.nan)
    # Widest first, then flattest, then lowest frequency: deterministic and never bridges a valley.
    region = max(candidates, key=lambda item: item[:3])[3]
    return float(np.median(curve[region])), (
        float(grid[region[0]]),
        float(grid[region[-1]]),
    )


def band_slope(
    values_db: np.ndarray, freqs: np.ndarray, low_hz: float, high_hz: float
) -> float:
    """Least-squares slope in dB per octave over a band. Positive falls toward the bottom."""
    band = (freqs >= low_hz) & (freqs <= high_hz)
    if band.sum() < 3 or not np.isfinite(values_db[band]).all():
        return math.nan
    octaves = np.log2(freqs[band])
    return float(np.polyfit(octaves, values_db[band], 1)[0])


def steepest_slope(
    values_db: np.ndarray,
    freqs: np.ndarray,
    band_hz: tuple[float, float],
    exclude_bands_hz: tuple[tuple[float, float], ...] = (),
) -> tuple[float, float]:
    """The steepest half-octave slope in a band, and where it is.

    A knee is local. A slope taken across the whole band averages the wall together with the
    plateau either side of it and reports neither.
    """
    best, at = 0.0, math.nan
    candidates = freqs[(freqs >= band_hz[0]) & (freqs <= band_hz[1] / math.sqrt(2))]
    for low in candidates:
        if any(a <= low * math.sqrt(2) and b >= low for a, b in exclude_bands_hz):
            continue
        slope = band_slope(values_db, freqs, low, low * math.sqrt(2))
        if math.isfinite(slope) and slope > best:
            best, at = slope, float(low)
    return best, at


def _spectral_blocks(samples: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Non-overlapping Hann frames, grouped later into balanced temporal blocks.

    Block error is descriptive, not calibrated coverage: scenes can span blocks.
    """
    n = min(WELCH_NPERSEG, len(samples))
    frames = np.lib.stride_tricks.sliding_window_view(samples, n)[::n]
    return np.fft.rfftfreq(n, 1 / fs)[1:], np.fft.rfft(frames * np.hanning(n), axis=1)[
        :, 1:
    ]


def _ratio_error(
    numerator: np.ndarray, denominator: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Ratio of means and delete-block jackknife error; retain coherent signed terms."""
    groups = [
        a
        for a in np.array_split(np.arange(len(numerator)), max(1, len(numerator) // 16))
        if len(a)
    ]
    n = np.array([numerator[g].sum(axis=0) for g in groups])
    d = np.array([denominator[g].sum(axis=0) for g in groups])
    total_n, total_d = n.sum(axis=0), d.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = total_n / total_d
        leave = (total_n - n) / (total_d - d)
    error = (
        np.sqrt(
            (len(n) - 1) / len(n) * np.sum((leave - leave.mean(axis=0)) ** 2, axis=0)
        )
        if len(n) >= 2
        else np.full_like(ratio, np.nan)
    )
    return ratio, error


def coherent_shares(
    material: Material,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Signed coherent contributions and temporal uncertainty. Cancellation may give >1 or <0."""
    from beqanalyser.design.material import LFE_GAIN, MAIN_GAIN

    spectra = {
        name: _spectral_blocks(samples, material.fs)[1]
        * (LFE_GAIN if name == "LFE" else MAIN_GAIN)
        for name, samples in material.channels.items()
    }
    if not spectra:
        return {}, {}
    summed = sum(spectra.values())
    power = np.abs(summed) ** 2
    values = {
        name: _ratio_error(np.real(x * summed.conj()), power)
        for name, x in spectra.items()
    }
    return (
        {name: pair[0] for name, pair in values.items()},
        {name: pair[1] for name, pair in values.items()},
    )


def mix_shares(material: Material, spectra=None) -> dict[str, np.ndarray]:
    """Signed coherent contribution; `spectra` retained for source compatibility only."""
    return coherent_shares(material)[0]


def supported_mix_change(
    before: np.ndarray, after: np.ndarray, fs: float, z: float
) -> tuple[np.ndarray, np.ndarray]:
    """Lower estimate of the proposed coherent power ratio, including block uncertainty.

    Recomputed after channel restoration: a formerly quiet channel cannot inherit another
    channel's precision. No independent-channel power-sum approximation is made.
    """
    freqs, original = _spectral_blocks(before, fs)
    _, changed = _spectral_blocks(after, fs)
    ratio, error = _ratio_error(np.abs(changed) ** 2, np.abs(original) ** 2)
    lower = np.where(np.isfinite(error), ratio - z * error, 1.0)
    return freqs, 10 * np.log10(np.maximum(lower, 1.0))


def stratified_response(
    samples: np.ndarray,
    fs: float,
    params: DiagnoseParams,
    reference_hz: tuple[float, float],
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Response relative to the channel's plateau, per scene-loudness stratum.

    `reference_hz` is that channel's own plateau, not a constant: normalising on the knee's
    shoulder makes the normalisation point itself level-dependent and contaminates the very
    spread this measures.

    Source variation survives a fixed filter, while common-envelope natural colouring can
    pass this check. This is a descriptive feature, not a causal classifier.
    """
    frames = np.lib.stride_tricks.sliding_window_view(samples, WELCH_NPERSEG)[
        :: WELCH_NPERSEG // 2
    ]
    window = np.hanning(WELCH_NPERSEG)
    power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
    freqs = np.fft.rfftfreq(WELCH_NPERSEG, 1.0 / fs)
    passband = (freqs >= reference_hz[0]) & (freqs <= reference_hz[1])
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


def scene_envelope(
    samples: np.ndarray,
    fs: float,
    band_hz: tuple[float, float],
    params: DiagnoseParams,
) -> np.ndarray:
    """Smoothed level of one band over time, in dB. The unit `band_tracking` correlates."""
    low, high = band_hz
    sos = signal.butter(4, [low, high], btype="band", fs=fs, output="sos")
    filtered = signal.sosfiltfilt(sos, samples)
    width = int(params.tracking_window_s * fs)
    return 10.0 * np.log10(_moving_average(filtered**2, width) + 1e-30)


def _moving_average(values: np.ndarray, width: int) -> np.ndarray:
    """Uniform moving average, as a difference of prefix sums.

    `np.convolve` with a uniform kernel is a direct O(n*w) correlation: over the 6.8M samples of
    a two-hour title with a 4,000-sample window it measured **3.05 s a call**, against 0.047 s
    here — and `diagnose` makes several. It was the largest single item left in the stage.

    **Not bit-identical, and in the less comfortable direction.** A prefix sum accumulates
    rounding over the whole signal where the direct convolution accumulates it over one window,
    so this is the *less* accurate of the two, by roughly the ratio of those lengths. It is
    computed in float64 over values that are all positive — squared samples — so there is no
    cancellation to amplify, and the absolute error lands around 1e-10 on a quantity spanning
    tens of dB.

    What that has to be weighed against is the decision it feeds. `band_tracking` correlates
    this envelope against the passband's and compares the result to `tracking_floor`, 0.5;
    measured on real material the correlations are 0.92, 0.93, 0.89 and 0.78. A perturbation
    eleven orders of magnitude below the signal does not move a correlation sitting that far
    from its threshold, and the four-title records confirm it: identical verdicts.
    """
    if width <= 1 or values.size < width:
        return values
    prefix = np.cumsum(values, dtype=np.float64)
    total = np.empty(values.size - width + 1, dtype=np.float64)
    total[0] = prefix[width - 1]
    total[1:] = prefix[width:] - prefix[:-width]
    return total / width


def band_tracking(
    samples: np.ndarray,
    fs: float,
    band_hz: tuple[float, float],
    params: DiagnoseParams,
    reference_hz: tuple[float, float],
    reference: np.ndarray | None = None,
) -> float:
    """Correlation between a band's scene envelope and the passband's.

    Programme events can share an envelope; stopband leakage can share it too.
    Restricted to frames where the passband is actually doing something, so the score is not
    manufactured by both bands falling silent together.

    `reference` is the passband's own envelope, which does not depend on `band_hz` and so is
    the same for every band the caller walks down through. Computed here when not supplied,
    since a single call should not need the caller to know that; passed in by `diagnose`,
    which asks about several bands and would otherwise pay for it once per band.
    """
    if reference is None:
        reference = scene_envelope(samples, fs, reference_hz, params)
    target = scene_envelope(samples, fs, band_hz, params)
    live = reference > (np.percentile(reference, 99) - 30.0)
    if live.sum() < 100:
        return math.nan
    return float(np.corrcoef(reference[live], target[live])[0, 1])


def diagnose(
    material: Material,
    params: DiagnoseParams | None = None,
    extraction_params: "ExtractionParams | None" = None,
) -> Diagnosis:
    """Decompose the mix per channel and locate the two floors R1 and R2 depend on."""
    params = params or DiagnoseParams()
    freqs, mix_db = mean_spectrum(material.mono_mix, material.fs)
    band = (freqs >= params.band_hz[0]) & (freqs <= params.band_hz[1])
    freqs, mix_db = freqs[band], mix_db[band]
    spectra = {
        name: mean_spectrum(samples, material.fs)[1]
        for name, samples in material.channels.items()
    }
    shares, share_errors = coherent_shares(material)
    _, mix_plateau = plateau_reference(mix_db, freqs, params)
    from beqanalyser.design.extraction import ExtractionParams, extract

    extraction_params = extraction_params or ExtractionParams()
    extraction_params = replace(
        extraction_params,
        exclude_bands_hz=tuple(
            dict.fromkeys(
                (*extraction_params.exclude_bands_hz, *params.exclude_bands_hz)
            )
        ),
    )

    channels: dict[str, ChannelDiagnosis] = {}
    for name in material.channels:
        response = spectra[name][band]
        level, plateau = plateau_reference(response, freqs, params)
        response = np.where(
            unexcluded(freqs, params.exclude_bands_hz), response, np.nan
        )
        slope, at = steepest_slope(
            response, freqs, params.band_hz, params.exclude_bands_hz
        )
        response = response - level
        share = shares[name][band] if len(shares[name]) != len(freqs) else shares[name]
        # the share band is common to every channel on purpose: which channel supplies the
        # low end is a comparison, and a comparison needs one yardstick
        in_share_band = (freqs >= mix_plateau[0]) & (freqs <= mix_plateau[1])
        in_share_band &= unexcluded(freqs, params.exclude_bands_hz)
        passband_share = (
            float(share[in_share_band].mean()) if in_share_band.any() else 0.0
        )
        _, channel_spread, _, _, tracking = _temporal_evidence(
            material.channels[name], material.fs, params, plateau, freqs
        )
        envelope = extract(material.channels[name], material.fs, extraction_params)
        channels[name] = ChannelDiagnosis(
            name=name,
            response_db=response,
            share=share,
            max_slope_db_per_octave=slope,
            max_slope_hz=at,
            passband_share=passband_share,
            is_filtered=(
                math.isfinite(level) and slope >= params.knee_slope_db_per_octave
            ),
            plateau_hz=plateau,
            share_se=share_errors[name][band],
            tracking=tracking,
            level_spread_db=channel_spread,
            contrast_db=np.interp(
                freqs, envelope.freqs, envelope.margin_db, left=np.nan, right=np.nan
            ),
            contrast_se_db=np.interp(
                freqs, envelope.freqs, envelope.margin_se_db, left=np.inf, right=np.inf
            ),
        )
        logger.info(f"  {channels[name]}")

    strata, spread, filter_floor, noise_floor, _ = _temporal_evidence(
        material.mono_mix, material.fs, params, mix_plateau, freqs
    )
    return Diagnosis(
        freqs=freqs,
        mix_db=mix_db,
        channels=channels,
        stratified=strata,
        level_spread_db=spread,
        filter_floor_hz=filter_floor,
        noise_floor_hz=noise_floor,
    )


def _temporal_evidence(
    subject: np.ndarray,
    fs: float,
    params: DiagnoseParams,
    reference_hz: tuple[float, float],
    freqs: np.ndarray,
) -> tuple[dict[str, np.ndarray], np.ndarray, float, float, np.ndarray]:
    """Measure each subject against its own plateau, including the actual combined mix."""
    unavailable = np.full_like(freqs, np.nan)
    if not all(math.isfinite(f) for f in reference_hz) or len(subject) < WELCH_NPERSEG:
        return {}, unavailable, math.nan, params.band_hz[1], unavailable
    strata_freqs, strata = stratified_response(subject, fs, params, reference_hz)
    if len(strata) < 2:
        spread = np.full_like(strata_freqs, np.nan)
    else:
        spread = np.ptp(np.vstack(list(strata.values())), axis=0)
    # searched downward from the *bottom* of the channel's plateau, not from the top of the
    # spectrum or the top of the plateau. Above it the strata diverge because loud scenes have
    # a different content spectrum, not because anything was filtered, and the spread is
    # already climbing at the plateau's upper edge — starting there stops on the first step.
    consistent = (spread <= params.level_tolerance_db) & unexcluded(
        strata_freqs, params.exclude_bands_hz
    )
    region = (strata_freqs >= params.band_hz[0]) & (strata_freqs <= reference_hz[0])
    # a plateau reaching the bottom of the analysis band leaves nothing to search: there is
    # no attenuation under it whose level-independence could fail. That is the honest answer
    # rather than an error, and it is what unfiltered material looks like.
    filter_floor = (
        _lowest_run(strata_freqs[region], consistent[region])
        if region.any()
        else params.band_hz[0]
    )

    if len(strata) < 2:
        filter_floor = math.nan

    noise_floor = math.nan
    # the passband envelope is what every band is compared against, so it is computed once
    # here rather than again inside each call — it was 4 s a band on a two-hour title
    tracking_reference = scene_envelope(subject, fs, reference_hz, params)
    tracking_curve = np.where(freqs >= reference_hz[0], 1.0, np.nan)
    for low, high in _octave_bands(params.band_hz[0], reference_hz[0]):
        if any(a <= high and b >= low for a, b in params.exclude_bands_hz):
            noise_floor = high
            break
        tracking = band_tracking(
            subject,
            fs,
            (low, high),
            params,
            reference_hz,
            reference=tracking_reference,
        )
        tracking_curve[(freqs >= low) & (freqs <= high)] = tracking
        # `not >=` rather than `<`, so a band that could not be measured at all fails the
        # same way one that failed does. NaN is not evidence of content, and reading it as
        # such is how a floor gets missed in the direction that costs something.
        if not tracking >= params.tracking_floor:
            noise_floor = high
            break

    return (
        {k: np.interp(freqs, strata_freqs, v) for k, v in strata.items()},
        np.interp(freqs, strata_freqs, spread),
        filter_floor,
        noise_floor,
        tracking_curve,
    )


def _lowest_run(freqs: np.ndarray, mask: np.ndarray) -> float:
    """Lowest frequency of the contiguous run of `mask` ending at the top of the array.

    Callers pass a region ending at the passband, so this walks down from a frequency the
    subject has a reference plateau. Isolated agreement further down does not establish
    continuity with that plateau; it must not be joined to the run above it. Neither kind
    of agreement establishes a mastering cause.
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
    while top > low:
        bands.append((max(low, top / math.sqrt(2)), top))
        top = max(low, top / math.sqrt(2))
    return bands
