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

from beqanalyser.design import DESIGN_GRID, BiquadSpec
from beqanalyser.design.filters import (
    Realisation,
    biquad_sos,
    drift_distribution,
    magnitude_db,
)
from beqanalyser.design.verify import Correction

logger = logging.getLogger(__name__)


def _at(value: float, quantum: float) -> float:
    """A dB quantity rounded to the precision the thresholds are known to.

    Applied to both sides of a comparison — see `AcceptParams.decision_quantum_db`.
    """
    return round(value / quantum) * quantum if quantum > 0 else value


@dataclass(frozen=True, slots=True)
class AcceptParams:
    """Thresholds the acceptance model applies."""

    target_tilt_db_per_octave: float = 0.0
    """The house curve asked of the corrected low end. **Positive rises toward the bottom.**

    The sign is the audio one, deliberately opposite to `Correction.tilt_db_per_octave`'s
    internal convention, because this is the dial a person sets and "+2 dB/octave" should mean
    a rising low end. `assess` negates once, at the comparison.

    This replaces `max_tilt_db_per_octave` 2.0 and `min_tilt_db_per_octave` -2.5, a window whose
    asymmetry was an unstated preference: it permitted 2.5 dB/octave of rise against 2.0 of
    droop, which over the 3.17 octaves of a 5-45 Hz band is 7.9 dB of lift against 6.3 dB of
    residual hole. Expressed as a request plus a tolerance, that preference becomes
    `target_tilt_db_per_octave = +0.25` and is visible rather than buried in two limits.

    0.0 because every filter the evidence base contains was produced aiming at flat — §3.4a's
    "flat is the shape; how far past flat to go is the preference dial of §4.3". A non-zero
    default would change four accepted answers on no evidence.

    **Acceptance-only, today.** No strategy builds a house curve into its target, so asking for
    a rise currently discards the flat candidates rather than producing rising ones: measured
    across the eight titles, +1 dB/octave loses a title and +2 loses three. Making this generate
    rather than filter means adding the requested rise to `flatten`/`counterfactual`'s targets,
    and it costs headroom at the bottom — roughly 6 dB for +2 dB/octave."""

    tilt_tolerance_db_per_octave: float = 2.0
    """How far the corrected tilt may sit from `target_tilt_db_per_octave`.

    2.0 is the half-width of the window this replaced, rounded; verified to select the identical
    filter on all eight titles. Also the tolerance the turnover clause compares against, which
    is why it is one number rather than two."""

    level_tolerance_db: float = 3.0
    """How far the corrected mean may sit from the requested shape's own mean.

    About the request, not about zero — which is what makes this independent of the tilt dial.
    A curve rising at T dB/octave and anchored at the top of the band has mean `T * octaves / 2`
    by construction, so a fixed window would quietly forbid the aggressive end of the tilt dial:
    at +2.5 dB/octave the mean is already +4 dB and the old +8 ceiling capped the dial at about
    +5 dB/octave without saying so.

    3.0 replaces the window (-3, +8), whose 11 dB width was asymmetric for the same unstated
    reason as the tilt limits. Verified outcome-neutral: the four accepted filters sit 1.8 to
    2.9 dB from their requested mean, and nothing accepted was ever within 8 dB of the old +8."""

    decision_quantum_db: float = 0.1
    """Precision every dB comparison here is made at. Below it, a difference is not a decision.

    No threshold in this class is known to better than this, and published gains are rounded to
    0.005 dB, so comparing at float precision invents knife-edges: title 2's 38.6 Hz shelf
    contributed 1.003 dB against a 1.0 dB limit and shipped with 0.003 dB of slack — one
    rounding from losing a section for no reason anyone could defend.

    Applied to both sides of each comparison, so it loosens every clause by at most half a
    quantum and never tightens one. Not applied to the extent clause, which is in Hz and already
    carries a 1.2x margin, nor to the band-width guard, which is in octaves."""

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

    min_judge_octaves: float = 1.0
    """Narrowest band a slope may be read from. Below it, abstain and say so.

    Tilt over a short band is not a weak measurement, it is an arbitrary one: Blazing Saddles'
    band from its own 33.7 Hz noise floor measures -7.32 dB/octave to 45 Hz and -0.02 to 80 Hz,
    which is the difference between "over-corrected" and "flat" decided by where the band was
    stopped. Every clause downstream of tilt inherits that.

    Calibrated between the two titles that have a measured noise floor at all, which is the only
    place this can bind. Blazing Saddles leaves **0.42** octaves and is the case above. Nocturnal
    Animals leaves **1.19**, and over them its `flatten` candidate measures +0.97 dB/octave and
    -1.9 dB — stable, inside every limit, and the right answer. 1.0 separates them.

    It was first set at 1.5 on the reasoning that the five titles with no measured floor all
    judge over 3.17 octaves and so have the width to spare. That compared the wrong populations:
    a title with no floor is never constrained by this clause, so its width says nothing about
    where the clause should sit, and the value it produced rejected Nocturnal Animals' good
    filter on a band its own measurement was fine over."""

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
    """A section contributing less than this to the cascade has not earned its slot (§5.1).

    Measured **over the judged band**, not over the whole design grid. A section earns its slot
    by contributing to the correction, and a bass correction's correction is in the bass. Judged
    over 3-400 Hz instead, a cascade can spend sections on the midrange and score well for it:
    Nocturnal Animals' `flatten` candidate passed with peaking sections at 214 and 341 Hz, Q 6.0,
    worth 1.94 and 1.72 dB across the grid and **0.00 dB** inside the band anyone listens to the
    result over. That is the "budget parked in the midrange" `correction_band_hz` exists to
    prevent, and it became reachable when `WIDEN_OCTAVES` opened the placement ceiling — so the
    two belong together.

    Measured across every passing candidate on the eight titles, the two populations do not
    overlap: the sections that earn nothing in band contribute exactly 0.00 dB there, and every
    other section contributes 1.00 dB or more. Worth knowing that the thinnest of those is
    title 2's 38.6 Hz shelf at **1.003 dB**, which clears this by 0.003 — it sits that close
    under the whole-grid measurement too, so the margin is not something this change introduced,
    but it is the filter title 2 ships and it is one rounding away from losing a section."""

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
    """Quantisation drift the **fitter** prefers to stay under. No longer an acceptance gate.

    Acceptance now judges the curve the device will actually realise — `verify` adds the
    coefficient-rounding error — and asks the only question that matters: does the shape survive.
    That is comparative and needs no calibrated number, where this one was a population separator
    (p90 of 1.09-1.11 dB for two-shelf designs against 13.59 for a cancelling cascade). It also
    rejected a usable filter: title 1's `counterfactual/35dB` measured 6.28 dB here and realises
    to tilt -1.79, level -1.2, which is a shape nobody would object to.

    Kept because the fitter still screens on it to *prefer* a robust cascade among equals, which
    is a legitimate tiebreak and the reason cancelling cascades rarely reach acceptance at all.
    The p90 is over `drift_samples` jitters of the published parameters — note that this explores
    coefficient sets near the published one rather than the rounding the published filter itself
    undergoes, which `verify` measures directly and which comes to 0.006-0.014 dB."""


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
    """The material's slope over the segment the corrected peak defines — the baseline.

    Not the slope below the material's *own* peak, which is a different segment and made the
    comparison meaningless on seven of eight titles; see `turnover_db_per_octave`."""

    turnover_after: float = math.nan
    """The same segment on the corrected curve. The turnover clause compares these two."""

    required_offset_db: float = 0.0
    """Gain reduction needed on the sub feed. 0.0 means none; NaN means unavailable.

    **Reported, not gated (§14.3).** Headroom is output-only per the contract's §2 — "you do
    not receive a headroom constraint as an input" — so this used to fail a candidate against
    `max_gain_reduction_db` and no longer does; `mv_adjust_db` and this value are the two
    headroom-shaped numbers that leave the designer, and both only ever go out."""

    recovered_fraction: float = math.nan
    """Priced target over measured deficit, deficit-weighted over the judged band (§14.1).

    NaN for a candidate with no target (the parametric route never builds one, so there is no
    ceiling to have clipped). Otherwise `sum(target) / sum(deficit)` over the points in the
    judged band where the deficit exceeds `recovered_fraction_floor_db` — a ratio of sums
    rather than a mean of ratios so a handful of near-zero-deficit bins cannot dominate it.
    Below 100% the evidence ceiling clipped the target; the four titles whose target is
    essentially unclipped read 84-102%, Alien and Tron 66-79%, and one title as low as 22% —
    over 100% means the target asked for more than the measured deficit, which §14.1's
    Blazing Saddles case shows is a construction defect, not evidence for a deeper rolloff."""

    shaping_fraction: float = math.nan
    """Share of the cascade's peak gain claimed below `filter_floor_hz`, R2's boundary.

    NaN when no filter floor was measured: the legacy floor value does not distinguish
    a successful check from an unavailable one. 0.0 when the floor was measured but
    the cascade claims nothing below it. This is `assess`'s existing shaping-note dB — the
    boost claimed below the floor in excess of what the cascade already reached there —
    expressed as a fraction of the cascade's own peak gain so it is comparable across
    candidates of different sizes; one of `confidence_from_evidence`'s two inputs."""

    device_error_db: float = math.nan
    """Worst dB the device's coefficient rounding adds, already inside `after_db`."""

    dc_margin_steps: float = math.nan
    """Smallest `1+a1+a2` across the cascade, in quantisation steps — why a section is fragile.

    Under about five steps a single rounding moves that section's DC gain appreciably:
    20*log10(1 + 1/N) is 3.5 dB at two steps and 0.8 dB at ten. Scales as (2*pi*f/fs)^2, so it
    is the closed-form reason a low section at a high rate is the hard case."""

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


def corrected_extent_hz(
    correction: Correction,
    params: AcceptParams,
    priced_target_db: np.ndarray | None = None,
) -> float:
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

    **An achievement measure, so it follows intent (§14.2) rather than the house curve alone.**
    A candidate whose target was clipped to part of the deficit is not expected to reach the
    house curve's own level down to the bottom of the band — it is expected to reach as far as
    the evidence licensed, which `priced_target_db` states. `None` (no target) falls back to
    the house curve exactly as before.
    """
    # bounded at both ends: the correction's own frequency axis runs to Nyquist, and walking
    # down from there reports the top of the spectrum rather than the top of the band
    band = (correction.freqs >= correction.band_hz[0]) & (
        correction.freqs <= correction.band_hz[1]
    )
    freqs = correction.freqs[band]
    after = _smooth(correction.after_db[band], params.extent_smoothing_bins)
    slack = spectral_roughness(correction, params.roughness_degree) / 2.0
    # The envelope tracks the intended shape rather than a fixed window, so a house curve or a
    # partially-licensed target does not read as the correction having stopped: at +2 dB/octave
    # the curve is *meant* to be 6 dB up at the bottom, and a static ceiling would terminate the
    # extent there.
    wanted = correction.intent_db(priced_target_db, params.target_tilt_db_per_octave)[
        band
    ]
    reach = params.level_tolerance_db + slack
    inside = (after >= wanted - reach) & (after <= wanted + reach)
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
    correction: Correction, params: AcceptParams
) -> tuple[float, float, float]:
    """Slope below the corrected curve's in-band peak, the material's slope over that same
    segment, and where the peak is.

    "Too much too soon and then a rolloff": a correction that reaches full boost above the
    bottom of the band and then falls away below it. `tilt` cannot see this — fitted across
    the whole band, the rise above the peak and the fall below it average out, and the third
    title's turnover measured -0.72 dB/octave overall while falling at +4.11 below its peak.

    **Both slopes come from one segment, and that is what makes the clause comparative.**
    Locating a peak on each curve separately and measuring the slope below *each* was not a
    comparison. A mix rises toward its own plateau, so its in-band peak lands at the top edge
    of the judged band — within half an octave of it on seven of the eight titles measured —
    the interior guard below then returned 0.0 for the material, and the clause silently
    collapsed into the absolute 2.0 dB/octave test it was written to replace. Only title 1,
    whose authored hump at 20 Hz sits inside the band, ever measured a real baseline (+12.23
    dB/oct); every other title compared a segment chosen on the corrected curve against a
    number that meant "not measurable here". Taking the material over the segment the
    corrected curve's peak defines keeps it like for like by construction, and costs one
    further `polyfit`.

    Slopes are signed as `tilt`: positive falls toward the bottom. Both are 0.0 when the
    segment is degenerate, so a clause reading them cannot fire on an unmeasurable turnover.
    """
    band = (correction.freqs >= correction.band_hz[0]) & (
        correction.freqs <= correction.band_hz[1]
    )
    freqs = correction.freqs[band]
    if len(freqs) < 4:
        return 0.0, 0.0, math.nan
    # Smoothed, and for the same reason the extent clause is: the material scatters by ~6 dB,
    # and `argmax` of a raw curve locates a bin rather than a peak. Measured on the third
    # title's corrected curve, the raw argmax put the peak at 36.6 Hz and read the turnover as
    # +0.00 dB/oct; the same curve through the same 9-bin window put it at 18.8 Hz and read
    # +1.70, against a rejection threshold of 2.0. One bin of scatter moved the segment being
    # measured by an octave, and the clause this sits in was written because a segment chosen
    # wrongly is the whole failure mode.
    after = _smooth(correction.after_db[band], params.extent_smoothing_bins)
    peak = int(np.argmax(after))
    # the peak has to be interior. At the band's top edge this measure degenerates into the
    # overall tilt, and reports plain under-correction as "too much too soon" — which the
    # tilt clause has already said, and said correctly.
    below_top = math.log2(freqs[-1] / freqs[peak])
    above_bottom = math.log2(freqs[peak] / freqs[0])
    if min(above_bottom, below_top) < params.turnover_min_octaves:
        return 0.0, 0.0, float(freqs[peak])
    octaves = np.log2(freqs[: peak + 1])
    before = _smooth(correction.before_db[band], params.extent_smoothing_bins)
    slope = float(np.polyfit(octaves, after[: peak + 1], 1)[0])
    material = float(np.polyfit(octaves, before[: peak + 1], 1)[0])
    return slope, material, float(freqs[peak])


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


def recovered_fraction(
    priced_target_db: np.ndarray | None,
    correction: Correction,
    floor_db: float = 1.0,
) -> float:
    """Priced target over measured deficit, deficit-weighted over the judged band (§14.1).

    The deficit is `max(-before_db, 0)` on `correction`'s own frequency axis; the target is
    `priced_target_db` (on `DESIGN_GRID`) interpolated onto that axis. A ratio of sums rather
    than a mean of per-bin ratios, deliberately: a bin with a fraction-of-a-dB deficit would
    otherwise contribute a wildly noisy ratio and could dominate a mean built from bins that
    mostly have real evidence behind them. `floor_db` excludes those bins from both sums so
    the aggregate is about where there is something to recover.

    NaN when there is no target (parametric) or no bin in the band clears `floor_db` — both
    mean "not applicable", not "0% recovered".
    """
    if priced_target_db is None:
        return math.nan
    band = (correction.freqs >= correction.band_hz[0]) & (
        correction.freqs <= correction.band_hz[1]
    )
    deficit = np.maximum(-correction.before_db[band], 0.0)
    target = np.interp(correction.freqs[band], DESIGN_GRID, priced_target_db)
    counted = deficit >= floor_db
    if not counted.any():
        return math.nan
    return float(np.sum(target[counted]) / np.sum(deficit[counted]))


def shaping_fraction(
    full_db: np.ndarray, grid: np.ndarray, filter_floor_hz: float
) -> float:
    """Share of the cascade's peak gain claimed below `filter_floor_hz`, R2's boundary.

    `full_db` is the cascade's own magnitude response over `grid` (`DESIGN_GRID`). The
    numerator is `assess`'s existing shaping-note dB — the boost claimed below the floor in
    *excess* of what the cascade already reached there, since every low shelf plateaus to DC
    and reading the full shelf gain would say every floor claims everything. Expressed as a
    fraction of the cascade's own peak gain so it is comparable across candidates.

    NaN when `filter_floor_hz` is NaN — the legacy value is ambiguous, so
    shaping cannot be quantified. 0.0 when the floor was measured but nothing is claimed
    beyond it.
    """
    if math.isnan(filter_floor_hz):
        return math.nan
    below = grid < filter_floor_hz
    if not below.any():
        return 0.0
    at_floor = float(np.interp(filter_floor_hz, grid, full_db))
    shaping = max(float(np.max(full_db[below])) - at_floor, 0.0)
    total = float(np.max(full_db))
    return shaping / total if total > 1e-9 else 0.0


def confidence_from_evidence(
    recovered_fraction: float, shaping_fraction: float
) -> float:
    """Uncalibrated evidence score, not a probability of a mastering filter.

    Missing components contribute zero support. A NaN floor cannot distinguish a successful
    check from an unavailable one; do not silently give either the maximum score.
    """
    ceiling_component = (
        0.0
        if not math.isfinite(recovered_fraction)
        else min(max(recovered_fraction, 0.0), 1.0)
    )
    identification_component = 1.0 - (
        1.0
        if not math.isfinite(shaping_fraction)
        else min(max(shaping_fraction, 0.0), 1.0)
    )
    return ceiling_component * identification_component


def assess(
    filters: list[BiquadSpec],
    correction: Correction,
    noise_floor_hz: float,
    params: AcceptParams | None = None,
    realisation: Realisation | None = None,
    filter_floor_hz: float = math.nan,
    required_offset_db: float = 0.0,
    target_db: np.ndarray | None = None,
) -> Verdict:
    """Judge one candidate against R1 and R3.

    `noise_floor_hz` is where R1's "down to the noise floor" terminates — from `diagnose`,
    not assumed. NaN means content was found all the way down, so the correction is expected
    to reach the bottom of the band.

    `filter_floor_hz` is R2's boundary, and it produces a *note* rather than a failure. Below
    it the attenuation being inverted is not level-independent, so undoing it is shaping and
    not identification — which lowers confidence without making the answer wrong.

    `target_db` is the evidence-priced target the fitter was handed, on `DESIGN_GRID`, or
    `None` for a candidate with no target (the parametric route). The tilt, level and extent
    clauses measure departure from *intent* — `before_db + target_db`, plus the house curve —
    rather than from the house curve alone (§14.2); `None` falls back to the house curve
    exactly as every clause did before intent existed. Overshoot, cliff, wobble-against-
    material, turnover, section contribution and drift/realisability are unaffected — those
    ask whether the filter is wrong, not whether it achieved what it was asked to, and must
    not be judged against a target that could itself be wrong (§6.2).
    """
    params = params or AcceptParams()
    realisation = realisation or Realisation()
    failures: list[str] = []
    notes: list[str] = []

    # Nothing below is meaningful on a band too short to carry a slope, so this returns rather
    # than adding a sixth failure to five arbitrary ones. See `min_judge_octaves`: the width is
    # what the material left after its own noise floor, so a band this narrow is a statement
    # about the title and not about the candidate.
    octaves = math.log2(correction.band_hz[1] / correction.band_hz[0])
    if octaves < params.min_judge_octaves:
        return Verdict(
            passed=False,
            failures=[
                f"only {octaves:.2f} octaves left to judge "
                f"({correction.band_hz[0]:.1f}-{correction.band_hz[1]:.1f} Hz); a slope read "
                f"over less than {params.min_judge_octaves:g} is set by where the band stops"
            ],
            notes=[],
            worst_gradient_before=math.nan,
            worst_gradient_after=math.nan,
            extent_hz=math.nan,
            drift_db=math.nan,
        )

    # --- R1: the shape asked for, no step, down to the noise floor
    # One negation, here: the dial reads in the audio sense (positive rises toward the bottom)
    # while `tilt_db_per_octave` is positive when the curve falls toward it.
    quantum = params.decision_quantum_db
    wanted = params.target_tilt_db_per_octave
    # Intent (§14.2): a target that only partially recovers the deficit is not itself flat, so
    # what "was asked for" here is the intended curve's own slope and level — before_db plus
    # the priced target, plus the house curve — not the dial's bare number. `target_db is None`
    # (no target) collapses `intent_*` back to the house curve exactly as `wanted`/
    # `requested_level_db` did before this existed, so a candidate with no target is unaffected.
    intent_tilt = -correction.intent_tilt_db_per_octave(target_db, wanted)
    achieved = -correction.tilt_db_per_octave
    if _at(abs(achieved - intent_tilt), quantum) > _at(
        params.tilt_tolerance_db_per_octave, quantum
    ):
        # Signed, with no direction word: "falls at -3.0 dB/oct" reads as a contradiction, and
        # the sign is the dial's own — positive rises toward the bottom.
        failures.append(
            f"tilts {achieved:+.1f} dB/oct where {intent_tilt:+.1f} was intended, outside the "
            f"{params.tilt_tolerance_db_per_octave:g} dB/oct allowed "
            "(positive rises toward the bottom)"
        )
    intent_level = correction.intent_level_db(target_db, wanted)
    if _at(abs(correction.level_db - intent_level), quantum) > _at(
        params.level_tolerance_db, quantum
    ):
        failures.append(
            f"corrected level {correction.level_db:+.1f} dB against the {intent_level:+.1f} "
            f"intended, outside the {params.level_tolerance_db:g} dB allowed"
        )

    # Comparative, like the cliff clause and for the same reason: the peak the corrected curve
    # turns over from may be one the correction never touched. On title 1 the mix is +8.6 dB
    # at 20 Hz against its own 40 Hz level — an authored hump, +14.2 dB in the LFE — so
    # `flatten` correctly asks for no boost across 12-31 Hz, the hump survives into the
    # corrected curve as its in-band peak, and everything below it reads as falling away from
    # something the filter did not put there. The input turns over at +12.23 dB/oct on its
    # own; the candidate left +3.2 and was rejected for a fourfold improvement.
    #
    # Both slopes are measured over the one segment the corrected peak defines — see
    # `turnover_db_per_octave` for why measuring each curve below its own peak left this
    # comparing unlike things on seven of eight titles.
    #
    # The tolerance is `tilt_tolerance_db_per_octave` rather than a new constant, which makes
    # this identical to the old absolute test whenever the material is flat below that peak —
    # title 3's input is flat there, so its parametric candidate at +4.1 still fails.
    turnover, material_turnover, peak_hz = turnover_db_per_octave(correction, params)
    if _at(turnover, params.decision_quantum_db) > _at(
        material_turnover + params.tilt_tolerance_db_per_octave,
        params.decision_quantum_db,
    ):
        failures.append(
            f"peaks at {peak_hz:.1f} Hz then falls at {turnover:.1f} dB/oct below it "
            f"against {material_turnover:.1f} in the material — too much too soon, then a "
            "rolloff"
        )

    # Overshoot, over the correction's whole extent rather than only the judged band — the one
    # clause that looks below `noise_floor_hz`. The judged band starts at that floor because the
    # correction is not expected to have *achieved* anything underneath it, but a low shelf acts
    # there whether or not it was asked to, and nothing else was watching: Blazing Saddles has no
    # programme content below 33.7 Hz and a candidate that lifted 5-20 Hz by +5 to +11 dB passed
    # every other clause, because every other clause had stopped looking at 33.7 Hz.
    #
    # Comparative on both sides and so needing no constant of its own: the bar is the shape that
    # was asked for, or where the material already sat if that is higher — which is what lets an
    # authored hump through. Title 1's mix is +5.8 dB at 20 Hz and its filter leaves +5.0 there;
    # the filter did not put it there and is not charged for it.
    guard = (correction.freqs >= DESIGN_GRID[0]) & (
        correction.freqs <= correction.band_hz[1]
    )
    slack = spectral_roughness(correction, params.roughness_degree) / 2.0
    bar = (
        np.maximum(
            correction.requested_db(params.target_tilt_db_per_octave)[guard],
            correction.before_db[guard],
        )
        + params.level_tolerance_db
        + slack
    )
    overshoot = correction.after_db[guard] - bar
    worst = int(np.argmax(overshoot))
    if _at(float(overshoot[worst]), quantum) > 0.0:
        at_hz = float(correction.freqs[guard][worst])
        failures.append(
            f"lifts {at_hz:.1f} Hz to {correction.after_db[guard][worst]:+.1f} dB, "
            f"{float(overshoot[worst]):.1f} dB above anything the material or the requested "
            "shape supports there — boosting what is not content"
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

    extent = corrected_extent_hz(correction, params, target_db)
    terminus = correction.band_hz[0] if math.isnan(noise_floor_hz) else noise_floor_hz
    if extent > terminus * 1.2:
        failures.append(
            f"corrected only down to {extent:.1f} Hz; content continues to "
            f"{terminus:.1f} Hz"
        )

    # --- R3: parsimonious, no cancellation, realisable
    grid = DESIGN_GRID
    samples = drift_distribution(filters, grid, realisation)
    drift = float(np.percentile(samples, 90))
    sos = biquad_sos(filters, realisation.fs)
    # The strict Jury conditions put both poles of each real biquad inside the
    # unit circle. Check the device coefficients: finite-band magnitude samples
    # cannot detect an uncancelled pole at DC, and no tolerance licenses one.
    for index, section in enumerate(realisation.quantise(sos)):
        a0, a1, a2 = section[3:]
        stable = (
            np.all(np.isfinite(section))
            and a0 > 0.0
            and a0 + a1 + a2 > 0.0
            and a0 - a1 + a2 > 0.0
            and a0 - a2 > 0.0
        )
        if not stable:
            failures.append(
                f"section {index + 1} is not stable after device coefficient quantisation"
            )

    full = magnitude_db(sos, grid, realisation.fs)
    # §4.2's headroom, measured on the waveform rather than on the magnitude. Reported on
    # `Verdict.required_offset_db`, never gated (§14.3): headroom is output-only per the
    # contract's §2, and this used to fail a candidate against a `max_gain_reduction_db` this
    # module no longer has. `required_offset_db` is negative when the filtered sub feed no
    # longer fits under full scale; the caller measures it because only the caller has the
    # signal.

    # in the band the result is judged over, not across the whole grid — see
    # `min_section_contribution_db` for the two midrange sections that motivated it
    judged = (grid >= correction.band_hz[0]) & (grid <= correction.band_hz[1])
    for index, section in enumerate(filters):
        without = [f for j, f in enumerate(filters) if j != index]
        reduced = (
            magnitude_db(biquad_sos(without, realisation.fs), grid, realisation.fs)
            if without
            else np.zeros_like(full)
        )
        contribution = float(np.max(np.abs((full - reduced)[judged])))
        if contribution < params.min_section_contribution_db:
            failures.append(
                f"section {index + 1} ({section.type} at {section.freq_hz:.1f} Hz) "
                f"contributes {contribution:.2f} dB across "
                f"{correction.band_hz[0]:g}-{correction.band_hz[1]:g} Hz — "
                "has not earned its slot"
            )

    shaping_frac = shaping_fraction(full, grid, filter_floor_hz)
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

    # Attribution rather than one scalar: the section with the least DC headroom is the one a
    # rounding will move, and naming it is actionable where "drift 2.11 dB" is not.
    step = 2.0 ** (realisation.integer_bits - realisation.coefficient_bits)
    margins = [
        abs(float(np.sum(biquad_sos([f], realisation.fs)[0, 3:6]))) / step
        for f in filters
    ]
    worst_margin = min(margins) if margins else math.nan
    if margins and worst_margin < 5.0:
        tightest = filters[int(np.argmin(margins))]
        moves = 20.0 * math.log10(1.0 + 1.0 / max(worst_margin, 1e-9))
        notes.append(
            f"{tightest.type} at {tightest.freq_hz:.1f} Hz has {worst_margin:.1f} quantisation "
            f"steps of DC headroom on this device; one rounding moves its low-frequency gain by "
            f"{moves:.1f} dB"
        )

    return Verdict(
        passed=not failures,
        failures=failures,
        notes=notes,
        worst_gradient_before=before,
        worst_gradient_after=after,
        extent_hz=extent,
        drift_db=drift,
        required_offset_db=required_offset_db,
        device_error_db=float(
            np.max(
                np.abs(
                    magnitude_db(realisation.quantise(sos), grid, realisation.fs) - full
                )
            )
        ),
        dc_margin_steps=worst_margin,
        turnover_before=material_turnover,
        turnover_after=turnover,
        roughness_db=roughness,
        wobble_db=wobble,
        recovered_fraction=recovered_fraction(target_db, correction),
        shaping_fraction=shaping_frac,
    )
