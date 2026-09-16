"""Turning an identified rolloff into a publishable filter.

Inversion is preference: identification says what was done, this says how far to undo it
and exposes the choices as dials rather than making them silently. See AGENTS.md's "Working
on design/" for the shipped model and TODO.md for what's still open.

Two routes, matching the contract's `method`:

* `exact` — the rolloff was identified as a named alignment, so the protective filter is given
  the same alignment and the published cascade *is* the inverse, in closed form (§5).
* `fitted` — an attenuation was measured but matches no representable alignment, so the target
  is built from the fitted curve and approximated numerically. Weaker claim, and the residual
  says how much weaker.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from beqanalyser.design import (
    DESIGN_GRID,
    Alignment,
    BiquadSpec,
    ExactInversionUnavailable,
    HighPass,
)
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
RESIDUAL_BAND_HZ = (5.0, 200.0)
"""Band the fitted cascade's residual is scored over, and reported against.

One name because it was two literals — the `fit_minimal_biquads` call and `_result`'s own `band`
— which is two places to change and one of them to forget. Wider than any placement band on
purpose: `_fit_structure` states the rule, evaluate wide and place narrow, or a section drifts up
to where nothing penalises it.
"""

PUBLISH_FS = 96000.0
"""Rate the cascade is realised at for measuring its own residual. Not published (§5).

A `BiquadSpec` is rate-independent, so this only sets the rate the residual is *read* at —
but it was 48 kHz while the pipeline judges, quantises and reports at 96 kHz, so a parametric
candidate's residual was the one number in the run measured somewhere else. 96 kHz is also the
worse case: the poles sit nearer z=1 (§5.1)."""


@dataclass(frozen=True, slots=True)
class DesignParams:
    """The dials of §4.3. This is where preference lives, and the only place it should."""

    max_boost_db: float = 20.0
    """Absolute cap on the correction. Sets the protective filter's corner."""

    residual_target_db: float = 0.5
    """Accuracy the published cascade must reach against its target.

    Sections are spent until this is met, then no more. Under-spending shows up here as a
    residual that misses; over-spending would otherwise show up nowhere at all."""

    confidence_z: float = 1.645
    """Bootstrap standard errors of margin a bin must clear before its boost is trusted (§4.1).

    The same dial as `PipelineParams.confidence_z`, and the same default, because it is the same
    question — see `_noise_ceiling`. It replaces `noise_margin_db`, a flat 12 dB haircut that
    could not tell 1,300 loud frames drawn from hundreds of scenes from 11 isolated instants."""

    lowest_frequency_hz: float = 5.0
    """Lowest frequency worth restoring — and the floor on where a section may be placed.

    Nothing below this was measured, so a section placed there has its corner and Q resting on
    no evidence."""

    gain_headroom_db: float = 6.0
    """How far a single section's gain may exceed the realised boost cap.

    Some headroom is needed because sections shape each other, but not much: a fit allowed
    45 dB used it, expressing a correction under 5 dB above 10 Hz as a 3 Hz shelf with +45 dB.
    No BEQ should publish a section gain like that, whatever the realised response does."""

    max_gain_db: float | None = None
    """Explicit per-section bound; None retains max_boost_db + gain_headroom_db."""

    max_drift_db: float | None = None
    """Optional publication-sensitivity screen shared with the pipeline fitter."""

    residual_band_hz: tuple[float, float] = RESIDUAL_BAND_HZ
    """Evaluation band shared by numerical fitting and the reported residual."""

    max_sections: int = 6
    """Ceiling on biquads the numerical route may spend. The device budget is 10 (§5)."""

    fit_seeds: tuple[int, ...] = (0,)
    """Seeds the numerical fit is repeated from, at each section count and split.

    Carried explicitly because it was not, and the omission cost a quarter of every run. This
    call reached `fit_minimal_biquads` without a `seeds` argument and so inherited that
    function's own default of three, while the pipeline around it fitted from one — so the
    parametric route ran three times the optimiser of every other candidate, on the strategy
    that is rejected on all four titles. `PipelineParams.fit_seeds` sets this now, and the
    reasoning there applies here unchanged."""

    realisation: Realisation | None = Realisation()
    """How the cascade will actually be realised, scored during the fit.

    On by default. Fitting in float64 alone accepts cascades built from large opposing
    sections that cancel; on the target device the cancellation does not survive coefficient
    quantisation. Measured on this pipeline's own output at 96 kHz in 5.23 fixed point, the
    drift falls from 0.98 dB to 0.19 dB for no meaningful loss of accuracy."""

    @property
    def section_gain_db(self) -> float:
        return (
            self.max_boost_db + self.gain_headroom_db
            if self.max_gain_db is None
            else self.max_gain_db
        )


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
    target_db: np.ndarray | None = None
    """The actual evidence-priced target on DESIGN_GRID, including exact inverses."""
    unpriced_target_db: np.ndarray | None = None
    target_notes: tuple[str, ...] = ()

    @property
    def declined(self) -> bool:
        return self.filters is None


def design(
    identification: Identification,
    envelopes: Envelopes,
    params: DesignParams | None = None,
    *,
    price_target: Callable[[np.ndarray], tuple[np.ndarray, list[str]]] | None = None,
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
    _, ceiling_db = _noise_ceiling(envelopes, fit, params)

    if not np.any(ceiling_db > 0):
        return _decline(
            "evidence_unavailable", "No measured support for a positive correction."
        )

    freqs = DESIGN_GRID
    filters = None
    protect = None
    unpriced = None
    if identification.rolloff is not None:
        protect = HighPass(
            identification.rolloff.alignment,
            identification.rolloff.order,
            protect_corner,
        )
        try:
            filters = invert_to_shelves(identification.rolloff, protect)
            unpriced = inversion_target_db(
                identification.rolloff, protect, freqs, PUBLISH_FS
            )
        except ExactInversionUnavailable as unavailable:
            logger.info(f"Closed form unavailable ({unavailable}); fitting instead")

    if unpriced is None:
        unpriced = _unpriced_fitted_target(freqs, fit, protect_corner, params)
    if price_target is None:
        ceiling = np.interp(freqs, envelopes.freqs, ceiling_db, left=0.0, right=0.0)
        target = np.clip(unpriced, 0.0, ceiling)
        notes = []
    else:
        target, notes = price_target(unpriced)
    binds = bool(np.any(unpriced > target))
    if binds:
        notes.append("evidence ceiling restricts the parametric inverse")
    if not np.any(target > 0):
        return _decline(
            "evidence_unavailable", "No measured support for a positive correction."
        )

    # Closed form is only an option when it meets the same effective resource bounds.
    if (
        filters is not None
        and np.array_equal(target, unpriced)
        and len(filters) <= params.max_sections
        and all(
            abs(f.gain_db) <= params.section_gain_db
            and f.freq_hz >= params.lowest_frequency_hz
            for f in filters
        )
    ):
        return _result(
            filters,
            "exact",
            identification.rolloff,
            protect,
            freqs,
            target,
            params,
            binds,
            unpriced,
            tuple(notes),
        )

    filters, _ = fit_minimal_biquads(
        target,
        freqs,
        PUBLISH_FS,
        params.max_sections,
        params.residual_target_db,
        band_hz=params.residual_band_hz,
        placement_band_hz=correction_band_hz(target, freqs, params.lowest_frequency_hz),
        max_gain_db=params.section_gain_db,
        realisation=params.realisation,
        seeds=params.fit_seeds,
        max_drift_db=params.max_drift_db,
    )
    return _result(
        filters,
        "fitted",
        None,
        None,
        freqs,
        target,
        params,
        binds,
        unpriced,
        tuple(notes),
    )


def _fitted_target(
    freqs: np.ndarray,
    fit,
    protect_corner: float,
    params: DesignParams,
    ceiling_db: np.ndarray,
    envelopes: Envelopes,
) -> np.ndarray:
    """The terminated parametric target, restricted by the measured evidence."""
    capped = _unpriced_fitted_target(freqs, fit, protect_corner, params)
    return np.clip(
        capped, 0.0, np.interp(freqs, envelopes.freqs, ceiling_db, left=0.0, right=0.0)
    )


def _unpriced_fitted_target(
    freqs: np.ndarray, fit, protect_corner: float, params: DesignParams
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
                PROTECTIVE_ALIGNMENT,
                _nearest_even_order(order),
                protect_corner,
            ),
            PUBLISH_FS,
        ),
        freqs,
        PUBLISH_FS,
    )
    capped = np.minimum(correction + termination, params.max_boost_db)
    return np.maximum(capped, 0.0)


def _nearest_even_order(order: float) -> int:
    return max(2, 2 * int(round(order / 2.0)))


PROTECTIVE_ALIGNMENT = Alignment.BUTTERWORTH
"""Alignment of the protective high-pass on the *fitted* path.

§4.3 says to default this to the identified rolloff's alignment, which is what makes the
output the exact inverse rather than a fit to it. That is what the `exact` path above does.
This constant is only reached when no alignment was identified, so there is nothing to match
and Butterworth is a stated choice rather than a derived one. It was a function taking the
implied order and ignoring it, which read as though the alignment were being chosen."""


def _noise_ceiling(
    envelopes: Envelopes, fit, params: DesignParams
) -> tuple[bool, np.ndarray]:
    """How much boost the measured noise floor allows, per §4.1.

    Computed and applied unconditionally. If it binds that is a signal, not merely a limit:
    a filter whose shape is set by the noise ceiling says the title is in the marginal regime
    and confidence should fall accordingly.

    **One ceiling, derived the same way on both paths.** This was `margin_db - 12.0`, a flat
    haircut, while `flatten` moved to `margin_db - confidence_z * margin_se_db` — per bin, from
    a block bootstrap over the evidence each bin actually has. §13.7 recorded the two as "two
    boost caps, differently applied"; keeping the flat one here would have left the parametric
    route asserting a number the rest of the system had stopped asserting.

    Missing and omitted measurements license no boost, as on the shared target path.
    """
    ceiling = envelopes.boost_ceiling(params.confidence_z)
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
    unpriced_target: np.ndarray,
    notes: tuple[str, ...],
) -> Design:
    band = params.residual_band_hz
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
        target_db=target.copy(),
        unpriced_target_db=unpriced_target.copy(),
        target_notes=notes,
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
