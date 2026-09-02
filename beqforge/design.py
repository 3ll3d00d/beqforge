"""Turning an identified rolloff into a publishable filter — AUTOMATED_DESIGN.md §4-§5.

Inversion is preference (§1): identification says what was done, this says how far to undo it
and exposes the choices as dials rather than making them silently.

Two routes, matching the contract's `method`:

* `exact` — the rolloff was identified as a named alignment, so the protective filter is given
  the same alignment and the published cascade *is* the inverse, in closed form (§5).
* `fitted` — an attenuation was measured but matches no representable alignment, so the target
  is built from the fitted curve and approximated numerically. Weaker claim, and the residual
  says how much weaker.
"""

import logging
import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from beqanalyser.design import BiquadSpec, ExactInversionUnavailable, HighPass
from beqanalyser.design.extraction import Envelopes
from beqanalyser.design.filters import (
    Realisation,
    biquad_sos,
    correction_band_hz,
    fit_minimal_biquads,
    high_pass_sos,
    inversion_target_db,
    invert_to_shelves,
    magnitude_db,
    residual_db,
)
from beqanalyser.design.identify import Identification
from beqanalyser.design.rolloff import attenuation_db

logger = logging.getLogger(__name__)

DesignMethod = Literal["exact", "fitted", "non_parametric"]
PUBLISH_FS = 48000.0
"""Rate the cascade is realised at for measuring its own residual. Not published (§5)."""


@dataclass(frozen=True, slots=True)
class DesignParams:
    """The dials of §4.3. This is where preference lives, and the only place it should."""

    max_boost_db: float = 20.0
    """Absolute cap on the correction. Sets the protective filter's corner."""

    residual_target_db: float = 0.5
    """Accuracy the published cascade must reach against its target.

    Sections are spent until this is met, then no more. Under-spending shows up here as a
    residual that misses; over-spending would otherwise show up nowhere at all."""

    noise_margin_db: float = 12.0
    """How far boosted noise must stay below the content that masks it (§4.1)."""

    lowest_frequency_hz: float = 5.0
    """Lowest frequency worth restoring."""

    max_sections: int = 6
    """Ceiling on biquads the numerical route may spend. The device budget is 10 (§5)."""

    realisation: Realisation | None = Realisation()
    """How the cascade will actually be realised, scored during the fit.

    On by default. Fitting in float64 alone accepts cascades built from large opposing
    sections that cancel; on the target device the cancellation does not survive coefficient
    quantisation. Measured on this pipeline's own output at 96 kHz in 5.23 fixed point, the
    drift falls from 0.98 dB to 0.19 dB for no meaningful loss of accuracy."""


@dataclass(frozen=True, slots=True)
class Design:
    """A filter, or the reason there isn't one."""

    filters: list[BiquadSpec] | None
    method: DesignMethod | None
    mv_adjust_db: float | None
    residual_db: float | None
    residual_band_hz: tuple[float, float] | None
    rolloff: HighPass | None
    protect: HighPass | None
    noise_ceiling_binds: bool
    decline_reason: str | None = None
    decline_message: str | None = None

    @property
    def declined(self) -> bool:
        return self.filters is None


def design(
    identification: Identification,
    envelopes: Envelopes,
    params: DesignParams | None = None,
) -> Design:
    """Invert an identified rolloff into a publishable cascade."""
    params = params or DesignParams()
    fit = identification.fit

    if not identification.detected:
        return _decline(
            "no_rolloff_detected",
            "No attenuation distinguishable from the natural envelope.",
        )

    protect_corner = fit.corner_hz / 10.0 ** (
        params.max_boost_db / (20.0 * max(fit.implied_order, 0.5))
    )
    protect_corner = max(protect_corner, params.lowest_frequency_hz)
    binds, ceiling_db = _noise_ceiling(envelopes, fit, params)

    if identification.rolloff is not None:
        protect = HighPass(
            identification.rolloff.alignment,
            identification.rolloff.order,
            protect_corner,
        )
        try:
            filters = invert_to_shelves(identification.rolloff, protect)
            freqs = np.logspace(math.log10(3.0), math.log10(400.0), 400)
            target = inversion_target_db(
                identification.rolloff, protect, freqs, PUBLISH_FS
            )
            return _result(
                filters,
                "exact",
                identification.rolloff,
                protect,
                freqs,
                target,
                params,
                binds,
            )
        except ExactInversionUnavailable as unavailable:
            logger.info(f"Closed form unavailable ({unavailable}); fitting instead")

    freqs = np.logspace(math.log10(3.0), math.log10(400.0), 400)
    target = _fitted_target(freqs, fit, protect_corner, params, ceiling_db, envelopes)
    filters, _ = fit_minimal_biquads(
        target,
        freqs,
        PUBLISH_FS,
        params.max_sections,
        params.residual_target_db,
        band_hz=(5.0, 200.0),
        placement_band_hz=correction_band_hz(target, freqs),
        realisation=params.realisation,
    )
    return _result(filters, "fitted", None, None, freqs, target, params, binds)


def _fitted_target(
    freqs: np.ndarray,
    fit,
    protect_corner: float,
    params: DesignParams,
    ceiling_db: np.ndarray,
    envelopes: Envelopes,
) -> np.ndarray:
    """The correction implied by the fitted attenuation, terminated and capped.

    `-A(f)` is the inverse of what was measured; it is unbounded downward, so it is terminated
    by a protective high-pass of the same implied order and then held under both dials.
    """
    order = max(fit.implied_order, 0.5)
    correction = -attenuation_db(
        freqs, fit.corner_hz, fit.slope_db_per_octave, fit.knee
    )
    termination = magnitude_db(
        high_pass_sos(
            HighPass(
                _nearest_even_alignment(order),
                _nearest_even_order(order),
                protect_corner,
            ),
            PUBLISH_FS,
        ),
        freqs,
        PUBLISH_FS,
    )
    capped = np.minimum(correction + termination, params.max_boost_db)
    return np.minimum(capped, np.interp(freqs, envelopes.freqs, ceiling_db))


def _nearest_even_order(order: float) -> int:
    return max(2, 2 * int(round(order / 2.0)))


def _nearest_even_alignment(order: float):
    from beqanalyser.design import Alignment

    return Alignment.BUTTERWORTH


def _noise_ceiling(
    envelopes: Envelopes, fit, params: DesignParams
) -> tuple[bool, np.ndarray]:
    """How much boost the measured noise floor allows, per §4.1.

    Computed and applied unconditionally. If it binds that is a signal, not merely a limit:
    a filter whose shape is set by the noise ceiling says the title is in the marginal regime
    and confidence should fall accordingly.
    """
    ceiling = envelopes.margin_db - params.noise_margin_db
    ceiling = np.where(np.isfinite(ceiling), ceiling, 0.0)
    wanted = -attenuation_db(
        envelopes.freqs, fit.corner_hz, fit.slope_db_per_octave, fit.knee
    )
    binds = bool(np.any(np.minimum(wanted, params.max_boost_db) > ceiling))
    return binds, ceiling


def _result(
    filters: list[BiquadSpec],
    method: DesignMethod,
    rolloff: HighPass | None,
    protect: HighPass | None,
    freqs: np.ndarray,
    target: np.ndarray,
    params: DesignParams,
    binds: bool,
) -> Design:
    band = (5.0, 200.0)
    boost = magnitude_db(biquad_sos(filters, PUBLISH_FS), freqs, PUBLISH_FS)
    return Design(
        filters=filters,
        method=method,
        mv_adjust_db=float(np.max(boost)),
        residual_db=residual_db(filters, target, freqs, PUBLISH_FS, band),
        residual_band_hz=band,
        rolloff=rolloff,
        protect=protect,
        noise_ceiling_binds=binds,
    )


def _decline(reason: str, message: str) -> Design:
    return Design(
        filters=None,
        method=None,
        mv_adjust_db=None,
        residual_db=None,
        residual_band_hz=None,
        rolloff=None,
        protect=None,
        noise_ceiling_binds=False,
        decline_reason=reason,
        decline_message=message,
    )
