"""The guard: what stops `flatten` inverting a noise floor.

`flatten` has no opinion of its own — it inverts whatever the mix shows. On modern bass-rich
material that is content and the answer is right; on sparse or old material the low end is a
noise floor and flattening would lift it. None of the three real titles can test this, because
none is noise dominated, so the case is constructed here.

Constructed, not inferred: content and floor are separately synthesised at a known crossover,
so "where does the guard think content stops" has a right answer to compare against.
"""

from unittest import mock

import numpy as np
import pytest
from scipy import signal

from beqanalyser.design.diagnose import (
    DiagnoseParams,
    _octave_bands,
    band_tracking,
    diagnose,
)
from beqanalyser.design.pipeline import DESIGN_GRID, PipelineParams, flatten_targets
from tests.test_design_diagnose import FS, high_passed, material_from, scened_noise

PARAMS = DiagnoseParams()


def noise_dominated(corner_hz: float, floor_db: float, seed: int = 40) -> np.ndarray:
    """Programme content high-passed at `corner_hz`, over a stationary floor.

    Below the corner the content is gone and only the floor remains, so anything the mix shows
    down there is noise by construction.
    """
    rng = np.random.default_rng(seed)
    samples = int(FS * 600.0)
    content = high_passed(scened_noise(seed + 1, samples), corner_hz, order=8)
    floor = (
        rng.standard_normal(samples)
        * np.sqrt(np.mean(content**2))
        * 10.0 ** (floor_db / 20.0)
    )
    return content + floor


def test_band_tracking_sees_the_floor_and_not_the_content() -> None:
    """The measurement the guard rests on, checked against a known crossover."""
    mixed = noise_dominated(corner_hz=30.0, floor_db=-26.0)
    in_content = band_tracking(mixed, FS, (34.0, 46.0), PARAMS)
    in_floor = band_tracking(mixed, FS, (7.0, 13.0), PARAMS)
    assert in_content > PARAMS.tracking_floor
    assert in_floor < in_content


def test_a_noise_dominated_low_end_reports_a_floor() -> None:
    material = material_from(
        {
            "C": noise_dominated(corner_hz=30.0, floor_db=-26.0),
            "LFE": noise_dominated(corner_hz=30.0, floor_db=-26.0, seed=60),
        }
    )
    result = diagnose(material)
    assert not np.isnan(result.noise_floor_hz), "guard found no floor at all"
    assert result.noise_floor_hz > PARAMS.band_hz[0]


def test_flatten_does_not_chase_the_floor_below_it() -> None:
    """The consequence that matters: the target stops rising where the content stops."""
    material = material_from(
        {
            "C": noise_dominated(corner_hz=30.0, floor_db=-26.0),
            "LFE": noise_dominated(corner_hz=30.0, floor_db=-26.0, seed=60),
        }
    )
    diagnosis = diagnose(material)
    proposals = flatten_targets(material, diagnosis, None, None, PipelineParams())
    if not proposals:
        pytest.skip("no correction proposed at all, which is also a safe outcome")
    target = proposals[0].target_db
    floor = diagnosis.noise_floor_hz
    assert not np.isnan(floor)
    below = DESIGN_GRID < floor
    assert below.any()
    # held flat below the floor rather than continuing to climb
    assert np.ptp(target[below]) < 0.5


def masked_knee(floor_db: float, seed: int = 40) -> np.ndarray:
    """A real wall, with a floor loud enough to flatten the slope it presents.

    The knee test reads the steepest half-octave of a channel's own response. A floor holds
    the bottom of that response up, so the louder the floor the shallower the wall looks —
    at -6 dB and above nothing clears `knee_slope_db_per_octave` even though the content
    below 20 Hz is as absent as it was at -26 dB.
    """
    rng = np.random.default_rng(seed)
    samples = int(FS * 600.0)
    content = high_passed(scened_noise(seed + 1, samples), 30.0, order=8)
    floor = (
        rng.standard_normal(samples)
        * np.sqrt(np.mean(content**2))
        * 10.0 ** (floor_db / 20.0)
    )
    return content + floor


def test_the_floors_are_measured_without_a_filtered_channel() -> None:
    """The guard asks about the material, so a knee is not a precondition for asking.

    Nesting the floors inside the filtered branch meant the one case that needs them most —
    material with no channel steep enough to be called filtered — was the one case they were
    never computed for, and `assess` then fell back to demanding a correction down to the
    bottom of the band.
    """
    material = material_from(
        {"C": masked_knee(-6.0), "LFE": masked_knee(-6.0, seed=60)}
    )
    result = diagnose(material)
    assert not result.filtered_channels, "expected no channel to clear the knee test"
    assert not np.isnan(result.noise_floor_hz), "floors not measured without a knee"
    assert not np.isnan(result.filter_floor_hz)


def test_band_tracking_agrees_with_the_true_content_to_floor_ratio() -> None:
    """Scored against ground truth rather than against itself.

    Content and floor are synthesised separately, so each band's true content-to-floor ratio
    is known and the measurement can be marked right or wrong rather than merely plausible.
    Bands within 3 dB either way are genuinely ambiguous and are not scored.
    """
    rng = np.random.default_rng(40)
    samples = int(FS * 600.0)
    content = high_passed(scened_noise(41, samples), 30.0, order=8)
    floor = (
        rng.standard_normal(samples)
        * np.sqrt(np.mean(content**2))
        * 10.0 ** (-26.0 / 20.0)
    )

    def band_power_db(x: np.ndarray, low: float, high: float) -> float:
        sos = signal.butter(4, [low, high], btype="band", fs=FS, output="sos")
        return float(10.0 * np.log10(np.mean(signal.sosfiltfilt(sos, x) ** 2) + 1e-300))

    scored = 0
    for low, high in _octave_bands(PARAMS.band_hz[0], PARAMS.passband_hz[0]):
        margin = band_power_db(content, low, high) - band_power_db(floor, low, high)
        if abs(margin) <= 3.0:
            continue
        scored += 1
        tracks = band_tracking(content + floor, FS, (low, high), PARAMS)
        assert (tracks >= PARAMS.tracking_floor) == (margin > 0.0), (
            f"{low:.1f}-{high:.1f} Hz is {margin:+.1f} dB content-to-floor "
            f"but tracking says {tracks:+.3f}"
        )
    assert scored >= 3, "not enough unambiguous bands to score"


def test_an_unmeasurable_band_terminates_the_search() -> None:
    """NaN is not evidence of content.

    `band_tracking` returns NaN when the passband is never live enough to correlate against.
    Read as "not below the floor" that becomes a claim that content continues, which is the
    expensive direction to be wrong in.
    """
    material = material_from({"C": masked_knee(-26.0), "LFE": masked_knee(-26.0, 60)})
    with mock.patch(
        "beqanalyser.design.diagnose.band_tracking", return_value=float("nan")
    ):
        result = diagnose(material)
    assert not np.isnan(result.noise_floor_hz), (
        "an unmeasurable band was read as content"
    )
