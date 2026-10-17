"""The mix's texture yardstick is measured about a cubic, not a line (9, 2009, 2026-10)."""

import numpy as np
from scipy import signal

from beqforge.material import Material
from beqforge.pipeline import (
    MIX_TEXTURE_TREND_DEGREE,
    PipelineParams,
    passband_ripple_db,
)

FS = 1000


def _programme(knee_hz: float | None, seed: int = 5) -> Material:
    """Noise high-passed at 20 Hz whose level falls away above `knee_hz`, if given.

    The knee stands in for an LFE-led mix, where the level drops where the LFE channel's content
    ends: real programme shape, but not texture the sub plays.
    """
    rng = np.random.default_rng(seed)
    high_pass = signal.butter(4, 20.0, btype="high", fs=FS, output="sos")
    bass = signal.sosfilt(high_pass, rng.standard_normal(240 * FS))
    if knee_hz is not None:
        bass = signal.sosfilt(
            signal.butter(4, knee_hz, btype="low", fs=FS, output="sos"), bass
        )
    mains = 0.05 * signal.sosfilt(high_pass, rng.standard_normal(bass.size))
    return Material("programme", FS, 0.01 * (bass + mains), {}, "complete_programme")


def test_a_knee_above_the_crossover_is_trend_not_texture():
    material, params = _programme(70.0), PipelineParams()
    line = passband_ripple_db(material, params)
    cubic = passband_ripple_db(material, params, trend_degree=MIX_TEXTURE_TREND_DEGREE)
    assert line is not None and cubic is not None
    assert cubic[0] < line[0] - 3.0


def test_the_band_is_the_one_the_boundary_was_calibrated_on():
    params = PipelineParams()
    cubic = passband_ripple_db(
        _programme(70.0), params, trend_degree=MIX_TEXTURE_TREND_DEGREE
    )
    assert cubic is not None and cubic[1][1] == params.diagnose.band_hz[1]


def test_programme_without_a_knee_keeps_its_texture():
    # the cubic must not explain away texture a line already measured: on broadband noise
    # the two agree
    material, params = _programme(None), PipelineParams()
    line = passband_ripple_db(material, params)
    cubic = passband_ripple_db(material, params, trend_degree=MIX_TEXTURE_TREND_DEGREE)
    assert line is not None and cubic is not None
    assert abs(cubic[0] - line[0]) < 0.25 * line[0]
