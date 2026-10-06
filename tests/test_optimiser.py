import copy
import json

import numpy as np
import pytest

from beqoptimiser import (
    FixedPoint,
    Float32,
    Section,
    Settings,
    magnitude,
    optimise,
    stable,
)
from beqoptimiser.cli import main, optimise_entry


@pytest.mark.parametrize("rate", [48000, 96000])
@pytest.mark.parametrize("kind", ["LowShelf", "HighShelf", "PeakingEQ"])
def test_rbj_matches_existing_arithmetic(rate, kind):
    biquad = pytest.importorskip("beqforge.biquad")

    actual = Section(kind, 10, 0.7, 12).sos(rate)
    expected = getattr(biquad, kind)(rate, 10, 0.7, 12).get_sos()[0]
    np.testing.assert_allclose(actual, expected, rtol=1e-15, atol=1e-15)


@pytest.mark.parametrize("rate", [48000, 96000])
def test_identity_and_accurate_original_do_not_search(rate):
    for row in ([1.0, 0, 0, 1, 0, 0], Section("LowShelf", 30, 0.7, 6).sos(rate)):
        result = optimise([row], rate=rate)
        assert result.outcome == "within_margin"
        assert result.replacement is None
        assert result.evaluations == 0


@pytest.mark.parametrize("rate,q", [(48000, 2), (96000, 0.7)])
def test_replacement_meets_margin_after_publication(rate, q):
    reference = np.array([Section("PeakingEQ", 10, q, 12).sos(rate)])
    original = reference.copy()
    result = optimise(reference, rate=rate, transport=Float32())
    assert result.outcome == "replacement"
    assert result.original_error_db > 0.5
    assert result.candidate_error_db < 0.5
    assert result.guard_error_db < 0.5
    stored = Float32().quantise(np.array(result.replacement))
    assert stable(stored)
    np.testing.assert_array_equal(stored, result.replacement)
    np.testing.assert_array_equal(reference, original)
    dense = np.geomspace(2, 200, 32768)
    assert (
        np.max(
            np.abs(magnitude(stored, dense, rate) - magnitude(reference, dense, rate))
        )
        < 0.5
    )


@pytest.mark.parametrize("rate", [48000, 96000])
def test_partial_improvement_is_published(rate):
    reference = [Section("PeakingEQ", 5, 6, 12).sos(rate)]
    result = optimise(reference, rate=rate)
    assert result.outcome == "improvement"
    assert 0.5 < result.candidate_error_db < result.original_error_db
    stored = Float32().quantise(np.array(result.replacement))
    assert stable(stored)
    np.testing.assert_array_equal(stored, result.replacement)


class Frozen(Float32):
    """float32 with no neighbouring values to search, so no candidate can beat the original"""

    name = "frozen-float32"

    def neighbours(self, value):
        return (value,)


def test_candidate_no_better_than_original_is_not_published():
    ref = [Section("PeakingEQ", 5, 6, 12).sos(48000)]
    result = optimise(ref, rate=48000, precision=Frozen())
    assert result.outcome == "no_replacement" and result.replacement is None
    assert result.candidate_error_db == pytest.approx(result.original_error_db)


@pytest.mark.parametrize("rate,kind", [(48000, "LowShelf"), (48000, "HighShelf")])
def test_out_of_band_error_does_not_affect_the_outcome(rate, kind):
    # these candidates are worse than the original outside 2-200 Hz, which is not assessed
    result = optimise(
        [
            Section(
                kind,
                3 if kind == "LowShelf" else 5,
                0.7 if kind == "LowShelf" else 6,
                10 if kind == "LowShelf" else 12,
            ).sos(rate)
        ],
        rate=rate,
    )
    assert result.outcome == "improvement" and result.replacement is not None
    assert result.guard_error_db > 0.5


def test_unstable_original_accepts_any_better_stable_candidate():
    result = optimise([Section("LowShelf", 3, 0.7, 10).sos(96000)], rate=96000)
    assert np.isinf(result.original_error_db)
    assert result.outcome == "improvement"
    assert np.isfinite(result.candidate_error_db)
    assert stable(np.array(result.replacement))


def test_rates_are_independent():
    a = optimise([Section("PeakingEQ", 10, 0.7, 12).sos(48000)], rate=48000)
    b = optimise([Section("PeakingEQ", 10, 0.7, 12).sos(96000)], rate=96000)
    assert a.outcome == "within_margin"
    assert b.outcome == "replacement"


def test_margin_and_numerical_boundary():
    ref = [Section("PeakingEQ", 10, 2, 12).sos(48000)]
    baseline = optimise(ref, rate=48000).original_error_db
    assert (
        optimise(ref, rate=48000, settings=Settings(margin_db=1)).outcome
        == "within_margin"
    )
    edge = optimise(ref, rate=48000, settings=Settings(margin_db=baseline))
    assert edge.outcome == "unresolved" and edge.replacement is None
    # a candidate which can't meet a tight margin is still published if it improves on the original
    strict = optimise(ref, rate=48000, settings=Settings(margin_db=0.01))
    assert strict.outcome == "improvement" and strict.replacement is not None
    assert strict.candidate_error_db < strict.original_error_db


def test_guard_setting_no_longer_exists():
    with pytest.raises(TypeError):
        Settings(guard_margin_db=0.1)


def test_fixed_precision_protocol():
    p = FixedPoint()
    np.testing.assert_array_equal(p.quantise(np.array([1.0, -2.0])), [1.0, -2.0])
    assert p.neighbours(1.0) == (1 - 2**-23, 1.0, 1 + 2**-23)
    r = optimise([Section("LowShelf", 40, 0.7, 6).sos(48000)], rate=48000, precision=p)
    assert r.precision == "fixed5.23"
    with pytest.raises(ValueError):
        p.quantise(np.array([16.0]))


@pytest.mark.parametrize(
    "settings",
    [
        {"margin_db": 0},
        {"margin_db": float("nan")},
        {"band_hz": (200, 2)},
        {"passes": 0},
    ],
)
def test_bad_settings(settings):
    with pytest.raises(ValueError):
        Settings(**settings)


def test_bad_reference_and_rate():
    with pytest.raises(ValueError):
        optimise([[1, 0, 0, 1, -2, 1]], rate=48000)
    with pytest.raises(ValueError):
        optimise([[1, 0, 0, 1, 0, 0]], rate=44100)


def test_catalogue_preserves_authored_and_exports_exact_feedback():
    entry = {
        "title": "fixture",
        "mv": -3,
        "filters": [{"type": "PeakingEQ", "freq": 10, "q": 2, "gain": 12}],
    }
    before = copy.deepcopy(entry)
    r = optimise_entry(entry, rate=48000)
    assert entry == before
    variant = r["variant"]
    assert variant is not None
    row = variant["biquads"][0]
    restored = [[*map(float, row["b"]), 1, *(-float(v) for v in row["a"])]]
    assert stable(np.array(restored))
    result = optimise([Section("PeakingEQ", 10, 2, 12).sos(48000)], rate=48000)
    np.testing.assert_array_equal(restored, result.replacement)


def test_incomplete_cache_is_not_silently_ignored():
    entry = {
        "filters": [
            {
                "type": "LowShelf",
                "freq": 30,
                "q": 0.7,
                "gain": 6,
                "biquads": {"48000": {"b": ["1", "0", "0"], "a": ["0", "0"]}},
            },
            {"type": "LowShelf", "freq": 30, "q": 0.7, "gain": 6},
        ]
    }
    with pytest.raises(ValueError, match="incomplete"):
        optimise_entry(entry, rate=48000)


def test_cli_both_rates_and_no_unsuccessful_variant(tmp_path):
    source = tmp_path / "in.json"
    output = tmp_path / "out.json"
    source.write_text(
        json.dumps({"filters": [{"type": "LowShelf", "freq": 30, "q": 0.7, "gain": 6}]})
    )
    assert main([str(source), "--out", str(output)]) == 0
    document = json.loads(output.read_text())
    assert {r["rate"] for r in document["entries"]} == {48000, 96000}
    for r in document["entries"]:
        published = r["result"]["outcome"] in ("replacement", "improvement")
        assert (r["variant"] is not None) == published


@pytest.mark.parametrize(
    "delta,outcome",
    [(-0.0001, "improvement"), (0.0, "unresolved"), (0.0001, "replacement")],
)
def test_candidate_margin_boundary(delta, outcome):
    ref = [Section("PeakingEQ", 10, 2, 12).sos(48000)]
    error = optimise(ref, rate=48000).candidate_error_db
    result = optimise(ref, rate=48000, settings=Settings(margin_db=error + delta))
    assert result.outcome == outcome
    assert (result.replacement is not None) == (outcome != "unresolved")


def test_cached_sent_baseline_and_repeated_sections():
    row = Section("PeakingEQ", 10, 2, 12).sos(48000)
    f = {
        "type": "PeakingEQ",
        "freq": 10,
        "q": 2,
        "gain": 12,
        "count": 2,
        "biquads": {
            "48000": {
                "b": [format(v, ".17g") for v in row[:3]],
                "a": [format(-v, ".17g") for v in row[4:]],
            }
        },
    }
    entry = {"filters": [f], "mv": -6}
    r = optimise_entry(entry, rate=48000)
    assert r["baseline_source"] == "published"
    if r["variant"]:
        assert len(r["variant"]["biquads"]) == 2
        assert r["variant"]["volume_offset_db"] == -6
    ref = np.array([row, row])
    expected = optimise(ref, rate=48000, transport=Float32())
    assert r["result"]["original_error_db"] == expected.original_error_db


def test_distinct_sent_coefficients_are_the_baseline():
    ref = [Section("PeakingEQ", 10, 2, 12).sos(48000)]
    sent = Float32().quantise(np.array(ref))
    sent[0, 0] = np.nextafter(np.float32(sent[0, 0]), np.float32(np.inf))
    a = optimise(ref, rate=48000)
    b = optimise(ref, sent=sent, rate=48000)
    assert a.original_error_db != b.original_error_db
    assert a.source_digest != b.source_digest


def test_deterministic_output():
    ref = [Section("PeakingEQ", 10, 2, 12).sos(48000)]
    assert optimise(ref, rate=48000) == optimise(ref, rate=48000)


def test_cli_refuses_to_overwrite_source(tmp_path):
    source = tmp_path / "source.json"
    raw = '{"filters": []}'
    source.write_text(raw)
    with pytest.raises(SystemExit) as error:
        main([str(source), "--out", str(source)])
    assert error.value.code == 2
    assert source.read_text() == raw
