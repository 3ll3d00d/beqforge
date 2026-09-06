"""PvA charts: axes, colour stability, and channel selection.

The picture is debug output, so what matters is that it is comparable — same axes as the
catalogue publishes, and the same colour for a channel in every chart of every run. A legend
that means something different from one chart to the next is worse than none.
"""

import numpy as np

from beqanalyser.design import BiquadSpec
from beqanalyser.design.charts import (
    CHANNEL_COLOURS,
    FREQ_LIMITS_HZ,
    LEVEL_LIMITS_DB,
    NPERSEG,
    colour_for,
    programme_levels_db,
    render,
)
from tests.test_design_diagnose import FS, high_passed, material_from, scened_noise

FILTERS = [BiquadSpec("low_shelf", 14.0, 12.0, 0.7)]


def test_catalogue_axes() -> None:
    assert FREQ_LIMITS_HZ == (1.0, 160.0)
    assert LEVEL_LIMITS_DB == (-80.0, -10.0)


def test_peak_sits_above_average_everywhere() -> None:
    levels = programme_levels_db(scened_noise(70, int(FS * 120)), FS)
    assert levels.freqs.min() >= FREQ_LIMITS_HZ[0]
    assert levels.freqs.max() <= FREQ_LIMITS_HZ[1]
    assert np.all(levels.peak >= levels.average - 1e-9)


def test_loudest_second_mostly_sits_under_the_peak_hull() -> None:
    """It sits well under the hull, but is not bounded by it, and that is not a bug.

    The hull maximises on the coarse grid (50% overlap, one frame per 2 s); the second
    maximises at `LOUDEST_HOP`. Neither set of frames contains the other, so a transient
    landing between two coarse centres — where the Hann taper attenuates it — is caught by
    the fine grid and not by the hull. Measured on a real title the second exceeds the hull
    in 5-13% of bins by up to 3.5 dB, against a mean gap of −7 to −8 dB the other way.
    """
    levels = programme_levels_db(scened_noise(70, int(FS * 120)), FS)
    over = levels.loudest_second - levels.peak
    assert float(np.mean(over)) < 0.0
    assert float(np.mean(over > 0.0)) < 0.5
    assert levels.loudest_index >= 0


def test_loudest_second_is_the_highest_energy_one() -> None:
    """A burst planted in one place is the moment that gets picked."""
    samples = scened_noise(75, int(FS * 120)) * 0.01
    start, span = 40 * int(FS), 2 * NPERSEG
    samples[start : start + span] *= 200.0
    hop = NPERSEG // 2
    picked = programme_levels_db(samples, FS).loudest_index * hop
    # any frame lying wholly inside the burst is a valid answer
    assert start <= picked <= start + span - NPERSEG


def test_frame_index_pins_the_choice() -> None:
    """The filtered curve must be the same moment, not whichever event the boost favours."""
    samples = scened_noise(76, int(FS * 120))
    chosen = programme_levels_db(samples, FS, frame_index=7)
    assert chosen.loudest_index == 7
    assert not np.allclose(
        chosen.loudest_second, programme_levels_db(samples, FS).loudest_second
    )


def test_colours_are_stable_and_distinct() -> None:
    """A channel is the same colour in every chart, and no two share one."""
    named = [colour_for(c) for c in ("L", "R", "C", "LFE", "Lb", "Rb", "Ls", "Rs")]
    assert len(set(named)) == len(named)
    assert colour_for("LFE") == colour_for("LFE") == CHANNEL_COLOURS["LFE"]
    assert colour_for("unknown") == colour_for("unknown")  # stable fallback


def test_render_writes_both_charts_and_omits_ignored_channels(tmp_path) -> None:
    samples = int(FS * 120)
    material = material_from(
        {
            "C": scened_noise(71, samples),
            "LFE": high_passed(scened_noise(72, samples), 20.0, order=6),
            "Ls": scened_noise(73, samples) * 0.02,
        }
    )
    written = render("flatten", FILTERS, material, ["C", "LFE"], tmp_path / "x")
    assert len(written) == 2
    assert {p.name for p in written} == {"flatten_mono.png", "flatten_channels.png"}
    assert all(p.exists() and p.stat().st_size > 5000 for p in written)


def test_render_copes_with_no_relevant_channels(tmp_path) -> None:
    material = material_from({"C": scened_noise(74, int(FS * 60))})
    written = render("flatten", FILTERS, material, [], tmp_path / "y")
    assert len(written) == 1  # the mono chart is always worth having


def test_loudest_second_is_unbiased_where_the_hull_is_not() -> None:
    """The point of the second: a max over ~8 frames costs ~0 dB, over thousands it costs ~9.

    A periodogram bin is chi-squared with two degrees of freedom, so `peak` reads high on
    stationary material carrying no events at all. `loudest_second` does not, which is what
    makes it readable as a moment rather than as a statistic.
    """
    noise = np.random.default_rng(0).standard_normal(int(FS * 600))
    levels = programme_levels_db(noise, FS)
    assert np.mean(levels.peak - levels.average) > 7.0
    assert abs(float(np.mean(levels.loudest_second - levels.average))) < 1.5
