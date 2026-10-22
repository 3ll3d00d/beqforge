"""E10's synthetic cases and scorer: what the arrays say, not what the pipeline does with them."""

from types import SimpleNamespace

import numpy as np
import pytest

from beqforge import BiquadSpec, e10
from beqforge.pipeline import PipelineParams


def _report(*filters: BiquadSpec, drift_db: float = 0.1):
    if not filters:
        return SimpleNamespace(accepted=None, evidence_notes=("withheld",))
    selected = SimpleNamespace(
        label="flatten",
        filters=list(filters),
        verdict=SimpleNamespace(drift_db=drift_db),
    )
    return SimpleNamespace(accepted=selected, evidence_notes=())


BOOST = BiquadSpec("low_shelf", 25.0, 12.0, 0.707)


@pytest.mark.parametrize("family", e10.FAMILIES)
def test_every_family_is_reproducible_from_its_seed(family):
    one = e10.e10_case(family, 3, duration_s=20.0)
    two = e10.e10_case(family, 3, duration_s=20.0)
    assert one.change == two.change
    for name in one.observed:
        np.testing.assert_array_equal(one.observed[name], two.observed[name])
        np.testing.assert_array_equal(one.noise[name], two.noise[name])
    assert e10.e10_case(family, 4, duration_s=20.0).change is not None


def test_the_development_and_held_out_blocks_do_not_overlap():
    assert not set(e10.DEVELOPMENT_SEEDS) & set(e10.HELD_OUT_SEEDS)
    # the corpus's seeds 1-9 are development
    assert set(range(1, 10)) <= set(e10.DEVELOPMENT_SEEDS)


def test_a_filtered_case_needs_a_correction_and_noise_alone_does_not():
    filtered = e10.truth(e10.e10_case("filtered", 1), "flat")
    assert filtered.needs_correction and filtered.truth_band.any()
    noise = e10.truth(e10.e10_case("stationary_noise", 1), "flat")
    assert not noise.needs_correction
    assert not noise.truth_band.any() and noise.noise_only.any()


def test_a_steep_coloured_floor_leaves_noise_only_bins_below_the_corner():
    known = e10.truth(e10.e10_case("coloured_floor", 2), "flat")
    assert known.noise_only.any()
    # the noise-only bins sit below every truth-band bin
    assert known.freqs[known.noise_only].max() < known.freqs[known.truth_band].min()


def test_a_gentle_goal_asks_for_less_than_a_flat_one():
    case = e10.e10_case("natural_droop", 5)
    flat, gentle = e10.truth(case, "flat"), e10.truth(case, "gentle")
    below = flat.freqs < e10.REFERENCE_HZ[0]
    assert np.all(gentle.goal_db[below] < flat.goal_db[below])


def test_abstaining_on_a_case_that_needs_correction_is_a_missed_recovery():
    case = e10.e10_case("filtered", 1)
    row = e10.score(case, "flat", _report(), PipelineParams())
    assert row["missed"] and not any(row[c] for c in e10.SAFETY)
    assert row["shortfall_median_db"] > 0


def test_a_boost_on_noise_alone_is_noise_lift_and_unnecessary():
    case = e10.e10_case("stationary_noise", 1)
    row = e10.score(case, "flat", _report(BOOST), PipelineParams())
    assert row["noise_lift"] and row["unnecessary"]
    assert row["noise_lift_db"] > e10.NOISE_LIFT_DB


def test_drift_past_the_judges_limit_is_a_device_failure():
    case = e10.e10_case("filtered", 1)
    row = e10.score(case, "flat", _report(BOOST, drift_db=9.0), PipelineParams())
    assert row["device_failure"]


def test_the_summary_counts_each_class_over_the_cases_exposed_to_it():
    params = PipelineParams()
    rows = [
        e10.score(e10.e10_case("stationary_noise", 1), "flat", _report(BOOST), params),
        e10.score(e10.e10_case("filtered", 1), "flat", _report(), params),
    ]
    pooled = e10.summarise(rows)["flat"]["pooled"]
    assert pooled["unnecessary"] == {"k": 1, "n": 1, "upper": 1.0, "lower": 0.025}
    assert pooled["missed"]["k"] == 1 and pooled["missed"]["n"] == 1
    assert pooled["noise_lift"]["k"] == 1


def test_the_interval_matches_the_protocols_sample_sizes():
    assert e10.clopper_pearson(0, 72)[1] == pytest.approx(0.050, abs=0.001)
    assert e10.clopper_pearson(0, 36)[1] == pytest.approx(0.097, abs=0.001)
