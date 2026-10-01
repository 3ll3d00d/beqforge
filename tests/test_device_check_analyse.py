import numpy as np

from beqforge_device_check.analyse import catalogue_summary, compare, summarise


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
