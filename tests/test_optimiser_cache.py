"""Numerical reuse must preserve publication policy and each caller's provenance."""

import copy
import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from beqoptimiser import FixedPoint, Float32, ResultCache, Section, Settings, optimise
from beqoptimiser import cache as caching
from beqoptimiser.cli import optimise_entry


def request():
    return [Section("PeakingEQ", 10, 2, 12).sos(48000)]


@pytest.fixture
def store(tmp_path):
    return ResultCache(tmp_path / "cache", use_seed=False)


def test_disk_hit_avoids_search_and_preserves_result(store, monkeypatch):
    expected = optimise(request(), rate=48000, cache=store)
    monkeypatch.setattr(
        caching.core, "optimise", lambda *a, **kw: pytest.fail("cache hit searched")
    )
    assert optimise(request(), rate=48000, cache=store) == expected


def test_entry_metadata_and_volume_are_rebuilt(store, monkeypatch):
    entry = {
        "title": "Original",
        "mv": -3,
        "filters": [{"type": "PeakingEQ", "freq": 10, "q": 2, "gain": 12}],
    }
    first = optimise_entry(entry, rate=48000, cache=store)
    assert first["variant"] is not None
    different = {
        **copy.deepcopy(entry),
        "title": "Other edition",
        "mv": -9,
        "edition": "Extended",
    }
    monkeypatch.setattr(
        caching.core, "optimise", lambda *a, **kw: pytest.fail("metadata caused search")
    )
    second = optimise_entry(different, rate=48000, cache=store)
    assert first["source_digest"] != second["source_digest"]
    assert second["variant"]["source_digest"] == second["source_digest"]
    assert second["variant"]["volume_offset_db"] == -9
    assert first["variant"]["biquads"] == second["variant"]["biquads"]
    assert entry["mv"] == -3


@pytest.mark.parametrize(
    "change",
    [
        "rate",
        "reference",
        "sent",
        "precision",
        "transport",
        "margin",
        "passes",
        "band",
        "environment",
    ],
)
def test_request_changes_invalidate_cache(store, monkeypatch, change):
    reference = request()
    kwargs = {"rate": 48000}
    before = caching._request(reference, **kwargs)[0]
    if change == "rate":
        kwargs["rate"] = 96000
    elif change == "reference":
        reference = [Section("PeakingEQ", 11, 2, 12).sos(48000)]
    elif change == "sent":
        kwargs["sent"] = np.array(reference)
        kwargs["sent"][0, 0] += 1e-7
    elif change == "precision":
        kwargs["precision"] = FixedPoint()
    elif change == "transport":
        kwargs["transport"] = Float32()
    elif change == "margin":
        kwargs["settings"] = Settings(margin_db=0.4)
    elif change == "passes":
        kwargs["settings"] = Settings(passes=5)
    elif change == "band":
        kwargs["settings"] = Settings(band_hz=(3.0, 200.0))
    else:
        identity = {**caching.implementation_identity(), "numpy": "different"}
        monkeypatch.setattr(caching, "implementation_identity", lambda: identity)
    assert caching._request(reference, **kwargs)[0] != before


@pytest.mark.parametrize(
    "damage", ["invalid_json", "checksum", "unsafe_margin", "foreign_key"]
)
def test_corrupt_or_ineligible_entries_are_recomputed(store, monkeypatch, damage):
    reference = request()
    expected = optimise(reference, rate=48000, cache=store)
    path = next(store.directory.glob("*.json"))
    body = json.loads(path.read_text())
    if damage == "invalid_json":
        path.write_text("{")
    else:
        if damage == "checksum":
            body["result"]["original_error_db"] = 0.1
        elif damage == "unsafe_margin":
            body["result"]["candidate_error_db"] = 0.6
            body["checksum"] = caching._digest(body["result"])
        else:
            body["key"] = "foreign"
        path.write_text(json.dumps(body))
    calls = []
    original = caching.core.optimise

    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(caching.core, "optimise", counted)
    assert optimise(reference, rate=48000, cache=store) == expected
    assert calls == [True]


def test_readonly_or_unavailable_directory_does_not_break_results(tmp_path):
    path = tmp_path / "not-a-directory"
    path.write_text("occupied")
    store = ResultCache(path, use_seed=False)
    actual = optimise(request(), rate=48000, cache=store)
    assert actual == optimise(request(), rate=48000, cache=False)


def test_concurrent_writers_publish_complete_identical_results(store):
    reference = request()
    result = optimise(reference, rate=48000, cache=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        keys = list(
            pool.map(lambda _: store.seed(reference, result, rate=48000), range(12))
        )
    assert len(set(keys)) == 1
    assert len(list(store.directory.glob("*.json"))) == 1
    assert not list(store.directory.glob("*.tmp"))
    assert store.get(caching._request(reference, rate=48000)) == result


def test_nonfinite_and_unsuccessful_results_round_trip(store):
    # an original which can't be represented has an infinite error
    reference = [Section("LowShelf", 3, 0.7, 10).sos(96000)]
    nonfinite = optimise(reference, rate=96000, cache=store)
    assert np.isinf(nonfinite.original_error_db)
    assert optimise(reference, rate=96000, cache=store) == nonfinite
    accurate = [Section("LowShelf", 30, 0.7, 6).sos(48000)]
    unsuccessful = optimise(accurate, rate=48000, cache=store)
    assert unsuccessful.replacement is None
    assert optimise(accurate, rate=48000, cache=store) == unsuccessful
    body = caching._encode({"x": float("inf"), "optional": None})
    assert json.loads(json.dumps(body)) == body
    restored = caching._decode(body)
    assert np.isinf(restored["x"]) and restored["optional"] is None


def test_unknown_precision_bypasses_cache_until_it_has_an_identity():
    class Unknown:
        name = "custom"

        def quantise(self, values):
            return Float32().quantise(values)

        def neighbours(self, value):
            return Float32().neighbours(value)

    assert caching._request(request(), rate=48000, precision=Unknown()) is None

    class Identified(Unknown):
        def cache_identity(self):
            return {"version": 1, "bits": 32}

    assert caching._request(request(), rate=48000, precision=Identified()) is not None


def test_global_disable_forces_calculation(store, monkeypatch):
    expected = optimise(request(), rate=48000, cache=store)
    calls = []
    monkeypatch.setenv("BEQOPTIMISER_CACHE", "0")
    monkeypatch.setattr(
        caching.core, "optimise", lambda *a, **kw: calls.append(True) or expected
    )
    assert optimise(request(), rate=48000, cache=store) == expected
    assert calls == [True]


def test_shipped_seed_reuses_a_catalogue_entry_without_disk_or_search(
    tmp_path, monkeypatch, request
):
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1] / "beqoptimiser/data/seed-manifest.json"
        ).read_text()
    )
    # Exercise reuse in the seed's declared environment on every host. Production
    # must reject this Linux seed on incompatible architectures/dependencies.
    monkeypatch.setattr(
        caching, "implementation_identity", lambda: manifest["implementation"]
    )
    caching._bundled_entries.cache_clear()
    request.addfinalizer(caching._bundled_entries.cache_clear)
    # The entry appears in the frozen report, including the complete 96 kHz baseline.
    value = json.loads(
        (Path(__file__).parent / "fixtures" / "optimiser_seed_entry.json").read_text()
    )
    monkeypatch.setenv("BEQOPTIMISER_CACHE_DIR", str(tmp_path / "unused"))
    monkeypatch.setattr(
        caching.core, "optimise", lambda *a, **kw: pytest.fail("bundled seed missed")
    )
    for rate in (48000, 96000):
        report = optimise_entry(value, rate=rate)
        assert report["variant"] is not None
        assert report["result"]["candidate_error_db"] <= 0.5
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize(
    "field", ["system", "machine", "numpy", "scipy", "longdouble_mantissa_bits"]
)
def test_bundled_seed_rejects_incompatible_environment(monkeypatch, request, field):
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1] / "beqoptimiser/data/seed-manifest.json"
        ).read_text()
    )
    identity = {**manifest["implementation"], field: "incompatible"}
    monkeypatch.setattr(caching, "implementation_identity", lambda: identity)
    caching._bundled_entries.cache_clear()
    request.addfinalizer(caching._bundled_entries.cache_clear)
    assert caching._bundled_entries() == {}


@pytest.mark.parametrize("failures", [2, 5])
def test_windows_sharing_violation_has_bounded_atomic_retry(
    store, monkeypatch, failures
):
    replace = Path.replace
    attempts = []
    waits = []

    def busy(source, destination):
        attempts.append(True)
        if len(attempts) <= failures:
            error = PermissionError("destination in use")
            error.winerror = 32
            raise error
        return replace(source, destination)

    monkeypatch.setattr(Path, "replace", busy)
    monkeypatch.setattr(caching.time, "sleep", waits.append)
    envelope = {"key": "test", "result": {"value": 1}}
    assert store._write(envelope) == (failures < 5)
    assert len(attempts) == min(failures + 1, 5)
    assert len(waits) == min(failures, 4)
    assert not list(store.directory.glob("*.tmp"))
    if failures < 5:
        assert json.loads((store.directory / "test.json").read_text()) == envelope


def test_bundled_entries_have_valid_checksums_and_population_provenance():
    with gzip.open(
        Path(__file__).resolve().parents[1] / "beqoptimiser/data/seed.json.gz", "rt"
    ) as stream:
        document = json.load(stream)
    assert (
        len(document["entries"])
        == document["provenance"]["unique_numerical_results"]
        == 29566
    )
    assert document["provenance"]["entry_rate_results"] == 30848
    assert document["provenance"]["unsupported_entry_rate_results"] == 104
    for key, value in document["entries"].items():
        assert key == value["key"]
        assert caching._digest(value["result"]) == value["checksum"]


def test_empty_xdg_variable_uses_home_cache(monkeypatch):
    monkeypatch.delenv("BEQOPTIMISER_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "")
    assert ResultCache().directory == Path.home() / ".cache" / "beqoptimiser"


def test_missing_numerical_sources_disable_cache(monkeypatch):
    def missing():
        raise FileNotFoundError("frozen source unavailable")

    monkeypatch.setattr(caching, "implementation_identity", missing)
    assert caching._request(request(), rate=48000) is None


def improvement_request():
    return [Section("PeakingEQ", 5, 6, 12).sos(48000)]


def test_improvement_round_trips_through_the_cache(store, monkeypatch):
    expected = optimise(improvement_request(), rate=48000, cache=store)
    assert expected.outcome == "improvement"
    monkeypatch.setattr(
        caching.core, "optimise", lambda *a, **kw: pytest.fail("cache hit searched")
    )
    assert optimise(improvement_request(), rate=48000, cache=store) == expected


@pytest.mark.parametrize(
    "tamper",
    [
        # no better than the original
        lambda r: {"candidate_error_db": r.original_error_db},
        # missing coefficients
        lambda r: {"replacement": None},
    ],
)
def test_cached_improvement_violating_policy_is_rejected(store, tamper):
    reference = improvement_request()
    result = optimise(reference, rate=48000, cache=False)
    assert result.outcome == "improvement"
    from dataclasses import replace

    with pytest.raises((ValueError, TypeError)):
        store.seed(reference, replace(result, **tamper(result)), rate=48000)
