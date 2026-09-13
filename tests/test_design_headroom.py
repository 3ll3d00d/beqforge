"""Missing channel decomposition cannot establish clipping headroom."""

import math

import numpy as np
import pytest

from beqanalyser.design import BiquadSpec, record
from beqanalyser.design.accept import assess
from beqanalyser.design.material import Material, bass_managed_sum
from beqanalyser.design.pipeline import PipelineParams, required_gain_reduction_db
from tests.test_design_accept import correction
from tools.design_beq import _headroom


@pytest.mark.parametrize(
    "channels_available, amplitude", [(False, 0.9), (True, 0.9), (True, 0.0)]
)
def test_headroom_distinguishes_unknown_clipping_and_silence(
    channels_available, amplitude
):
    samples = amplitude * np.sin(2 * np.pi * 10 * np.arange(10000) / 1000)
    material = Material(
        "headroom",
        1000,
        samples,
        {"LFE": samples} if channels_available else {},
        "complete_programme",
    )
    filters = [BiquadSpec("low_shelf", 30.0, 20.0, 0.707)]
    offset = required_gain_reduction_db(material, filters, PipelineParams())
    if not channels_available:
        assert bass_managed_sum(material) is None
        assert math.isnan(offset)
        assert "unavailable" in _headroom(offset)
    elif amplitude:
        assert offset < 0.0
        assert "needs" in _headroom(offset)
    else:
        assert offset == 0.0
        assert _headroom(offset) == "no gain reduction needed"


def test_unavailable_headroom_remains_unknown_in_the_verdict_and_record():
    verdict = assess(
        [BiquadSpec("low_shelf", 17.0, 11.5, 0.73)],
        correction(lambda f: 0.0 if f >= 23.0 else -13.0, lambda f: -1.5),
        noise_floor_hz=math.nan,
        required_offset_db=math.nan,
    )
    assert verdict.passed, verdict.failures
    assert math.isnan(verdict.required_offset_db)
    assert record._verdict(verdict)["required_offset_db"] is None
