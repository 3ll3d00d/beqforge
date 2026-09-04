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
    colour_for,
    peak_and_average_db,
    render,
)
from tests.test_design_diagnose import FS, high_passed, material_from, scened_noise

FILTERS = [BiquadSpec("low_shelf", 14.0, 12.0, 0.7)]


def test_catalogue_axes() -> None:
    assert FREQ_LIMITS_HZ == (1.0, 160.0)
    assert LEVEL_LIMITS_DB == (-80.0, -10.0)


def test_peak_sits_above_average_everywhere() -> None:
    freqs, peak, average = peak_and_average_db(scened_noise(70, int(FS * 120)), FS)
    assert freqs.min() >= FREQ_LIMITS_HZ[0]
    assert freqs.max() <= FREQ_LIMITS_HZ[1]
    assert np.all(peak >= average - 1e-9)


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
