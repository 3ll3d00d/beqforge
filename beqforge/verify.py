"""Applying a design and measuring what it did — AUTOMATED_DESIGN.md §6.2.

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

from beqanalyser.design import DESIGN_GRID, BiquadSpec
from beqanalyser.design.diagnose import DiagnoseParams, plateau_reference
from beqanalyser.design.filters import (
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
    from beqanalyser.design.accept import AcceptParams


def device_error_db(
    filters: list[BiquadSpec], freqs: np.ndarray, realisation: Realisation
) -> np.ndarray:
    """dB the device's own coefficient rounding adds, on `freqs`.

    The device takes coefficients and stores them in its own format, so the response it realises
    is not the one the optimiser produced. Measured at the device's rate, where the rounding
    happens, then resampled onto the analysis axis.

    Measured across the eight titles this runs 0.08 to 1.41 dB. Two things worth knowing about
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


def device_waveform(
    filters: list[BiquadSpec],
    samples: np.ndarray,
    fs: float,
    realisation: Realisation | None = None,
    *,
    include_tail: bool = False,
) -> np.ndarray:
    """Apply the published device's complex transfer to band-limited analysis samples.

    Zero-padded Fourier convolution evaluates H_device(f) at physical frequencies, including
    phase and coefficient quantisation. No analysis-rate biquad is substituted. The input is
    the band-limited reconstruction of the extraction, zero-extended outside the programme;
    this does not recover content removed during extraction. Padding covers at least eight
    seconds and twelve decades of pole decay per section. `include_tail` retains ring-out
    for peak measurement. Unstable devices have no finite waveform and are refused.
    """
    device = realisation or Realisation()
    filters = publication_filters(filters)
    if not filters:
        return np.asarray(samples, dtype=float).copy()
    if device.fs < fs:
        raise ValueError("device rate must cover the analysis bandwidth")
    if unstable_sections(filters, device):
        raise ValueError(
            "unstable published device has no finite verification waveform"
        )
    sos = device.quantise(biquad_sos(filters, device.fs))
    radius = max(float(np.max(np.abs(np.roots(row[3:])))) for row in sos)
    decay = 0.0 if radius == 0 else -math.log(1e-12) / -math.log(radius)
    guard = max(
        int(math.ceil(8 * fs)), int(math.ceil(decay * len(sos) * fs / device.fs))
    )
    size = fft.next_fast_len(len(samples) + 2 * guard)
    padded = np.zeros(size)
    padded[guard : guard + len(samples)] = samples
    freqs = fft.rfftfreq(size, 1 / fs)
    _, transfer = signal.freqz_sos(sos, worN=freqs, fs=device.fs)
    corrected = fft.irfft(fft.rfft(padded) * transfer, n=size)
    end = guard + len(samples) + (guard if include_tail else 0)
    return corrected[guard:end].copy()


def waveform_peak(samples: np.ndarray) -> float:
    """Peak of the reconstructed waveform, sampled at sixteen times the analysis rate.

    A long Kaiser interpolation kernel preserves the extraction's usable bandwidth. Blocks
    overlap by the kernel support, so their boundaries do not truncate the interpolation.
    Sixteen-fold sampling bounds sinusoidal peak-grid loss at Nyquist to 0.042 dB; dedicated
    device-rate simulations separately exercise multitone/transient peak error. Headroom is
    an output, never an acceptance gate.
    """
    factor, half_width, block = 16, 48, 65536
    kernel = signal.firwin(
        2 * half_width * factor + 1, 1 / factor, window=("kaiser", 10)
    )
    peak = 0.0
    for start in range(0, len(samples), block):
        end = min(start + block, len(samples))
        left, right = max(0, start - half_width), min(len(samples), end + half_width)
        interpolated = signal.resample_poly(
            samples[left:right], factor, 1, window=kernel
        )
        retained = interpolated[(start - left) * factor : (end - left) * factor]
        peak = max(peak, float(np.max(np.abs(retained))))
    return peak


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
        top = self.band_hz[1]
        rise = target_tilt_db_per_octave * np.log2(top / np.maximum(self.freqs, 1e-9))
        return np.where(self.freqs < top, rise, 0.0)

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
        """What the correction was actually asked to achieve — AUTOMATED_DESIGN.md §14.2.

        `before_db + priced_target_db`, plus the house curve on top of it (inert while
        nothing builds a house curve into a target — `target_tilt_db_per_octave` defaults to
        0.0 and `priced_by_evidence` never adds one — but stated once here rather than left to
        be got right twice when §14.4 wires it in). `priced_target_db` is on `DESIGN_GRID` and
        is interpolated onto `self.freqs`.

        `priced_target_db is None` means no strategy built a target for this candidate.
        A caller-supplied cascade may have none; intent then falls back to the house curve
        alone, exactly what every clause compared against before this existed. Treating an absent target as an all-zero one would be
        wrong: zero added to `before_db` is not "no intent", it is "intent to leave the input
        exactly as it was", which is not what a candidate with no target is claiming.
        """
        house = self.requested_db(target_tilt_db_per_octave)
        if priced_target_db is None:
            return house
        return (
            self.before_db
            + np.interp(self.freqs, DESIGN_GRID, priced_target_db)
            + house
        )

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
        once in the unit they are already in. Ranking on `wobble_db` alone decided on 0.08-0.23
        dB of a quantity whose own scatter is 3-14 dB, and was blind to level — on title 3 it
        preferred a candidate sitting +3.70 dB above plateau to one at -0.36 because its wobble
        was 0.09 dB lower. The same two score 4.27 and 1.54 here.

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
        from beqanalyser.design.accept import AcceptParams

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
                f"corrected low end wobbles {wobble:.1f} dB over "
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
) -> Correction:
    """Apply `filters` to `samples` and measure the corrected low end.

    The band has to be wide enough to see a slope. An earlier default of 5-16 Hz was not: two
    designs measured +0.17 and +0.05 dB/octave there and looked identical in shape, while over
    5-45 Hz they separate to -1.17 and +0.10 — one rising into the bottom, the other flat. A
    window narrower than the shape being judged reads a step as a slope and a slope as nothing.

    `exclude_bands_hz` drops authored emphasis, which is content: correcting a hump at 20 Hz is
    not the job and including it would penalise a correct filter.

    The reference used to be a single fixed point, `before`/`after` each anchored to their own
    value at 40 Hz — AUTOMATED_DESIGN.md §6.2 already named this "should be derived, not
    defaulted" and it stayed defaulted regardless. On Predator that single point sits on the
    shoulder of a local bump 1.7-2.3 dB above the mix's own plateau, which read as `level_db`
    running 4 dB under reference when the corrected curve was in fact flat within 2 dB of it —
    a shape that passed R1 everywhere else and failed only because the ruler had a bump in it.
    `plateau_reference` is the fix already used for exactly this on `flatten`'s own target and
    on every per-channel reference in `diagnose`; verification judging the result by a
    different rule than construction judged the target was the gap, not two separate bugs.
    One reference, from `before` alone so a filter cannot move its own goalposts, applied to
    both curves so what's compared is how far `after` closed on where `before` already stood.

    With `reference_samples`, `samples` is the post-bass-management sub feed and the reference
    is the aligned full-band programme used to construct targets. The fixed baseline is
    PSD(sub_before) - PSD(programme_before), measured before correction: it includes the
    model's crossover and coherent channel sum, not a target or fitted cascade. Sub spectra
    are judged relative to this unchanged baseline and the programme's own plateau. Thus
    independent wrong-filter checks retain the same house/material meaning, and a crossover
    does not become a deficit. Raw playback spectra and the baseline remain in Correction.
    This describes the sub output, not the combined sub-plus-mains acoustic response.

    The corrected waveform uses the device-rate complex response, including publication
    rounding and coefficient quantisation, on the band-limited extracted signal. Magnitude
    and phase therefore include the full rate difference. An unstable publication retains
    only a frequency-response diagnostic for rejection; it has no finite waveform/headroom.

    `priced_target_db` is the evidence-priced target the fitter was handed, if any (§14.2) — on
    `DESIGN_GRID`, `None` for a caller-supplied candidate with no target. Only reaches
    `Correction.concerns`'s smoke test here; `assess` takes it directly.
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
    freqs, before = _mean_db(samples, fs)
    if filters and unstable_sections(filters, device):
        # Keep the fitter's unstable fallback reviewable; assess rejects exact Jury failure.
        after = before + magnitude_db(
            device.quantise(biquad_sos(filters, device.fs)), freqs, device.fs
        )
    else:
        corrected = device_waveform(filters, samples, fs, device)
        _, after = _mean_db(corrected, fs)
    source = before if reference_samples is None else _mean_db(reference_samples, fs)[1]
    baseline = np.zeros_like(before) if reference_samples is None else before - source
    reference_db, _ = plateau_reference(
        source, freqs, diagnose_params or DiagnoseParams(), exclude_bands_hz
    )

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
    logger.info(f"Applied correction: {correction}")
    for concern in correction.concerns(accept_params, priced_target_db):
        logger.warning(f"Correction concern: {concern}")
    return correction


def _mean_db(samples: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    freqs, power = signal.welch(samples, fs=fs, nperseg=4096, noverlap=2048)
    keep = freqs > 0
    return freqs[keep], 10.0 * np.log10(power[keep] + 1e-300)
