"""The negative corpus (IMPROVEMENT_PLAN E2): its cases and its statistics, not its results.

Running it is a tool (`tools/negative_corpus.py`), minutes not seconds; what can be pinned
cheaply is that a case is reproducible from its seed, that the truth it carries is what its
shape says, and that the interval is the exact one.
"""

import numpy as np
import pytest

from beqforge.harness import CORPUS_GATED, CORPUS_SHAPES, corpus_case
from tools.negative_corpus import clopper_pearson, summarise


@pytest.mark.parametrize("shape", CORPUS_SHAPES)
def test_a_case_is_reproducible_from_its_shape_and_seed(shape) -> None:
    a, b = corpus_case(shape, 5, 30.0), corpus_case(shape, 5, 30.0)
    assert a.name == f"{shape}/5"
    for name in a.content:
        assert np.array_equal(a.observed()[name], b.observed()[name])
    other = corpus_case(shape, 6, 30.0)
    assert not np.array_equal(a.observed()["L"], other.observed()["L"])


def test_only_filtered_carries_an_injection() -> None:
    for shape in CORPUS_SHAPES:
        case = corpus_case(shape, 1, 30.0)
        assert case.negative == (shape != "filtered"), shape
        material = case.material()
        assert set(material.channels) == {"L", "LFE"}
        assert material.coverage == "complete_programme"
    assert "natural_droop" not in CORPUS_GATED and "filtered" not in CORPUS_GATED


def test_clopper_pearson_is_exact_at_the_edges() -> None:
    low, high = clopper_pearson(0, 50)
    assert low == 0.0 and high == pytest.approx(0.0711, abs=1e-4)  # the "rule of 3.7"
    low, high = clopper_pearson(50, 50)
    assert high == 1.0 and low == pytest.approx(0.9289, abs=1e-4)
    low, high = clopper_pearson(5, 50)
    assert low < 0.1 < high
    assert clopper_pearson(0, 0) == (0.0, 1.0)


def test_the_gate_is_taken_over_distinguishable_negatives_only() -> None:
    cases = [
        {"shape": "broadband", "false_acceptance": False, "selected": None},
        {"shape": "natural_droop", "false_acceptance": True, "selected": "flatten"},
        {
            "shape": "filtered",
            "false_acceptance": False,
            "selected": "flatten",
            "recovery_rms_db": 12.0,
        },
    ]
    summary = summarise(cases)
    assert summary["gated_negatives"]["n"] == 1
    assert summary["gated_negatives"]["false_acceptances"] == 0
    assert summary["natural_droop"]["false_acceptances"] == 1
    assert summary["filtered"]["true_positives"] == 1


def test_texture_is_left_alone_and_a_filter_is_not() -> None:
    """A low-end shortfall no larger than the programme's own ripple is texture, not a deficit.

    Unfiltered broadband titles were "corrected" for 2-4 dB wiggles below the knee — the same
    texture their passband shows above it. Measured against the passband's crest-to-trough
    swing, every unfiltered corpus title fell under it and every filter well over.
    """
    from beqforge.designer import _decline_for_blockers
    from beqforge.pipeline import PipelineParams, analyse

    texture = analyse(corpus_case("broadband", 1).material(), PipelineParams())
    assert any("within the programme's own ripple" in b for b in texture.blockers)
    assert _decline_for_blockers(texture.blockers)[0] == "within_programme_ripple"

    filtered = analyse(corpus_case("filtered", 3).material(), PipelineParams())
    assert not any("ripple" in b for b in filtered.blockers)


def test_a_channel_is_restored_for_a_missing_low_end_not_a_steep_slope() -> None:
    """IMPROVEMENT_PLAN T3: the fixed 14 dB/octave slope decided on noise.

    filtered/3's LFE carries an injected filter yet its steepest slope reads 13.5; broadband/4's
    LFE is unfiltered yet reads 22.9. Against each channel's own texture, both come out right.
    """
    from beqforge.diagnose import diagnose
    from beqforge.pipeline import PipelineParams, channels_missing_low_end

    params = PipelineParams()
    filtered = corpus_case("filtered", 3).material()
    assert not diagnose(filtered).channels["LFE"].is_filtered  # the slope missed it
    assert "LFE" in channels_missing_low_end(filtered, params)

    unfiltered = corpus_case("broadband", 4).material()
    assert diagnose(unfiltered).channels["LFE"].is_filtered  # the slope flagged it
    assert channels_missing_low_end(unfiltered, params) == []
