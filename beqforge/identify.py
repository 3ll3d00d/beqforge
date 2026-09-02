"""Separating the rolloff from the content it sits in — AUTOMATED_DESIGN.md §3.5-§3.6.

Fits `E(f) = N(f) + A(f)`: a smooth natural envelope plus the soft-hinge attenuation of
`rolloff.py`. `N` is what film bass content does on its own; `A` is what was done to it.

`N`'s flexibility *is* the detector, which is why it is a low-order polynomial in log-frequency
and not something more accommodating. Too flexible and it absorbs the rolloff, giving a false
negative; too rigid and it manufactures one, giving the false positive §2.3 calls the expensive
failure. The order is a stated choice, not a fitted one, and it is the largest remaining source
of uncertainty in the whole pipeline (§10).

Detection is the model comparison of §3.6 — does `N + A` explain the envelope enough better
than `N` alone to be worth believing — reported as a margin, never as a threshold passed.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np
from scipy import optimize

from beqanalyser.design import HighPass
from beqanalyser.design.extraction import Envelopes
from beqanalyser.design.rolloff import (
    DB_PER_OCTAVE_PER_ORDER,
    RolloffFit,
    attenuation_db,
    identify,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IdentifyParams:
    """Choices the identification makes. Each is a prior until a corpus settles it (§10)."""

    fit_band_hz: tuple[float, float] = (5.0, 60.0)
    """Band the two-part model is fitted over.

    Narrow, and that is the whole point. `N` and `A` overlap in function space, and how badly
    depends on how many octaves `N` gets to curve over: across 5-300 Hz a quadratic absorbs
    all but ~1 dB of a 2nd-order rolloff and the estimate is unstable, while across 5-60 Hz
    the same fit moves the corner by 0.5 Hz between a linear and a quadratic `N`. The
    identifiability problem is largely an artefact of fitting too wide a band.

    60 Hz is also roughly where a human stops looking when reading a bass rolloff off a
    spectrum, which is not a coincidence: above it there is nothing to learn about the corner
    and plenty of content for `N` to chase."""

    exclude_bands_hz: tuple[tuple[float, float], ...] = ()
    """Bands to drop before fitting, for narrow authored features that are content, not shape.

    The first real title carries a +14 dB feature about a third of an octave wide at 20 Hz in
    its LFE channel. It is not a rolloff and it is not natural envelope; a robust loss does not
    reject it because it is too broad to look like an outlier, and left in it drags the corner
    from 13 Hz to 20."""

    envelope_order: int = 1
    """Polynomial order of `N(f)` in log-frequency.

    Linear over the fitted band. Higher orders no longer change the answer much once the band
    is narrow, so the lower order is taken for the tighter prior it represents."""

    min_coherence: float = 0.1
    """Below this a bin carries no event-related content and gets no weight (§3.4)."""

    corner_bounds_hz: tuple[float, float] = (4.0, 120.0)
    """Full plausible range, not a catalogue-derived window (§2.1)."""


@dataclass(frozen=True, slots=True)
class Identification:
    """What was found, and how much of it to believe."""

    fit: RolloffFit
    rolloff: HighPass | None
    """The named high-pass, or None when the shape matches no representable alignment."""

    improvement_db: float
    """How much better `N + A` fits than `N` alone, as a reduction in RMS residual."""

    smooth_residual_db: float
    """RMS residual of the smooth-only model. The comparison's denominator."""

    weighted_bins: int
    coherent_bandwidth_octaves: float

    @property
    def detected(self) -> bool:
        """Whether an attenuation is present at all — not whether it is *identified*."""
        return self.improvement_db > 0.0 and self.fit.slope_db_per_octave > 1.0

    def __str__(self) -> str:
        named = str(self.rolloff) if self.rolloff else "no representable alignment"
        return (
            f"fc {self.fit.corner_hz:.1f} Hz, slope "
            f"{self.fit.slope_db_per_octave:.1f} dB/oct (order "
            f"{self.fit.implied_order:.2f}), knee {self.fit.knee:.2f} -> {named}; "
            f"model improvement {self.improvement_db:.2f} dB on "
            f"{self.smooth_residual_db:.2f} dB, {self.coherent_bandwidth_octaves:.1f} "
            f"coherent octaves"
        )


def identify_rolloff(
    envelopes: Envelopes, params: IdentifyParams | None = None
) -> Identification:
    """Fit `N + A` to the extracted envelope and compare it against `N` alone."""
    params = params or IdentifyParams()
    freqs, values, weights = _fit_inputs(envelopes, params)
    if len(freqs) < 3 * (params.envelope_order + 4):
        raise ValueError(
            f"only {len(freqs)} usable bins in "
            f"{params.fit_band_hz[0]:.0f}-{params.fit_band_hz[1]:.0f} Hz; nothing to fit"
        )

    log_f = np.log2(freqs / freqs[0])
    smooth_residual = _rms(_fit_smooth(log_f, values, weights) - values, weights)
    fit, model = _fit_two_part(log_f, freqs, values, weights, params)
    combined_residual = _rms(model - values, weights)

    coherent = envelopes.freqs[envelopes.coherence >= params.min_coherence]
    octaves = math.log2(coherent.max() / coherent.min()) if len(coherent) > 1 else 0.0
    identification = Identification(
        fit=fit,
        rolloff=identify(fit),
        improvement_db=float(smooth_residual - combined_residual),
        smooth_residual_db=float(smooth_residual),
        weighted_bins=len(freqs),
        coherent_bandwidth_octaves=octaves,
    )
    logger.info(f"Identified {identification}")
    return identification


def _fit_inputs(
    envelopes: Envelopes, params: IdentifyParams
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bins worth fitting, and how much each is worth.

    Weighting is the coherence of §3.4 rather than any absolute noise-floor threshold: where
    coherence collapses the weight goes to zero on its own.
    """
    band = (envelopes.freqs >= params.fit_band_hz[0]) & (
        envelopes.freqs <= params.fit_band_hz[1]
    )
    for low, high in params.exclude_bands_hz:
        band &= ~((envelopes.freqs >= low) & (envelopes.freqs <= high))
    return (
        envelopes.freqs[band],
        envelopes.mean_db[band],
        np.ones(int(band.sum())),
    )


def _rms(residual: np.ndarray, weights: np.ndarray) -> float:
    return float(np.sqrt(np.sum(weights * residual**2) / np.sum(weights)))


def _design_matrix(log_f: np.ndarray, order: int) -> np.ndarray:
    return np.vander(log_f, order + 1, increasing=True)


def _fit_smooth(
    log_f: np.ndarray, values: np.ndarray, weights: np.ndarray
) -> np.ndarray:
    """Best smooth-only explanation of the envelope — the null model of §3.6."""
    return _weighted_lstsq(_design_matrix(log_f, 2), values, weights)


def _weighted_lstsq(
    design: np.ndarray, values: np.ndarray, weights: np.ndarray
) -> np.ndarray:
    root = np.sqrt(weights)[:, None]
    coefficients, *_ = np.linalg.lstsq(design * root, values * root[:, 0], rcond=None)
    return design @ coefficients


def _fit_two_part(
    log_f: np.ndarray,
    freqs: np.ndarray,
    values: np.ndarray,
    weights: np.ndarray,
    params: IdentifyParams,
) -> tuple[RolloffFit, np.ndarray]:
    """Fit `N + A` together under a robust loss.

    Robust because real content is not smooth. The first title tried carries a narrow ~+8 dB
    resonance at 20 Hz, about a third of an octave wide, sitting on an otherwise unremarkable
    envelope. A low-order `N` cannot represent a feature that narrow, so under least squares
    the attenuation term absorbs it: the corner is dragged up to 18.5 Hz and the knee pegs at
    its bound, sharper than any physical filter. A soft-L1 loss treats the resonance as the
    outlier it is and leaves the broad shape to be measured.

    All parameters are fitted jointly, from several starts, because `N` and `A` trade against
    each other and a single descent finds whichever local minimum it started nearest.
    """
    design = _design_matrix(log_f, params.envelope_order)
    root = np.sqrt(weights)

    def residuals(p: np.ndarray) -> np.ndarray:
        attenuation = attenuation_db(freqs, math.exp(p[0]), p[1], math.exp(p[2]))
        model = design @ p[3:] + attenuation
        return root * (model - values)

    lower = [math.log(params.corner_bounds_hz[0]), 0.0, math.log(0.25)]
    upper = [math.log(params.corner_bounds_hz[1]), 120.0, math.log(64.0)]
    envelope_start = np.linalg.lstsq(design, values, rcond=None)[0]

    best: optimize.OptimizeResult | None = None
    for corner_guess in (8.0, 15.0, 25.0, 45.0):
        for order_guess in (1.0, 2.0, 4.0, 8.0):
            start = np.concatenate(
                [
                    [
                        math.log(corner_guess),
                        order_guess * DB_PER_OCTAVE_PER_ORDER,
                        math.log(order_guess * 2.0),
                    ],
                    envelope_start,
                ]
            )
            found = optimize.least_squares(
                residuals,
                start,
                bounds=(
                    lower + [-np.inf] * design.shape[1],
                    upper + [np.inf] * design.shape[1],
                ),
                loss="soft_l1",
                f_scale=1.0,
            )
            if best is None or found.cost < best.cost:
                best = found
    assert best is not None

    corner, slope, knee = math.exp(best.x[0]), float(best.x[1]), math.exp(best.x[2])
    model = values + residuals(best.x) / np.where(root > 0, root, 1.0)
    return RolloffFit(corner, slope, knee, _rms(model - values, weights)), model
