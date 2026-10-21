"""A channel's DC offset, and the steps in it a correction would turn into thumps (TODO 29, O1).

Reported, never decided on. A static offset needs nothing here: `measure_headroom` filters the
sub feed with the device's full transfer, 0 Hz included, so the lifted offset is already in the
measured peak. What it does not show is an offset that *steps*. Each step is an infrasonic
transient, and a correction boosting the bottom octaves lifts it by its gain there: Desperately
Seeking Susan's FR carries -48 dBFS of drifting offset whose steps stand 15-22 dB above FL in
4-20 Hz, heard as thumps once corrected. A DC-blocking high-pass would not help — at 1, 3 or
5 Hz it left those transients where they were, since a step's energy reaches far above any
blocker's corner — so the honest response is to say so.
"""

from dataclasses import dataclass

import numpy as np
from scipy import ndimage, signal

from beqforge.material import Material

STEP_BAND_HZ = (4.0, 20.0)
"""Where a step's transient is measured: the band a correction boosts most."""

LEVEL_HALF_WIDTH_S = 15
"""Half the window, in seconds, the slow DC level is the median over. Long enough that a scene's
bass does not move it, short enough to follow an offset that changes at an edit."""


@dataclass(frozen=True, slots=True)
class DcSteps:
    """One channel's offset and the steps in it that stand out of the programme."""

    channel: str
    offset_dbfs: float
    """The channel's typical slow DC level, re full scale."""
    steps_s: tuple[int, ...]
    """Where each step is, to the second."""
    worst_excess_db: float
    """How far the largest step's transient rises above the programme's own level in the band."""

    def note(self) -> str:
        times = ", ".join(f"{s // 60}:{s % 60:02d}" for s in self.steps_s[:5])
        more = f" and {len(self.steps_s) - 5} more" if len(self.steps_s) > 5 else ""
        return (
            f"DC offset: {self.channel} carries a {self.offset_dbfs:.0f} dBFS offset that steps "
            f"{len(self.steps_s)} time(s) (at {times}{more}); each step is an infrasonic "
            f"transient up to {self.worst_excess_db:.1f} dB above the programme's own "
            f"{STEP_BAND_HZ[0]:g}-{STEP_BAND_HZ[1]:g} Hz level, and a correction boosting that "
            "band lifts it by its gain there, as a thump; headroom already counts the offset "
            "itself"
        )


def dc_steps(material: Material) -> list[DcSteps]:
    """The channels whose DC offset steps audibly, by three tests and no dB constant.

    A channel qualifies when its slow DC level (the median of per-second means over
    `LEVEL_HALF_WIDTH_S` either side) is persistently large enough that a step in it would reach
    the programme: the band's response to a step of that size exceeds the 90th percentile of the
    channel's per-second peak in `STEP_BAND_HZ`, the level its own programme regularly reaches
    there. Each step reported is a change in that level whose transient exceeds it too, and, with
    other channels to compare, near which this channel's band level stands out of every other's:
    programme bass arrives in several channels at once, a step in one channel's offset does not.

    The 90th percentile, not the median, because a sparse channel — an LFE silent most of the
    time — has a median near nothing, and every small drift cleared it. The persistent offset,
    because an LFE carries infrasonic content no other channel does, so it always stands out.
    On 34 titles at hand only Desperately Seeking Susan's FR qualifies.
    """
    fs = int(material.fs)
    if not material.channels or fs <= 2 * STEP_BAND_HZ[1]:
        return []
    seconds = min(len(x) for x in material.channels.values()) // fs
    if seconds <= 2 * LEVEL_HALF_WIDTH_S:
        return []
    band = signal.butter(4, STEP_BAND_HZ, btype="band", fs=fs, output="sos")
    unit_step = np.r_[np.zeros(4 * fs), np.ones(4 * fs)]
    step_gain = float(np.max(np.abs(signal.sosfilt(band, unit_step))))
    peaks = {
        name: np.abs(signal.sosfilt(band, np.asarray(x, dtype=np.float64)))[
            : seconds * fs
        ]
        .reshape(seconds, fs)
        .max(axis=1)
        for name, x in material.channels.items()
    }
    found: list[DcSteps] = []
    for name, x in material.channels.items():
        means = (
            np.asarray(x[: seconds * fs], dtype=np.float64)
            .reshape(seconds, fs)
            .mean(axis=1)
        )
        level = ndimage.median_filter(
            means, size=2 * LEVEL_HALF_WIDTH_S + 1, mode="nearest"
        )
        programme = float(np.percentile(peaks[name], 90))
        offset = float(np.median(np.abs(level)))
        if programme <= 0.0 or offset * step_gain <= programme:
            continue
        shift = np.zeros(seconds)
        shift[LEVEL_HALF_WIDTH_S : seconds - LEVEL_HALF_WIDTH_S] = (
            level[2 * LEVEL_HALF_WIDTH_S :] - level[: seconds - 2 * LEVEL_HALF_WIDTH_S]
        )
        candidates, _ = signal.find_peaks(
            np.abs(shift), distance=2 * LEVEL_HALF_WIDTH_S
        )
        others = [peaks[k] for k in material.channels if k != name]
        steps: list[int] = []
        worst = 0.0
        for centre in candidates:
            transient = abs(float(shift[centre])) * step_gain
            if transient <= programme:
                continue
            window = slice(
                max(centre - LEVEL_HALF_WIDTH_S, 1),
                min(centre + LEVEL_HALF_WIDTH_S + 1, seconds),
            )
            if others and peaks[name][window].max() <= max(
                o[window].max() for o in others
            ):
                continue
            # to the second: the largest jump between consecutive means in the window
            jumps = np.abs(np.diff(means[window.start - 1 : window.stop]))
            steps.append(int(window.start + np.argmax(jumps)))
            worst = max(worst, 20.0 * np.log10(transient / programme))
        if steps:
            found.append(
                DcSteps(name, 20.0 * np.log10(offset), tuple(steps), float(worst))
            )
    return found
