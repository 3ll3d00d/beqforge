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

    def concerns(
        self,
        max_spread_db: float = 6.0,
        max_tilt_db: float = 2.0,
        level_range_db: tuple[float, float] = (-3.0, 8.0),
    ) -> list[str]:
        """Everything about the corrected result a person would object to on sight.

        `level_range_db` encodes "flat, or mildly rising at the bottom": the corrected low end
        should sit near the reference, a little above it at most.
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
        if self.spread_db > max_spread_db:
            found.append(
                f"corrected low end spans {self.spread_db:.1f} dB over "
                f"{self.band_hz[0]:.0f}-{self.band_hz[1]:.0f} Hz; expected flat"
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
    band_hz: tuple[float, float] = (5.0, 16.0),
    reference_hz: float = 40.0,
) -> Correction:
    """Apply `filters` to `samples` and measure the corrected low end.

    The band deliberately stops below any authored emphasis — a hump at 20 Hz is content and
    correcting it is not the job, so including it would penalise a correct filter.
    """
    corrected = signal.sosfilt(biquad_sos(filters, fs), samples)
    freqs, before = _mean_db(samples, fs)
    _, after = _mean_db(corrected, fs)
    anchor = int(np.argmin(np.abs(freqs - reference_hz)))

    correction = Correction(
        freqs=freqs,
        before_db=before - before[anchor],
        after_db=after - after[anchor],
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
