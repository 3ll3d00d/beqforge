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
from dataclasses import dataclass

import numpy as np
from scipy import signal

from beqanalyser.design import BiquadSpec
from beqanalyser.design.filters import biquad_sos

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Correction:
    """What the low end looks like after the filter is applied."""

    freqs: np.ndarray
    before_db: np.ndarray
    after_db: np.ndarray
    band_hz: tuple[float, float]

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
        spread_margin_db: float = 2.0,
        max_tilt_db: float = 2.0,
        level_range_db: tuple[float, float] = (-3.0, 8.0),
    ) -> list[str]:
        """Everything about the corrected result a person would object to on sight.

        `level_range_db` encodes "flat, or mildly rising at the bottom": the corrected low end
        should sit near the reference, a little above it at most.

        A smoke test logged during `verify`, not the acceptance model — `accept` is what
        decides. It nonetheless has to agree with `accept` about what flat means, or it warns
        on answers the model correctly accepts: this took an absolute 6 dB spread limit that
        §6.4 records as sitting exactly on the floor of what a smooth cascade can achieve, and
        the third title's own accepted shape trips it at 6.4 dB. Judged as wobble against the
        material's own, as `accept` does.
        """
        found: list[str] = []
        if self.level_db > level_range_db[1]:
            found.append(
                f"corrected low end sits {self.level_db:.1f} dB above the reference — "
                "over-corrected"
            )
        if self.level_db < level_range_db[0]:
            found.append(
                f"corrected low end sits {-self.level_db:.1f} dB below the reference — "
                "under-corrected"
            )
        wobble = self.wobble_db(self.after_db)
        roughness = self.wobble_db(self.before_db)
        if wobble > roughness + spread_margin_db:
            found.append(
                f"corrected low end wobbles {wobble:.1f} dB over "
                f"{self.band_hz[0]:.0f}-{self.band_hz[1]:.0f} Hz against {roughness:.1f} dB "
                "in the material; expected flat"
            )
        if self.tilt_db_per_octave > max_tilt_db:
            found.append(
                f"corrected low end still falls at {self.tilt_db_per_octave:.1f} dB/oct "
                "toward the bottom — under-corrected"
            )
        if self.tilt_db_per_octave < -max_tilt_db:
            found.append(
                f"corrected low end rises at {-self.tilt_db_per_octave:.1f} dB/oct "
                "toward the bottom — over-corrected"
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
    reference_hz: float = 40.0,
    exclude_bands_hz: tuple[tuple[float, float], ...] = (),
) -> Correction:
    """Apply `filters` to `samples` and measure the corrected low end.

    The band has to be wide enough to see a slope. An earlier default of 5-16 Hz was not: two
    designs measured +0.17 and +0.05 dB/octave there and looked identical in shape, while over
    5-45 Hz they separate to -1.17 and +0.10 — one rising into the bottom, the other flat. A
    window narrower than the shape being judged reads a step as a slope and a slope as nothing.

    `exclude_bands_hz` drops authored emphasis, which is content: correcting a hump at 20 Hz is
    not the job and including it would penalise a correct filter.
    """
    corrected = signal.sosfilt(biquad_sos(filters, fs), samples)
    freqs, before = _mean_db(samples, fs)
    _, after = _mean_db(corrected, fs)
    anchor = int(np.argmin(np.abs(freqs - reference_hz)))

    keep = np.ones_like(freqs, dtype=bool)
    for low, high in exclude_bands_hz:
        keep &= ~((freqs >= low) & (freqs <= high))
    correction = Correction(
        freqs=freqs[keep],
        before_db=(before - before[anchor])[keep],
        after_db=(after - after[anchor])[keep],
        band_hz=band_hz,
    )
    logger.info(f"Applied correction: {correction}")
    for concern in correction.concerns():
        logger.warning(f"Correction concern: {concern}")
    return correction


def _mean_db(samples: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    freqs, power = signal.welch(samples, fs=fs, nperseg=4096, noverlap=2048)
    keep = freqs > 0
    return freqs[keep], 10.0 * np.log10(power[keep] + 1e-300)
