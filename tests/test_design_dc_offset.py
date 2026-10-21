"""A DC offset that steps is reported, and nothing else is (TODO 29, O1)."""

import numpy as np
from scipy import signal

from beqforge.dc_offset import dc_steps
from beqforge.material import Material

FS = 1000
SECONDS = 600


def _programme(seed: int) -> np.ndarray:
    """Programme with a 30-120 Hz bass passband: like a real mix, little of it below 20 Hz."""
    rng = np.random.default_rng(seed)
    return 0.01 * signal.sosfilt(
        signal.butter(2, (30.0, 120.0), btype="band", fs=FS, output="sos"),
        rng.standard_normal(SECONDS * FS),
    )


def _stepping_offset() -> np.ndarray:
    """Desperately Seeking Susan's FR, roughly: an offset near -47 dBFS changing at edits."""
    levels = np.repeat([4e-3, 9e-3, 2e-3, 7e-3, 4e-3], SECONDS * FS // 5)
    return levels


def _material(channels: dict[str, np.ndarray]) -> Material:
    mix = sum(channels.values()) / len(channels)
    return Material("dc", FS, mix, channels, "complete_programme")


def test_a_stepping_offset_on_one_channel_is_reported():
    found = dc_steps(
        _material({"L": _programme(1), "R": _programme(2) + _stepping_offset()})
    )
    assert [steps.channel for steps in found] == ["R"]
    assert len(found[0].steps_s) == 4
    for step, edit in zip(found[0].steps_s, (120, 240, 360, 480), strict=True):
        assert abs(step - edit) <= 1
    assert "thump" in found[0].note()


def test_programme_without_an_offset_reports_nothing():
    assert dc_steps(_material({"L": _programme(1), "R": _programme(2)})) == []


def test_a_sparse_channel_is_not_an_offset():
    """An LFE silent most of the time stands out of the other channels whenever it plays.

    Its median level is near nothing, so measured against that every drift was a step; and it
    carries infrasonic content no other channel does, so the cross-channel test alone passes it.
    """
    lfe = np.zeros(SECONDS * FS)
    rng = np.random.default_rng(7)
    for start in rng.integers(0, SECONDS - 5, 12):
        burst = signal.sosfilt(
            signal.butter(4, 30.0, btype="low", fs=FS, output="sos"),
            rng.standard_normal(4 * FS),
        )
        lfe[start * FS : start * FS + 4 * FS] += 0.05 * burst
    found = dc_steps(_material({"L": _programme(1), "R": _programme(2), "LFE": lfe}))
    assert found == []


def test_a_mono_channel_with_a_stepping_offset_is_reported():
    """With nothing to compare it against, the offset and its steps decide on their own."""
    found = dc_steps(_material({"C": _programme(3) + _stepping_offset()}))
    assert [steps.channel for steps in found] == ["C"]
