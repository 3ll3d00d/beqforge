"""A plain-language account of a run: what it found, how it filtered, why this candidate.

Everything here is already in the `Report`; nothing is measured or decided. What this adds is
order and plain wording, for a reader who has only the designer response. The response
otherwise carried the basis for a correction scattered through 2,000 characters of
limitation notes and a `PipelineParams` repr, which is complete and unreadable.

Three parts, each a short paragraph:

* **found** — the reference the deficit is measured against, where the programme stops
  tracking it, where the attenuation stops being level-invariant, and which channels show a
  steep knee. Present for every run that got as far as a diagnosis, including declines.
* **correction** — the chosen candidate: how much it was asked for, how much the evidence
  licensed, the cascade, and the corrected low end against the reference, before and after.
* **alternatives** — every other candidate, and why it lost.
"""

import math

import numpy as np

from beqforge import DESIGN_GRID
from beqforge.pipeline import Candidate, Report

POINTS_HZ = (5, 8, 10, 13, 16, 20, 25, 31, 40, 50, 63)
"""Where the before/after table is read — the same points `tools/design_beq.py` prints."""


def _hz(value: float) -> str:
    return f"{value:.1f} Hz"


def found(report: Report) -> str:
    """The reference, the floors and the channel knees, in the order a correction uses them."""
    parts: list[str] = []
    low, high = report.mix_plateau_hz
    if math.isfinite(report.mix_reference_db):
        parts.append(
            f"reference: the mix's own plateau, {low:.1f}-{high:.1f} Hz, "
            f"at {report.mix_reference_db:.1f} dB"
        )
    else:
        parts.append(
            "reference: the mix has no usable flat plateau in the analysis band, so there "
            "is nothing to measure a deficit against"
        )
    d = report.diagnosis
    if d is None:
        return "; ".join(parts)

    parts.extend(_carriage(report))
    if math.isnan(d.noise_floor_hz):
        parts.append("the programme tracks that reference to the bottom of the band")
    else:
        parts.append(
            f"the programme tracks that reference down to {_hz(d.noise_floor_hz)}; "
            "below it nothing is recovered and any boost is held flat"
        )
    if math.isfinite(d.filter_floor_hz):
        parts.append(
            f"the attenuation is level-invariant down to {_hz(d.filter_floor_hz)}; "
            "correction below that is shaping, not the inverse of a measured filter"
        )

    knees = [
        f"{c.name} {c.max_slope_db_per_octave:.0f} dB/oct at {_hz(c.max_slope_hz)}"
        for c in d.channels.values()
        if c.is_filtered
    ]
    parts.append(
        "channels with a steep knee: " + ", ".join(knees)
        if knees
        else "no channel shows a steep knee"
    )
    if report.judged_band_hz is not None:
        a, b = report.judged_band_hz
        parts.append(f"results are judged over {a:.1f}-{b:.1f} Hz")
    parts.append(goal(report))
    return "; ".join(parts)


def goal(report: Report) -> str:
    """The preference the deficit was measured against — without it "asks for X dB" is unread."""
    tilt = report.accept.target_tilt_db_per_octave
    pivot = (
        ""
        if report.judged_band_hz is None
        else f" below {report.judged_band_hz[1]:.1f} Hz"
    )
    if tilt == 0:
        return f"goal: flat{pivot}"
    shape = "rising" if tilt > 0 else "rolling off"
    return f"goal: {shape} at {abs(tilt):g} dB/octave toward the bottom{pivot}"


SILENCE_MENTION = 0.1
"""Presentation only: a channel silent for at least this share of the programme is named."""


def _carriage(report: Report) -> list[str]:
    """Which channels the reference is made of, and which are absent or silent.

    Signed coherent contributions over the mix plateau (`ChannelDiagnosis.passband_share`),
    so they can be negative or exceed 100% under cancellation. A mix whose plateau is almost
    all centre, with an empty LFE, is a dialogue-led mix with no authored bass — a very
    different thing to restore than a bass-heavy one, and the reader needs to see it.
    """
    channels = sorted(
        report.diagnosis.channels.values(), key=lambda c: -abs(c.passband_share)
    )
    if not channels:
        return ["no per-channel decomposition was supplied"]
    carried = [c for c in channels if abs(c.passband_share) >= 0.005]
    parts = [
        "the plateau is carried by "
        + ", ".join(f"{c.name} {c.passband_share:.0%}" for c in carried)
        if carried
        else "no channel measurably carries the plateau"
    ]
    absent = [c.name for c in channels if abs(c.passband_share) < 0.005]
    if absent:
        verb = "contributes" if len(absent) == 1 else "contribute"
        parts.append(f"{', '.join(absent)} {verb} nothing to it")
    silent = [
        f"{name} is exact digital silence for {share:.0%} of the programme"
        for name, share in digital_silence(report.material).items()
        if share >= SILENCE_MENTION
    ]
    parts.extend(silent)
    return parts


def digital_silence(material, frame: int = 1024) -> dict[str, float]:
    """Each channel's share of frames that are exactly zero: absent programme, not quiet."""
    if material is None:
        return {}
    shares = {}
    for name, samples in material.channels.items():
        if len(samples) < frame:
            continue
        frames = np.lib.stride_tricks.sliding_window_view(samples, frame)[:: frame // 2]
        shares[name] = float(np.mean(~frames.any(axis=1)))
    return shares


def correction(candidate: Candidate) -> str:
    """What the chosen candidate was asked for, what it did, and what the low end became."""
    parts: list[str] = []
    asked = candidate.unpriced_target_db
    licensed = candidate.target_db
    if asked is not None and np.any(asked > 0):
        at = int(np.argmax(asked))
        parts.append(
            f"the deficit asks for up to {asked[at]:.1f} dB (at {_hz(DESIGN_GRID[at])}); "
            f"the measured evidence licenses up to {float(np.max(licensed)):.1f} dB"
        )
    recovered = candidate.verdict.recovered_fraction
    if math.isfinite(recovered):
        parts.append(f"{recovered:.0%} of the measured deficit is corrected")
    sections = ", ".join(
        f"{f.type} {f.freq_hz:g} Hz {f.gain_db:+.1f} dB Q {f.q:.2f}"
        for f in candidate.filters
    )
    parts.append(
        f"{candidate.label}: {len(candidate.filters)} section(s) — {sections}; "
        f"peak boost {candidate.mv_adjust_db:+.1f} dB"
    )

    c = candidate.correction
    points = [p for p in POINTS_HZ if c.freqs[0] <= p <= c.freqs[-1]]
    table = ", ".join(
        f"{p} Hz {np.interp(p, c.freqs, c.before_db):+.1f} → "
        f"{np.interp(p, c.freqs, c.after_db):+.1f}"
        for p in points
    )
    parts.append(f"low end against the reference, before → after (dB): {table}")

    shaping = candidate.verdict.shaping_fraction
    if math.isfinite(shaping) and shaping > 0:
        parts.append(
            f"{min(shaping, 1.0):.0%} of the correction lies below the level-invariance "
            "floor, where it rests on the preference for a flat result rather than on a "
            "measured filter"
        )
    return "; ".join(parts)


def alternatives(report: Report, chosen: Candidate | None) -> str:
    """One line per other candidate: rejected and why, or passed and why it was not chosen."""
    wanted = report.accept.target_tilt_db_per_octave
    ours = None if chosen is None else chosen.correction.departure_db(wanted)
    lines: list[str] = []
    for c in report.candidates:
        if c is chosen:
            continue
        if not c.verdict.passed:
            first = c.verdict.failures[0] if c.verdict.failures else "rejected"
            more = len(c.verdict.failures) - 1
            lines.append(
                f"{c.label} rejected: {first}"
                + (f" (+{more} more)" if more > 0 else "")
            )
        elif ours is not None:
            theirs = c.correction.departure_db(wanted)
            if abs(theirs - ours) > report.ranking_tie_db:
                why = (
                    f"its result departs {theirs:.1f} dB from the requested shape "
                    f"against {ours:.1f} dB"
                )
            elif len(c.filters) != len(chosen.filters):
                why = (
                    f"as flat as the chosen one ({theirs:.1f} against {ours:.1f} dB from the "
                    f"requested shape) but needs {len(c.filters)} sections against "
                    f"{len(chosen.filters)}"
                )
            else:
                why = (
                    f"tied on section count and within {report.ranking_tie_db:g} dB on "
                    f"flatness ({theirs:.1f} against {ours:.1f} dB); the flatter one was taken"
                )
            lines.append(f"{c.label} passed but was not chosen: {why}")
    return "; ".join(lines) if lines else "no other candidate was proposed"
