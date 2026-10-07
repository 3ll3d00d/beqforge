"""Publication statistics must describe emitted replacements, never rejected trials."""

import json
from itertools import pairwise

import numpy as np

from beqoptimiser.cli import optimise_entry
from tools.optimiser_catalogue_report import (
    cascades,
    job_key,
    replacement_cascade,
    statistics,
    title_key,
)


def entry():
    return {
        "title": "Example",
        "year": 2000,
        "filters": [{"type": "LowShelf", "freq": 20, "q": 0.7, "gain": 4}],
    }


def test_unpublished_candidate_keeps_original():
    baseline = np.ones((1, 6))
    report = {"variant": None, "result": {"candidate_error_db": 0.1}}
    assert replacement_cascade(report, baseline) is baseline


def test_published_additive_feedback_decodes():
    report = {"variant": {"biquads": [{"b": ["1", "2", "3"], "a": [".4", "-.5"]}]}}
    np.testing.assert_array_equal(
        replacement_cascade(report, None), [[1, 2, 3, 1, -0.4, 0.5]]
    )


def test_cached_baseline_matches_cli_policy():
    value = entry()
    reference, baseline = cascades(value, 48000)
    value["filters"][0]["biquads"] = {
        "48000": {
            "b": [str(v) for v in reference[0, :3]],
            "a": [str(-v) for v in reference[0, 4:]],
        }
    }
    cached_reference, cached_baseline = cascades(value, 48000)
    np.testing.assert_array_equal(cached_reference, reference)
    np.testing.assert_array_equal(cached_baseline, baseline)
    assert optimise_entry(value, rate=48000)["baseline_source"] == "published"
    value["filters"] = json.dumps(value["filters"])
    np.testing.assert_array_equal(cascades(value, 48000)[1], baseline)


def test_statistics_include_unchanged_failure_tail():
    before = np.array([[1.0, 2.0], [8.0, 12.0]])
    after = np.array([[0.1, 0.2], [8.0, 12.0]])
    stats = statistics(before, after)
    assert stats["maximum"]["after"] == [8.0, 12.0]
    assert stats["median"]["after"] == [4.05, 6.1]


def test_dedup_preserves_rate_and_filter_but_ignores_title():
    original = entry()
    renamed = {**original, "title": "Other"}
    assert job_key(original, 48000, "code") == job_key(renamed, 48000, "code")
    assert job_key(original, 48000, "code") != job_key(original, 96000, "code")
    assert job_key(original, 48000, "code") != job_key(original, 48000, "changed")
    assert title_key(original) != title_key(renamed)


def test_cached_search_preserves_exact_response_and_falls_back():
    from beqoptimiser import Section, magnitude
    from tools.optimiser_catalogue_report import cached_search_magnitude

    for rate in (48000, 96000):
        cached = cached_search_magnitude(rate, magnitude)
        cascade = np.asarray(
            [
                Section("LowShelf", 12, 0.7, 10).sos(rate),
                Section("PeakingEQ", 22, 2, -3).sos(rate),
            ]
        )
        for points in (512, 8192):
            frequencies = np.geomspace(2, 200, points)
            np.testing.assert_array_equal(
                cached(cascade, frequencies, rate),
                magnitude(cascade, frequencies, rate),
            )
            changed = cascade.copy()
            changed[0, 0] = np.nextafter(np.float32(changed[0, 0]), np.float32(np.inf))
            np.testing.assert_array_equal(
                cached(changed, frequencies, rate),
                magnitude(changed, frequencies, rate),
            )


def test_accelerated_worker_matches_library_result_exactly(tmp_path):
    from tools.optimiser_catalogue_report import evaluate

    value = entry()
    value["filters"] = [{"type": "PeakingEQ", "freq": 10, "q": 2, "gain": 12}]
    expected = optimise_entry(value, rate=48000)
    _, actual = evaluate(("test", value, 48000, str(tmp_path)))
    assert actual == json.loads(json.dumps(expected))
    assert evaluate(("test", value, 48000, str(tmp_path)))[1] == actual


def test_checked_in_catalogue_report_is_complete_and_respects_publication_policy():
    import gzip
    from pathlib import Path

    import pytest

    report = Path(__file__).resolve().parents[1] / "docs" / "optimiser-report"
    if not report.exists():
        pytest.skip("whole-catalogue report has not been generated yet")
    summary = json.loads((report / "statistics.json").read_text())
    with gzip.open(report / "entry-results.json.gz", "rt") as stream:
        rows = json.load(stream)
    size = summary["entry_count"]
    assert len(rows) == size * 2
    assert {(row["ordinal"], row["rate"]) for row in rows} == {
        (ordinal, rate) for ordinal in range(size) for rate in (48000, 96000)
    }
    for row in rows:
        if row["replacement"]:
            assert row["outcome"] in ("replacement", "improvement")
            assert (
                row["original_max_error_db"] is None
                or row["original_max_error_db"] > 0.5
            )
            if row["outcome"] == "replacement":
                assert row["published_max_error_db"] <= 0.5
            else:
                assert row["original_max_error_db"] is None or (
                    row["published_max_error_db"] < row["original_max_error_db"]
                )
        else:
            assert row["published_max_error_db"] == row["original_max_error_db"]
    assert (
        len({row["ordinal"] for row in rows if row["replacement"]})
        == summary["improved_entries_either_rate"]
    )
    for rate, data in summary["rates"].items():
        assert sum(data["outcomes"].values()) == size
        assert (
            sum(row["replacement"] for row in rows if str(row["rate"]) == rate)
            == data["replaced_entries"] + data["improved_entries"]
        )
        for stage in ("before", "after"):
            values = [
                np.asarray(data["pointwise_absolute_error_db"][name][stage])
                for name in ("median", "p95", "p99", "maximum")
            ]
            assert all(np.all(np.isfinite(value)) for value in values)
            assert all(np.all(lower <= upper) for lower, upper in pairwise(values))
    for name in (
        "aggregate-48000.png",
        "aggregate-96000.png",
        "example-1.png",
        "example-2.png",
    ):
        assert (report / "assets" / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
