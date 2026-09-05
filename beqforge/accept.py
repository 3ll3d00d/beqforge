"""The acceptance model of §6.4 — R1 and R3, as checks rather than prose.

R2 is a property of the material, measured by `diagnose`, and it bounds what a candidate may
attempt rather than judging one after the fact — so it appears here only as a note. Where a
correction reaches below the level-independence floor it is shaping rather than inverting an
identified filter, which lowers confidence without making the answer wrong. Title 2's accepted
design does exactly that and is right to; what was missing was anything saying so.

The reason this module exists separately from `verify` is that `Correction`'s statistics are
aggregates — `spread`, `tilt` and `level` are all means or extrema over a band — and R1 is
not an aggregate. A design that fills a notch and leaves a 9 dB cliff two bins wide scores
well on all three and is wrong. The cliff test below is what distinguishes them, and it is
deliberately *comparative*: the corrected curve is measured against the input curve rather
than against a threshold, so it needs no calibrated constant. §12 records that the existing
thresholds are guesses; this one has nothing to guess.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np

from beqanalyser.design import BiquadSpec
from beqanalyser.design.filters import (
    Realisation,
    biquad_sos,
    drift_distribution,
    magnitude_db,
)
from beqanalyser.design.verify import Correction

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AcceptParams:
    """Thresholds the acceptance model applies."""

    max_tilt_db_per_octave: float = 2.0
    """Beyond this the corrected end is falling, not flat-to-mildly-rising."""

    min_tilt_db_per_octave: float = -2.5
    """Below this it is rising too hard to be called mild."""

    level_range_db: tuple[float, float] = (-3.0, 8.0)
    """Where the corrected low end may sit relative to the reference."""

    spread_margin_db: float = 2.0
    """How much flatter than the material's own roughness a correction need not be.

    "Flat" is part of R1, but an absolute threshold cannot express it. A smooth cascade cannot
    remove structure the mean spectrum already has, so the material sets a floor: measured
    against a smooth trend over the judged band, all three titles wobble by 5.8-6.7 dB. An
    absolute 6.0 dB limit therefore sat exactly on that floor — it failed the hand-built filter
    accepted on the first title (6.6 against 6.74 of roughness) and passed one on the second
    only because the cascade happened to cancel some of the wobble.

    Judged as an excess over roughness the populations separate: accepted designs run -1.6 to
    -0.1 dB, while the two rejected ones run +2.4 and +4.3."""

    roughness_degree: int = 3
    """Order of the smooth trend the material's roughness is measured against."""

    extent_smoothing_bins: int = 9
    """Width of the moving average the extent clause is measured on."""

    turnover_min_octaves: float = 0.5
    """How far inside the band the peak must sit before a turnover is measured.

    Nearer the bottom than this and the segment below it is a couple of bins of noise; nearer
    the top and the measure is just the overall tilt under another name."""

    cliff_window_octaves: float = 0.25
    """Width the local gradient is measured over. Narrow enough to see a step."""

    cliff_tolerance_db_per_octave: float = 2.0
    """How much worse than the input's worst gradient a correction may be.

    Not zero: a correction that steepens one narrow region slightly while removing a much
    larger cliff elsewhere is fine, and demanding monotone improvement everywhere would
    reject it."""

    min_section_contribution_db: float = 1.0
    """A section contributing less than this to the cascade has not earned its slot (§5.1)."""

    shaping_note_db: float = 1.0
    """Boost claimed below the level-independence floor worth remarking on.

    Not a limit. R2 says where inverting an attenuation stops being *identification* of a
    filter and becomes shaping, which is a claim about confidence rather than about the
    target — title 2's accepted filter boosts through that region and is right to. But
    nothing in the system said where the boundary was, so a reader had no way to tell a
    correction that rests on measured level-independence from one that does not.

    Measured as the boost *in excess of* what the cascade had already reached at the floor,
    not as the boost below it. Every low shelf plateaus to DC, so the second reads as the
    full shelf gain for any floor at all and says nothing. The excess is the part of the
    correction that only the unmeasured region asks for."""

    max_drift_db: float = 3.0
    """Quantisation drift above which the cascade is not safely realisable.

    Applied to the 90th percentile of `drift_samples`, not to a single evaluation.

    Calibrated against the cascades measured so far rather than picked: at p90, two-shelf
    designs on both titles sit at 1.09-1.11 dB and the hand-built single shelf accepted on
    the first title at 2.33, while the four-section cancelling cascade reaches 13.59. The
    populations separate by an order of magnitude, so the exact value between them matters
    little — but it is still a threshold set on two titles (§12)."""


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether one candidate is publishable, and what is wrong with it if not."""

    passed: bool
    failures: list[str]
    notes: list[str]
    worst_gradient_before: float
    worst_gradient_after: float
    extent_hz: float
    drift_db: float
    turnover_before: float = math.nan
    """Slope below the *input's* in-band peak. What the material does on its own."""

    turnover_after: float = math.nan
    """The same on the corrected curve. The turnover clause compares these two."""

    roughness_db: float = math.nan
    """Wobble in the input over the judged band — the floor on achievable flatness."""

    wobble_db: float = math.nan
    """The same statistic on the corrected curve. The flatness clause compares these two."""

    def __str__(self) -> str:
        head = "accept" if self.passed else "REJECT"
        detail = "; ".join(self.failures) if self.failures else "no objections"
        return f"{head}: {detail}"


def worst_gradient(
    freqs: np.ndarray,
    values_db: np.ndarray,
    band_hz: tuple[float, float],
    window_octaves: float,
) -> tuple[float, float]:
    """Steepest local rise toward the bottom of the band, and where it is.

    A cliff is local by definition, so this slides a narrow window rather than fitting the
    band. Sign follows `Correction.tilt_db_per_octave`: positive falls toward the bottom.
    """
    step = 2.0**window_octaves
    best, at = 0.0, math.nan
    candidates = freqs[(freqs >= band_hz[0]) & (freqs <= band_hz[1] / step)]
    for low in candidates:
        window = (freqs >= low) & (freqs <= low * step)
        if window.sum() < 3:
            continue
        slope = float(np.polyfit(np.log2(freqs[window]), values_db[window], 1)[0])
        if slope > best:
            best, at = slope, float(low)
    return best, at


def corrected_extent_hz(correction: Correction, params: AcceptParams) -> float:
    """Lowest frequency the corrected curve is still within the acceptable envelope at.

    R1's extent clause. Both candidates on the second title are flat across the band they
    cover; the only difference between them is how far down that band reaches, so a check
    that does not measure extent cannot tell them apart.

    Judged on a smoothed curve against an envelope widened by the material's own scatter. Bin
    noise is not something a filter can address — a hand-built design that is flat to +-1.5 dB
    across 5-40 Hz still puts 17 of 164 bins below an absolute -3 dB line, worst -3.9, in runs
    up to 0.7 Hz wide, and terminating on the first of those reported the correction as
    reaching only 25.9 Hz. What this clause is for is gross failure to correct at all — the
    design it was written to catch sits 13 dB out, not 0.9.
    """
    # bounded at both ends: the correction's own frequency axis runs to Nyquist, and walking
    # down from there reports the top of the spectrum rather than the top of the band
    band = (correction.freqs >= correction.band_hz[0]) & (
        correction.freqs <= correction.band_hz[1]
    )
    freqs = correction.freqs[band]
    after = _smooth(correction.after_db[band], params.extent_smoothing_bins)
    slack = spectral_roughness(correction, params.roughness_degree) / 2.0
    low, high = params.level_range_db
    low, high = low - slack, high + slack
    inside = (after >= low) & (after <= high)
    if not inside.any():
        return float(freqs[-1])
    index = len(inside) - 1
    while index >= 0 and inside[index]:
        index -= 1
    return float(freqs[min(index + 1, len(freqs) - 1)])


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """Moving average, edges preserved rather than pulled toward zero."""
    if window <= 1 or len(values) < window:
        return values
    padded = np.pad(values, window // 2, mode="edge")
    return np.convolve(padded, np.ones(window) / window, mode="valid")[: len(values)]


def turnover_db_per_octave(
    correction: Correction, params: AcceptParams, values_db: np.ndarray | None = None
) -> tuple[float, float]:
    """Slope from a curve's in-band peak down to the bottom of the band.

    Defaults to the corrected curve; pass `correction.before_db` to measure what the material
    does on its own, which is what the clause compares against.

    "Too much too soon and then a rolloff": a correction that reaches full boost above the
    bottom of the band and then falls away below it. `tilt` cannot see this — fitted across
    the whole band, the rise above the peak and the fall below it average out, and the third
    title's turnover measured -0.72 dB/octave overall while falling at +4.11 below its peak.

    Returns the slope and the peak frequency. Sign follows `tilt`: positive falls toward the
    bottom.
    """
    band = (correction.freqs >= correction.band_hz[0]) & (
        correction.freqs <= correction.band_hz[1]
    )
    freqs = correction.freqs[band]
    if len(freqs) < 4:
        return 0.0, math.nan
    values_db = correction.after_db if values_db is None else values_db
    # Smoothed, and for the same reason the extent clause is: the material scatters by ~6 dB,
    # and `argmax` of a raw curve locates a bin rather than a peak. Measured on the third
    # title's corrected curve, the raw argmax put the peak at 36.6 Hz and read the turnover as
    # +0.00 dB/oct; the same curve through the same 9-bin window put it at 18.8 Hz and read
    # +1.70, against a rejection threshold of 2.0. One bin of scatter moved the segment being
    # measured by an octave, and the clause this sits in was written because a segment chosen
    # wrongly is the whole failure mode.
    after = _smooth(values_db[band], params.extent_smoothing_bins)
    peak = int(np.argmax(after))
    # the peak has to be interior. At the band's top edge this measure degenerates into the
    # overall tilt, and reports plain under-correction as "too much too soon" — which the
    # tilt clause has already said, and said correctly.
    below_top = math.log2(freqs[-1] / freqs[peak])
    above_bottom = math.log2(freqs[peak] / freqs[0])
    if min(above_bottom, below_top) < params.turnover_min_octaves:
        return 0.0, float(freqs[peak])
    slope = float(np.polyfit(np.log2(freqs[: peak + 1]), after[: peak + 1], 1)[0])
    return slope, float(freqs[peak])


def spectral_roughness(correction: Correction, degree: int = 3) -> float:
    """How far the *input* departs from a smooth trend over the judged band.

    The floor on achievable flatness. A cascade of shelves and peaking sections is smooth in
    log-frequency, so whatever wobble the mean spectrum carries survives correction — judging
    the result against a fixed number charges a filter for structure it cannot reach.
    """
    return correction.wobble_db(correction.before_db, degree)


def corrected_wobble(correction: Correction, degree: int = 3) -> float:
    """The same statistic on the corrected curve, so the comparison is like for like.

    `Correction.spread_db` is peak-to-peak of the corrected curve *including* its trend,
    while `spectral_roughness` removes one — so comparing them charged a correction for tilt
    the tilt clause has already judged. A perfectly smooth curve rising at 1.5 dB/octave over
    5-45 Hz scores a spread of 4.70 dB against a roughness of 0.00, and at the tilt clause's
    own limits (+2.0 / -2.5 dB/octave over 3.17 octaves) tilt alone accounts for 6.3-7.9 dB
    of spread. The two clauses were not independent, and the flatness one was mostly
    re-reading the tilt.

    Both curves are detrended at the same degree, each against its own trend: the smooth part
    of a corrected curve is what tilt, turnover and level are for, and what survives here is
    the wobble neither the material nor a smooth cascade can do anything about.
    """
    return correction.wobble_db(correction.after_db, degree)


def assess(
    filters: list[BiquadSpec],
    correction: Correction,
    noise_floor_hz: float,
    params: AcceptParams | None = None,
    realisation: Realisation | None = None,
    filter_floor_hz: float = math.nan,
) -> Verdict:
    """Judge one candidate against R1 and R3.

    `noise_floor_hz` is where R1's "down to the noise floor" terminates — from `diagnose`,
    not assumed. NaN means content was found all the way down, so the correction is expected
    to reach the bottom of the band.

    `filter_floor_hz` is R2's boundary, and it produces a *note* rather than a failure. Below
    it the attenuation being inverted is not level-independent, so undoing it is shaping and
    not identification — which lowers confidence without making the answer wrong.
    """
    params = params or AcceptParams()
    realisation = realisation or Realisation()
    failures: list[str] = []
    notes: list[str] = []

    # --- R1: flat to mildly rising, no step, down to the noise floor
    if correction.tilt_db_per_octave > params.max_tilt_db_per_octave:
        failures.append(
            f"still falls at {correction.tilt_db_per_octave:.1f} dB/oct — under-corrected"
        )
    if correction.tilt_db_per_octave < params.min_tilt_db_per_octave:
        failures.append(
            f"rises at {-correction.tilt_db_per_octave:.1f} dB/oct — over-corrected"
        )
    low, high = params.level_range_db
    if not low <= correction.level_db <= high:
        failures.append(
            f"corrected level {correction.level_db:+.1f} dB is outside {low:+g}..{high:+g}"
        )

    # Comparative, like the cliff clause and for the same reason: the peak the corrected curve
    # turns over from may be one the correction never touched. On title 1 the mix is +8.6 dB
    # at 20 Hz against its own 40 Hz level — an authored hump, +14.2 dB in the LFE — so
    # `flatten` correctly asks for no boost across 12-31 Hz, the hump survives into the
    # corrected curve as its in-band peak, and everything below it reads as falling away from
    # something the filter did not put there. The input turns over at +12.23 dB/oct on its
    # own; the candidate left +3.2 and was rejected for a fourfold improvement.
    #
    # The tolerance is `max_tilt_db_per_octave` rather than a new constant, which makes this
    # identical to the old absolute test whenever the material is flat below its peak — title
    # 3's input turns over at +0.00, so its parametric candidate at +4.1 still fails.
    turnover, peak_hz = turnover_db_per_octave(correction, params)
    material_turnover, material_peak_hz = turnover_db_per_octave(
        correction, params, correction.before_db
    )
    if turnover > material_turnover + params.max_tilt_db_per_octave:
        failures.append(
            f"peaks at {peak_hz:.1f} Hz then falls at {turnover:.1f} dB/oct below it "
            f"against {material_turnover:.1f} in the material — too much too soon, then a "
            "rolloff"
        )

    roughness = spectral_roughness(correction, params.roughness_degree)
    wobble = corrected_wobble(correction, params.roughness_degree)
    if wobble > roughness + params.spread_margin_db:
        failures.append(
            f"corrected low end wobbles {wobble:.1f} dB over "
            f"{correction.band_hz[0]:g}-{correction.band_hz[1]:g} Hz against "
            f"{roughness:.1f} dB in the material; expected flat"
        )

    before, _ = worst_gradient(
        correction.freqs,
        correction.before_db,
        correction.band_hz,
        params.cliff_window_octaves,
    )
    after, after_at = worst_gradient(
        correction.freqs,
        correction.after_db,
        correction.band_hz,
        params.cliff_window_octaves,
    )
    if after > before + params.cliff_tolerance_db_per_octave:
        failures.append(
            f"introduces a cliff of {after:.1f} dB/oct at {after_at:.1f} Hz where the input's "
            f"worst was {before:.1f} — relocates the discontinuity rather than removing it"
        )

    extent = corrected_extent_hz(correction, params)
    terminus = correction.band_hz[0] if math.isnan(noise_floor_hz) else noise_floor_hz
    if extent > terminus * 1.2:
        failures.append(
            f"corrected only down to {extent:.1f} Hz; content continues to "
            f"{terminus:.1f} Hz"
        )

    # --- R3: parsimonious, no cancellation, realisable
    grid = np.logspace(math.log10(3.0), math.log10(400.0), 400)
    samples = drift_distribution(filters, grid, realisation)
    drift = float(np.percentile(samples, 90))
    if drift > params.max_drift_db:
        failures.append(
            f"quantisation drift {drift:.2f} dB at p90 (median "
            f"{np.median(samples):.2f}, worst {samples.max():.2f}) — cancelling sections"
        )
    sos = biquad_sos(filters, realisation.fs)

    full = magnitude_db(sos, grid, realisation.fs)
    for index, section in enumerate(filters):
        without = [f for j, f in enumerate(filters) if j != index]
        reduced = (
            magnitude_db(biquad_sos(without, realisation.fs), grid, realisation.fs)
            if without
            else np.zeros_like(full)
        )
        contribution = float(np.max(np.abs(full - reduced)))
        if contribution < params.min_section_contribution_db:
            failures.append(
                f"section {index + 1} ({section.type} at {section.freq_hz:.1f} Hz) "
                f"contributes {contribution:.2f} dB — has not earned its slot"
            )

    if not math.isnan(filter_floor_hz):
        below = grid < filter_floor_hz
        at_floor = float(np.interp(filter_floor_hz, grid, full))
        shaping = float(np.max(full[below])) - at_floor if below.any() else 0.0
        if shaping >= params.shaping_note_db:
            notes.append(
                f"{shaping:.1f} dB of the correction is claimed below "
                f"{filter_floor_hz:.1f} Hz, where the attenuation stops being "
                "level-independent — that part is shaping rather than identification (R2)"
            )

    if max((abs(f.q) for f in filters), default=0.0) > 4.0:
        notes.append(
            "carries a Q above 4, which is unusual but not itself a defect — check the "
            "target is shelf-shaped (§11, Constraining Q)"
        )

    return Verdict(
        passed=not failures,
        failures=failures,
        notes=notes,
        worst_gradient_before=before,
        worst_gradient_after=after,
        extent_hz=extent,
        drift_db=drift,
        turnover_before=material_turnover,
        turnover_after=turnover,
        roughness_db=roughness,
        wobble_db=wobble,
    )
