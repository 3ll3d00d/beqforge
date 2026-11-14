"""Applying a design and measuring what it did.

The residual only says the cascade matches the target it was given. It cannot say the target
was right. This applies the filter to the signal and measures the corrected low end, which is
what a person checks by eye: **a correct rolloff correction leaves the bottom flat, or mildly
rising toward the lowest frequencies.**

That criterion discriminates where the residual does not. Four candidate designs for one title
all reported residuals under 0.5 dB against their own targets; applied, they left the 5-16 Hz
band spread by 4.9, 5.1, 6.7 and 11.8 dB. The last over-corrected by 13 dB at 10 Hz and its
residual said nothing about it.

A smoke test, not a confidence measure (§6.2): it runs the same estimator's arithmetic over its
own output, so a systematic error inverted into the correction is invisible here too.
"""

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy import fft, signal

from beqforge import DESIGN_GRID, BiquadSpec
from beqforge.diagnose import DiagnoseParams, plateau_reference
from beqforge.filters import (
    Realisation,
    biquad_sos,
    magnitude_db,
    publication_filters,
    unstable_sections,
)

logger = logging.getLogger(__name__)

if (
    TYPE_CHECKING
):  # `accept` imports `Correction` from here, so this stays one-directional
    from beqforge.accept import AcceptParams


def device_error_db(
    filters: list[BiquadSpec], freqs: np.ndarray, realisation: Realisation
) -> np.ndarray:
    """dB the device's own coefficient rounding adds, on `freqs`.

    The device takes coefficients and stores them in its own format, so the response it realises
    is not the one the optimiser produced. Measured at the device's rate, where the rounding
    happens, then resampled onto the analysis axis.

    Over real material this runs from under a tenth of a dB to a little over one. Two things worth knowing about
    its size: a 32-bit float device is no better than 5.23 fixed point here, because the
    coefficients that matter sit near |a1| = 2 where both formats have the same 1.19e-7 absolute
    step; and the mechanism is not pole radius — one step moves that by 0.03% of its margin —
    but cancellation in `1+a1+a2`, the denominator at DC, which scales as (2*pi*f/fs)^2 and
    measures under five quantisation steps on every section below ~15 Hz at 96 kHz. That is why
    halving the rate helps fourfold and why pushing a section lower makes it worse.
    """
    sos = biquad_sos(filters, realisation.fs)
    exact = magnitude_db(sos, DESIGN_GRID, realisation.fs)
    rounded = magnitude_db(realisation.quantise(sos), DESIGN_GRID, realisation.fs)
    return np.interp(freqs, DESIGN_GRID, rounded - exact)


@dataclass(frozen=True, slots=True)
class DeviceTransfer:
    """`device_waveform`'s half that depends on the cascade, not the signal.

    The published device's complex transfer on the FFT grid of `samples` long input, with
    the padding it was built for: 0.09 s of the 0.25 s a 6.4M-sample signal takes, the same
    for every signal of that length run through one cascade. Keeps what it was built for, so
    `device_waveform` can refuse one built for something else.
    """

    samples: int
    fs: float
    realisation: Realisation
    guard: int
    size: int
    transfer: np.ndarray


def device_transfer(
    filters: list[BiquadSpec],
    samples: int,
    fs: float,
    realisation: Realisation | None = None,
) -> DeviceTransfer | None:
    """The device's transfer for `samples` long input, as `device_waveform` builds it.

    `None` when the cascade is empty, which `device_waveform` returns the input for. Refuses
    what it refuses: a device rate below the analysis rate, an unstable device.
    """
    device = realisation or Realisation()
    filters = publication_filters(filters)
    if not filters:
        return None
    if device.fs < fs:
        raise ValueError("device rate must cover the analysis bandwidth")
    if unstable_sections(filters, device):
        raise ValueError(
            "unstable published device has no finite verification waveform"
        )
    sos = device.quantise(biquad_sos(filters, device.fs))
    radius = max(float(np.max(np.abs(np.roots(row[3:])))) for row in sos)
    decay = 0.0 if radius == 0 else -math.log(1e-12) / -math.log(radius)
    guard = max(math.ceil(8 * fs), math.ceil(decay * len(sos) * fs / device.fs))
    size = fft.next_fast_len(samples + 2 * guard)
    freqs = fft.rfftfreq(size, 1 / fs)
    _, transfer = signal.freqz_sos(sos, worN=freqs, fs=device.fs)
    return DeviceTransfer(samples, fs, device, guard, size, transfer)


def device_waveform(
    filters: list[BiquadSpec],
    samples: np.ndarray,
    fs: float,
    realisation: Realisation | None = None,
    *,
    include_tail: bool = False,
    transfer: DeviceTransfer | None = None,
) -> np.ndarray:
    """Apply the published device's complex transfer to band-limited analysis samples.

    Zero-padded Fourier convolution evaluates H_device(f) at physical frequencies, including
    phase and coefficient quantisation. No analysis-rate biquad is substituted. The input is
    the band-limited reconstruction of the extraction, zero-extended outside the programme;
    this does not recover content removed during extraction. Padding covers at least eight
    seconds and twelve decades of pole decay per section. `include_tail` retains ring-out
    for peak measurement. Unstable devices have no finite waveform and are refused.

    `transfer` is `device_transfer(filters, len(samples), fs, realisation)` when the caller
    has run other signals of the same length through the same cascade; one built for
    something else is refused.
    """
    device = realisation or Realisation()
    if transfer is None:
        transfer = device_transfer(filters, len(samples), fs, device)
        if transfer is None:
            return np.asarray(samples, dtype=float).copy()
    elif (transfer.samples, transfer.fs, transfer.realisation) != (
        len(samples),
        fs,
        device,
    ):
        raise ValueError("transfer was built for another signal length, rate or device")
    guard = transfer.guard
    padded = np.zeros(transfer.size)
    padded[guard : guard + len(samples)] = samples
    corrected = fft.irfft(fft.rfft(padded) * transfer.transfer, n=transfer.size)
    end = guard + len(samples) + (guard if include_tail else 0)
    return corrected[guard:end].copy()


def waveform_peak(samples: np.ndarray) -> float:
    """Peak of the reconstructed waveform, sampled at sixteen times the analysis rate.

    A long Kaiser interpolation kernel preserves the extraction's usable bandwidth. Blocks
    overlap by the kernel support, so their boundaries do not truncate the interpolation.
    Sixteen-fold sampling bounds sinusoidal peak-grid loss at Nyquist to 0.042 dB; dedicated
    device-rate simulations separately exercise multitone/transient peak error. Headroom is
    an output, never an acceptance gate.

    Blocks that provably cannot hold the peak are not interpolated (C4).
    Every interpolated value is a weighted sum of the input samples within the kernel's
    reach, so no block can exceed its largest input sample times the kernel's largest
    polyphase gain. Taking blocks loudest first, a block whose bound is already below the peak
    found is skipped. The answer is bit-identical to interpolating everything: the same
    per-block computation, and a maximum does not depend on order. It was 82% of judging.

    Blocks are about a second long. The bound is loose — the kernel's polyphase gain is 3.02,
    so any block holding a sample within 9.6 dB of the peak must be interpolated — and over a
    65,536-sample block nearly every loud passage has one: 1.84M samples interpolated on
    Caught Stealing against 0.15M at 1,024, and 1.4 s against 0.15 s. Shorter blocks lose
    it again to per-call cost and the kernel overlap each one carries. The block length
    cannot change the answer: each retained sample sees exactly the inputs within the
    kernel's reach, whatever block it falls in.
    """
    factor, half_width, block = 16, 48, 1024
    kernel = signal.firwin(
        2 * half_width * factor + 1, 1 / factor, window=("kaiser", 10)
    )
    # `resample_poly` scales the kernel by `factor`; each output phase uses every
    # `factor`-th tap. A hair of margin for the rounding in the sums it bounds.
    gain = float(
        max(np.sum(np.abs(factor * kernel[p::factor])) for p in range(factor))
    ) * (1.0 + 1e-9)
    spans = []
    for start in range(0, len(samples), block):
        end = min(start + block, len(samples))
        left, right = max(0, start - half_width), min(len(samples), end + half_width)
        reach = float(np.max(np.abs(samples[left:right]))) if right > left else 0.0
        spans.append((reach, start, end, left, right))
    peak = 0.0
    for reach, start, end, left, right in sorted(spans, key=lambda s: -s[0]):
        if reach * gain < peak:
            break
        interpolated = signal.resample_poly(
            samples[left:right], factor, 1, window=kernel
        )
        retained = interpolated[(start - left) * factor : (end - left) * factor]
        peak = max(peak, float(np.max(np.abs(retained))))
    return peak


def house_curve_db(
    freqs: np.ndarray, pivot_hz: float, tilt_db_per_octave: float
) -> np.ndarray:
    """The goal below the knee, in dB re the plateau: 0 at and above `pivot_hz`, then sloping.

    **Positive tilt rises toward the bottom** (the audio convention of
    `AcceptParams.target_tilt_db_per_octave`); negative is a gentle rolloff; zero is flat and
    identically zero. One definition for both halves: the target a strategy builds
    (`pipeline.low_end_deficit_db`) and the shape a result is judged and ranked against
    (`Correction.requested_db`), pivoting at the same point — the top of the judged band.
    """
    freqs = np.asarray(freqs, dtype=float)
    rise = tilt_db_per_octave * np.log2(pivot_hz / np.maximum(freqs, 1e-9))
    return np.where(freqs < pivot_hz, rise, 0.0)


@dataclass(frozen=True, slots=True)
class Correction:
    """What the low end looks like after the filter is applied."""

    freqs: np.ndarray
    before_db: np.ndarray
    after_db: np.ndarray
    band_hz: tuple[float, float]
    signal_domain: str = "analysis_signal"
    playback_model: str | None = None
    playback_before_db: np.ndarray | None = None
    playback_after_db: np.ndarray | None = None
    playback_baseline_db: np.ndarray | None = None
    reference_level_db: float | None = None
    """Raw sub spectra and the unchanged sub-minus-programme baseline, when verified.

    before_db/after_db then describe the sub output relative to that baseline and the
    programme plateau. The crossover is preserved rather than becoming a flattening target.
    These fields are absent on legacy records and ordinary analysis-only measurements."""

    @property
    def spread_db(self) -> float:
        """Peak-to-peak of the corrected curve over the band. Lower is flatter."""
        return float(np.ptp(self._in_band(self.after_db)))

    @property
    def tilt_db_per_octave(self) -> float:
        """Slope of the corrected curve. Positive falls toward the bottom of the band."""
        freqs = self._in_band(self.freqs)
        return float(
            np.polyfit(np.log2(freqs / freqs[0]), self._in_band(self.after_db), 1)[0]
        )

    @property
    def level_db(self) -> float:
        """Mean corrected level over the band, relative to the reference frequency.

        Needed because spread and tilt are both blind to a correction that is uniformly too
        large. Inverting a rolloff as if its corner were 70 Hz when it is 18 leaves the 6-16 Hz
        band *flat* — the inverse is at its plateau there — so the tilt saturates around
        -1.5 dB/oct and the spread barely moves while the level runs away.
        """
        return float(np.mean(self._in_band(self.after_db)))

    def requested_db(self, target_tilt_db_per_octave: float = 0.0) -> np.ndarray:
        """The shape asked for, over the full frequency axis, in dB re the plateau.

        A house curve rising at `target_tilt_db_per_octave` toward the bottom, anchored at 0 dB
        at the *top* of the judged band — the top is where the mix already reaches its plateau,
        so that is the one point a correction should leave alone. Positive tilt rises toward the
        bottom, the audio convention; see `AcceptParams.target_tilt_db_per_octave`.

        Zero tilt gives a flat request, which is what every clause compared against before this
        existed, so `requested_db(0.0)` is identically zero and nothing changes.
        """
        return house_curve_db(self.freqs, self.band_hz[1], target_tilt_db_per_octave)

    def requested_level_db(self, target_tilt_db_per_octave: float = 0.0) -> float:
        """Mean of the requested shape over the judged band — what `level_db` is compared to.

        `target_tilt * octaves / 2` analytically, but taken over the same log-spaced bins the
        measurement uses so the two are commensurate rather than nearly so.
        """
        return float(
            np.mean(self._in_band(self.requested_db(target_tilt_db_per_octave)))
        )

    def intent_db(
        self,
        priced_target_db: np.ndarray | None,
        target_tilt_db_per_octave: float = 0.0,
    ) -> np.ndarray:
        """What the correction was actually asked to achieve (AGENTS.md, "judged against intent").

        `before_db + priced_target_db`. The house curve is *not* added on top: targets are built
        against it (`pipeline.low_end_deficit_db`), so a priced target already carries whatever
        of the goal the evidence licensed, and adding it again would ask for the goal twice.
        `priced_target_db` is on `DESIGN_GRID` and is interpolated onto `self.freqs`.

        `priced_target_db is None` means no strategy built a target for this candidate.
        A caller-supplied cascade may have none; intent then falls back to the house curve
        alone, exactly what every clause compared against before this existed. Treating an absent target as an all-zero one would be
        wrong: zero added to `before_db` is not "no intent", it is "intent to leave the input
        exactly as it was", which is not what a candidate with no target is claiming.
        """
        if priced_target_db is None:
            return self.requested_db(target_tilt_db_per_octave)
        return self.before_db + np.interp(self.freqs, DESIGN_GRID, priced_target_db)

    def intent_level_db(
        self,
        priced_target_db: np.ndarray | None,
        target_tilt_db_per_octave: float = 0.0,
    ) -> float:
        """Mean of `intent_db` over the judged band — what `level_db` is compared to."""
        return float(
            np.mean(
                self._in_band(
                    self.intent_db(priced_target_db, target_tilt_db_per_octave)
                )
            )
        )

    def intent_tilt_db_per_octave(
        self,
        priced_target_db: np.ndarray | None,
        target_tilt_db_per_octave: float = 0.0,
    ) -> float:
        """Slope of `intent_db` over the judged band, same convention as `tilt_db_per_octave`.

        `wanted` used to be the bare dial value; a target that only partially recovers the
        deficit is not flat itself, so its slope has to be measured the same way the corrected
        curve's is (a fit over the band, not a constant) or the two are not comparable.
        """
        freqs = self._in_band(self.freqs)
        intent = self._in_band(
            self.intent_db(priced_target_db, target_tilt_db_per_octave)
        )
        return float(np.polyfit(np.log2(freqs / freqs[0]), intent, 1)[0])

    def departure_db(self, target_tilt_db_per_octave: float = 0.0) -> float:
        """RMS departure of the corrected curve from the shape asked for, over the band.

        For *ranking* accepted candidates, not for judging them — `accept` decides, and a
        scalar that could overrule it would reintroduce the aggregate-blindness R1 exists to
        defeat. Among candidates the model has already passed, the question left is which is
        closest to the shape the pipeline was asked for — `AcceptParams.target_tilt_db_per_octave`,
        which defaults to flat for the reason §3.4a gives: the three human-validated filters track
        `flatten` within 2-4 dB, "flat is the shape; how far past flat to go is the preference dial
        of §4.3".

        One physical quantity in dB rather than a weighted combination of the clauses'
        statistics, which is what makes it comparable without a constant to argue about: level,
        tilt and wobble are all departures from this same line, and this measures all three at
        once in the unit they are already in. Ranking on `wobble_db` alone decided on differences of a
        fraction of a dB in a quantity whose own scatter is several dB, and was blind to level —
        it could prefer a candidate sitting nearly 4 dB above plateau to one a third of a dB
        below it because its wobble was a hair lower. Departure from the requested shape scores
        those two very differently, and correctly.

        Measured against the request rather than against flat, so the ranking cannot quietly
        reimpose flat on a run that asked for a house curve. At 0.0 the two are identical.
        """
        want = self._in_band(self.requested_db(target_tilt_db_per_octave))
        return float(np.sqrt(np.mean((self._in_band(self.after_db) - want) ** 2)))

    @property
    def improvement_db(self) -> float:
        return float(np.ptp(self._in_band(self.before_db))) - self.spread_db

    def _in_band(self, values: np.ndarray) -> np.ndarray:
        return values[(self.freqs >= self.band_hz[0]) & (self.freqs <= self.band_hz[1])]

    def wobble_db(self, values_db: np.ndarray, degree: int = 3) -> float:
        """Peak-to-peak departure of a curve from its own smooth trend over the band.

        The comparable form of `spread_db`. A cascade of shelves and peaking sections is
        smooth in log-frequency, so structure the mean spectrum already carries survives
        correction; what a filter can be held to is the wobble, not the wobble plus a tilt
        that is judged separately.
        """
        octaves = np.log2(self._in_band(self.freqs))
        values = self._in_band(values_db)
        if len(values) <= degree + 1:
            return 0.0
        trend = np.polyval(np.polyfit(octaves, values, degree), octaves)
        return float(np.ptp(values - trend))

    def concerns(
        self,
        params: "AcceptParams | None" = None,
        priced_target_db: np.ndarray | None = None,
    ) -> list[str]:
        """Everything about the corrected result a person would object to on sight.

        A smoke test logged during `verify`, not the acceptance model — `accept` is what
        decides. It nonetheless has to agree with `accept` about what flat means, or it warns
        on answers the model correctly accepts: this took an absolute 6 dB spread limit that
        §6.4 records as sitting exactly on the floor of what a smooth cascade can achieve, and
        the third title's own accepted shape trips it at 6.4 dB. Judged as wobble against the
        material's own, as `accept` does.

        **The thresholds come from `AcceptParams`, not from defaults of its own.** Agreeing
        with a model by keeping a private copy of three of its numbers is agreement that lasts
        until one of them is edited; the previous signature restated `spread_margin_db` 2.0,
        `max_tilt_db` 2.0 and `level_range_db` (-3, 8) as its own parameters, so tuning the
        model would have left this warning on shapes the model accepts — which is the exact
        failure the paragraph above describes, reintroduced by a different route. Imported
        under `TYPE_CHECKING` because `accept` imports `Correction` from here; the default is
        constructed lazily to keep that one-directional.

        **Level and tilt are judged against intent (§14.2), same as `assess`.**
        `priced_target_db` defaults to `None`, which falls back to the house curve exactly as
        this did before intent existed — passing it through is what keeps this agreeing with
        `accept` on a candidate whose target was clipped to less than the full deficit, rather
        than warning on a correction that did exactly what the evidence licensed.
        """
        from beqforge.accept import AcceptParams

        params = params or AcceptParams()
        spread_margin_db = params.spread_margin_db
        wanted = params.target_tilt_db_per_octave
        intent_level = self.intent_level_db(priced_target_db, wanted)
        found: list[str] = []
        if self.level_db > intent_level + params.level_tolerance_db:
            found.append(
                f"corrected low end sits {self.level_db - intent_level:.1f} dB above the "
                "shape asked for — over-corrected"
            )
        if self.level_db < intent_level - params.level_tolerance_db:
            found.append(
                f"corrected low end sits {intent_level - self.level_db:.1f} dB below the "
                "shape asked for — under-corrected"
            )
        wobble = self.wobble_db(self.after_db)
        roughness = self.wobble_db(self.before_db)
        if wobble > roughness + spread_margin_db:
            found.append(
                f"corrected low end is uneven: {wobble:.1f} dB of ripple about its trend over "
                f"{self.band_hz[0]:.0f}-{self.band_hz[1]:.0f} Hz against {roughness:.1f} dB "
                "in the material; expected flat"
            )
        achieved = -self.tilt_db_per_octave
        intent_tilt = -self.intent_tilt_db_per_octave(priced_target_db, wanted)
        if abs(achieved - intent_tilt) > params.tilt_tolerance_db_per_octave:
            found.append(
                f"corrected low end {'rises' if achieved > intent_tilt else 'falls'} at "
                f"{achieved:+.1f} dB/oct against the {intent_tilt:+.1f} intended"
            )
        if self.improvement_db < 0:
            found.append("the correction made the low end less flat than it was")
        return found

    def __str__(self) -> str:
        return (
            f"{np.ptp(self._in_band(self.before_db)):.1f} dB -> {self.spread_db:.1f} dB "
            f"spread, tilt {self.tilt_db_per_octave:+.1f} dB/oct, "
            f"level {self.level_db:+.1f} dB"
        )


@dataclass(frozen=True, slots=True)
class Unfiltered:
    """What `verify` measures before any filter is applied: the same for every candidate.

    The spectrum of the signal being corrected, the spectrum of the reference programme and
    the plateau level read from it — a third of each `verify` call when it was remeasured per
    candidate. Keeps the inputs it was measured from, so `verify` can refuse one measured
    for something else.
    """

    samples: np.ndarray
    fs: float
    diagnose_params: DiagnoseParams
    exclude_bands_hz: tuple[tuple[float, float], ...]
    reference_samples: np.ndarray | None
    freqs: np.ndarray
    before_db: np.ndarray
    source_db: np.ndarray
    reference_db: float


def measure_unfiltered(
    samples: np.ndarray,
    fs: float,
    diagnose_params: DiagnoseParams | None = None,
    exclude_bands_hz: tuple[tuple[float, float], ...] = (),
    reference_samples: np.ndarray | None = None,
) -> Unfiltered:
    """Measure once what every `verify` call on these signals would measure for itself."""
    diagnose_params = diagnose_params or DiagnoseParams()
    freqs, before = _mean_db(samples, fs)
    source = before if reference_samples is None else _mean_db(reference_samples, fs)[1]
    reference_db, _ = plateau_reference(
        source, freqs, diagnose_params, exclude_bands_hz
    )
    return Unfiltered(
        samples,
        fs,
        diagnose_params,
        exclude_bands_hz,
        reference_samples,
        freqs,
        before,
        source,
        reference_db,
    )


def verify(
    filters: list[BiquadSpec],
    samples: np.ndarray,
    fs: float,
    band_hz: tuple[float, float] = (5.0, 45.0),
    diagnose_params: DiagnoseParams | None = None,
    exclude_bands_hz: tuple[tuple[float, float], ...] = (),
    accept_params: "AcceptParams | None" = None,
    realisation: "Realisation | None" = None,
    priced_target_db: np.ndarray | None = None,
    reference_samples: np.ndarray | None = None,
    playback_model: str | None = None,
    log: bool = True,
    unfiltered: Unfiltered | None = None,
    corrected: np.ndarray | None = None,
) -> Correction:
    """Apply the published device response and measure the corrected sub spectrum.

    Use the quantised complex transfer on the extracted waveform, then compare
    before and after against one programme plateau and an unchanged playback
    baseline. The resulting curve feeds the independent acceptance checks.
    `unfiltered` is `measure_unfiltered` of these same arguments, when a caller verifying
    many candidates has it. `corrected` is `device_waveform(filters, samples, fs,
    realisation)`, when the caller has already filtered the waveform — the head of the
    one headroom measures (`include_tail`), which is the same samples; an unstable cascade
    ignores it.
    """
    if any(a <= band_hz[1] and b >= band_hz[0] for a, b in exclude_bands_hz):
        raise ValueError(
            "exclusions fragment the judged band; contiguous verification unavailable"
        )
    if reference_samples is not None:
        if len(reference_samples) != len(samples):
            raise ValueError(
                "playback and reference signals must have identical sample alignment"
            )
        if not np.any(samples):
            raise ValueError("playback verification unavailable: silent sub feed")
    filters = publication_filters(filters)
    device = realisation or Realisation()
    if unfiltered is None:
        unfiltered = measure_unfiltered(
            samples, fs, diagnose_params, exclude_bands_hz, reference_samples
        )
    elif not (
        unfiltered.samples is samples
        and unfiltered.reference_samples is reference_samples
        and unfiltered.fs == fs
        and unfiltered.diagnose_params == (diagnose_params or DiagnoseParams())
        and unfiltered.exclude_bands_hz == exclude_bands_hz
    ):
        raise ValueError("unfiltered spectra were measured for different signals")
    freqs, before = unfiltered.freqs, unfiltered.before_db
    if filters and unstable_sections(filters, device):
        # Keep the fitter's unstable fallback reviewable; assess rejects exact Jury failure.
        after = before + magnitude_db(
            device.quantise(biquad_sos(filters, device.fs)), freqs, device.fs
        )
    else:
        if corrected is None:
            corrected = device_waveform(filters, samples, fs, device)
        elif len(corrected) != len(samples):
            raise ValueError("corrected waveform must align with the samples")
        _, after = _mean_db(corrected, fs)
    source = unfiltered.source_db
    baseline = np.zeros_like(before) if reference_samples is None else before - source
    reference_db = unfiltered.reference_db

    if not np.isfinite(reference_db):
        raise ValueError("no usable contiguous mix plateau")

    keep = np.ones_like(freqs, dtype=bool)
    for low, high in exclude_bands_hz:
        keep &= ~((freqs >= low) & (freqs <= high))
    correction = Correction(
        freqs=freqs[keep],
        before_db=(before - baseline - reference_db)[keep],
        after_db=(after - baseline - reference_db)[keep],
        signal_domain="sub_output_relative_to_playback"
        if reference_samples is not None
        else "analysis_signal",
        playback_model=playback_model,
        playback_before_db=before[keep] if reference_samples is not None else None,
        playback_after_db=after[keep] if reference_samples is not None else None,
        playback_baseline_db=baseline[keep] if reference_samples is not None else None,
        reference_level_db=reference_db,
        band_hz=band_hz,
    )
    if log:
        logger.info(f"Applied correction: {correction}")
        for concern in correction.concerns(accept_params, priced_target_db):
            logger.warning(f"Correction concern: {concern}")
    return correction


def _mean_db(samples: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Measure the waveform's Welch mean spectrum for before/after comparison."""
    freqs, power = signal.welch(samples, fs=fs, nperseg=4096, noverlap=2048)
    keep = freqs > 0
    return freqs[keep], 10.0 * np.log10(power[keep] + 1e-300)
