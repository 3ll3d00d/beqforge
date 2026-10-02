import numpy as np

from beqforge_device_check.analyse import (
    catalogue_summary,
    compare,
    compare_traces,
    frequency_population,
    sample_trace,
    summarise,
)


def trace(frequencies, values, mask, *, level=-30, attempt="a"):
    return {
        "frequencies": frequencies,
        "delta_exact_db": values,
        "mask": mask,
        "uncertainty_db": [0.01] * len(frequencies),
        "level_dbfs": level,
        "attempt": attempt,
    }


def test_matching_grids_never_bridge_missing_bins_or_extrapolate():
    data = trace([2, 4, 6, 8], [0.1, 0.2, None, 0.4], [True, True, False, True])
    values, budget, mask = sample_trace(data, np.array([1, 2, 3, 4, 5, 6, 7, 8, 9]))
    assert mask.tolist() == [False, True, True, True, False, False, False, True, False]
    assert np.isclose(values[2], 0.15)
    assert budget[2] == 0.01


def test_matched_comparison_retains_reload_pairs_levels_sign_and_denominators():
    left = [
        trace([2, 3, 4, 5, 6], [0.1] * 5, [True] * 5, attempt=a) for a in ("a", "b")
    ]
    left.append(trace([2, 4], [0, 0], [True, True], level=-50))
    right = [trace([2, 4, 6], [0.3, 0.3, None], [True, True, False], attempt="c")]
    result = compare_traces(left, right, 0, 1)
    assert len(result["pairs"]) == 2
    assert result["unmatched_left_levels"] == [-50]
    pair = result["pairs"][0]
    assert pair["qualified_pair_bins"] == 3
    assert pair["outside_common_mask_bins"] == 2
    assert pair["bins_exceeding_combined_uncertainty"] == 3
    assert np.allclose(pair["delta_right_minus_left_db"][:3], 0.2)
    assert pair["delta_right_minus_left_db"][3:] == [None, None]
    assert pair["combined_uncertainty_db"][:3] == [0.02] * 3


def test_disjoint_qualified_bands_are_reported_under_range():
    left = trace([2, 4, 6], [0, None, None], [True, False, False])
    right = trace([2, 4, 6], [None, None, 1], [False, False, True])
    pair = compare_traces([left], [right], 0, 1)["pairs"][0]
    assert pair["summary"]["status"] == "under-range"
    assert pair["qualified_pair_bins"] == 0


def test_catalogue_frequency_denominators_count_entries_and_cascades_not_reloads():
    inventory = {"entries": [{"case": "same"}, {"case": "same"}, {"case": "other"}]}
    one = {**trace([2, 4, 6], [0.2, 0.2, 0.2], [True] * 3), "status": "measured"}
    two = {
        **trace([2, 4, 6], [None, None, -0.4], [False, False, True]),
        "status": "measured",
    }
    result = frequency_population(inventory, {"same": [one, one], "other": [two]}, 0.1)
    assert result["unique_cascade_weighted"][0]["count"] == 1
    assert result["entry_weighted"][0]["count"] == 2
    assert result["unique_cascade_weighted"][-1]["count"] == 2
    assert result["entry_weighted"][-1]["count"] == 3
    assert result["unique_cascade_weighted"][-1]["maximum_db"] == 0.4


def test_masked_gaps_are_not_excursions_or_zero_error():
    frequencies = np.geomspace(2, 200, 8)
    delta = np.array([0.5, 0.5, 20, 20, -0.5, -0.5, 0, 0])
    mask = np.array([1, 1, 0, 0, 1, 1, 1, 1], dtype=bool)
    result = summarise(frequencies, delta, mask, 0.1)
    assert result["worst_db"] == 0.5
    assert len(result["excursions"]) == 2
    assert result["coverage"] == 0.75
    assert summarise(frequencies, delta, mask * False, 0.1)["status"] == "under-range"


def test_comparison_exposes_unmatched_cases_and_distinct_configuration():
    base = {
        "engine": {"engine": "test"},
        "bench_hash": "a",
        "scope": "numerical",
        "results": [
            {"match_key": "common", "status": "measured"},
            {"match_key": "other", "status": "measured"},
        ],
    }
    second = {
        **base,
        "bench_hash": "b",
        "results": [{"match_key": "common", "status": "measured"}],
    }
    result = compare([base, second])
    assert len(result["matched_cases"]) == 1
    assert result["unmatched_counts"] == [1, 0]


def test_catalogue_versions_and_reloads_do_not_inflate_unique_cascade_count():
    inventory = {
        "source": {"complete_snapshot_declared": True},
        "entries": [
            {"id": "version-a", "case": "same", "status": "planned"},
            {"id": "version-b", "case": "same", "status": "planned"},
            {"id": "unsupported", "status": "unsupported", "reason": "capacity"},
        ],
    }
    report = {
        "complete": True,
        "accuracy_db": 0.1,
        "results": [
            {"case": "same", "status": "measured", "exact": {"worst_db": value}}
            for value in (0.02, 0.03, 0.01)
        ],
    }
    result = catalogue_summary(inventory, report)
    assert result["entry_weighted"]["count"] == 2
    assert result["unique_cascade_weighted"]["count"] == 1
    assert result["counts"] == {
        "measured": 2,
        "unsupported": 1,
        "under-range": 0,
        "incomplete": 0,
    }
    assert result["complete"]
