"""The parametric rolloff model.

Attenuation as a soft hinge in log-frequency/dB: flat above the corner, a straight line of
`slope` dB/octave below it, with `knee` controlling how abruptly the two meet.

    A(f) = -(slope / knee) * log2(1 + (fc / f) ** knee)

The three parameters are not arbitrary. Writing a Butterworth high-pass of order M in dB gives
`-10 * log10(1 + (fc/f)**(2M))`, which is this form exactly at `knee = 2M` and
`slope = 6.02M`. A Linkwitz-Riley of order M is Butterworth of order M/2 squared, which is the
same form at `knee = M` and the same slope. So the model reproduces both families exactly, and
`knee` — not slope — is what separates them: at a given order, Butterworth has twice the knee
of Linkwitz-Riley. `fc` recovers the design corner in both cases, at -3 dB and -6 dB
respectively.

That is the answer to the question §3.5 posed: a free-slope fit does not merely approximate a
real high-pass, it identifies one, alignment included. See `identify`.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np
from scipy import optimize

from beqforge import Alignment, HighPass

logger = logging.getLogger(__name__)

DB_PER_OCTAVE_PER_ORDER = 20.0 * math.log10(2.0)
"""6.0206 dB/octave per filter order — the asymptotic slope of any high-pass."""

_KNEE_PER_ORDER = {Alignment.BUTTERWORTH: 2.0, Alignment.LINKWITZ_RILEY: 1.0}
"""Knee sharpness per order, for the alignments the model reproduces exactly."""


@dataclass(frozen=True, slots=True)
class RolloffFit:
    """A fitted rolloff and how well it described the data."""

    corner_hz: float
    slope_db_per_octave: float
    knee: float
    residual_db: float
    """Maximum absolute error in dB over the band that was fitted."""

    @property
    def implied_order(self) -> float:
        """Filter order implied by the slope. Not rounded — the fractional part is evidence."""
        return self.slope_db_per_octave / DB_PER_OCTAVE_PER_ORDER


def attenuation_db(
    freqs: np.ndarray, corner_hz: float, slope_db_per_octave: float, knee: float
) -> np.ndarray:
    """The soft-hinge attenuation, 0 dB well above `corner_hz` and negative below."""
    ratio = np.asarray(freqs, dtype=np.float64) / corner_hz
    # log1p(exp(x)) form keeps this finite when (fc/f)**knee overflows at low frequency
    exponent = -knee * np.log(ratio)
    return -(slope_db_per_octave / knee) * np.logaddexp(0.0, exponent) / math.log(2.0)


def fit_rolloff(
    magnitude_db: np.ndarray,
    freqs: np.ndarray,
    band_hz: tuple[float, float] | None = None,
    corner_bounds_hz: tuple[float, float] = (4.0, 120.0),
) -> RolloffFit:
    """Estimate corner, asymptotic slope and knee width of attenuation.

    Fit the soft-hinge response from several bounded starting points and keep
    the lowest residual. These parameters describe a possible parametric inverse.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    mask = (
        np.ones_like(freqs, dtype=bool)
        if band_hz is None
        else (freqs >= band_hz[0]) & (freqs <= band_hz[1])
    )
    fitted_freqs = freqs[mask]
    fitted_db = np.asarray(magnitude_db, dtype=np.float64)[mask]

    def residuals(p: np.ndarray) -> np.ndarray:
        corner, slope, knee = math.exp(p[0]), p[1], math.exp(p[2])
        return attenuation_db(fitted_freqs, corner, slope, knee) - fitted_db

    best: optimize.OptimizeResult | None = None
    for corner_guess in (10.0, 20.0, 40.0):
        for order_guess in (2.0, 4.0, 8.0):
            start = np.array(
                [
                    math.log(corner_guess),
                    order_guess * DB_PER_OCTAVE_PER_ORDER,
                    math.log(order_guess),
                ]
            )
            found = optimize.least_squares(
                residuals,
                start,
                bounds=(
                    [math.log(corner_bounds_hz[0]), 1.0, math.log(0.25)],
                    [math.log(corner_bounds_hz[1]), 120.0, math.log(64.0)],
                ),
            )
            if best is None or found.cost < best.cost:
                best = found
    assert best is not None

    corner, slope, knee = math.exp(best.x[0]), float(best.x[1]), math.exp(best.x[2])
    error = float(np.max(np.abs(residuals(best.x))))
    return RolloffFit(corner, slope, knee, error)


def identify(
    fit: RolloffFit,
    order_tolerance: float = 0.1,
    knee_tolerance: float = 0.1,
    max_residual_db: float | None = None,
) -> HighPass | None:
    """Recognise a fitted Butterworth or Linkwitz-Riley high-pass.

    Match implied order and knee to a named alignment within tolerance; require
    the optional residual limit when supplied. Unknown shapes cannot take the
    closed-form shelf inversion path.
    """
    if max_residual_db is not None and fit.residual_db > max_residual_db:
        return None
    order = round(fit.implied_order)
    if order < 1 or abs(fit.implied_order - order) > order_tolerance:
        return None
    for alignment, knee_per_order in _KNEE_PER_ORDER.items():
        expected = knee_per_order * order
        if abs(fit.knee - expected) <= knee_tolerance * expected:
            if alignment.is_linkwitz_riley and order % 2:
                continue
            return HighPass(alignment, order, fit.corner_hz)
    return None
