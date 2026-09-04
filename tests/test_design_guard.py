"""The guard: what stops `flatten` inverting a noise floor.

`flatten` has no opinion of its own — it inverts whatever the mix shows. On modern bass-rich
material that is content and the answer is right; on sparse or old material the low end is a
noise floor and flattening would lift it. None of the three real titles can test this, because
none is noise dominated, so the case is constructed here.

Constructed, not inferred: content and floor are separately synthesised at a known crossover,
so "where does the guard think content stops" has a right answer to compare against.
"""

import numpy as np
import pytest

from beqanalyser.design.diagnose import DiagnoseParams, band_tracking, diagnose
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
