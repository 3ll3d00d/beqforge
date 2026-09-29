"""E9: boost the published cascade delivers beyond the evidence ceiling, record-only."""

import math

import numpy as np
import pytest

from beqforge import DESIGN_GRID, BiquadSpec
from beqforge import record
from beqforge.filters import Realisation
from beqforge.pipeline import evidence_excess

DEVICE = Realisation()
MEASURED = (4.0, 200.0)
SHELF = [BiquadSpec("low_shelf", 20.0, 10.0, 0.707)]


def test_no_filter_delivers_no_excess():
    found = evidence_excess([], DEVICE, np.full_like(DESIGN_GRID, 6.0), MEASURED)
    assert found.max_db == pytest.approx(-6.0)
    assert found.width_octaves == 0.0
    assert found.integrated_db_octaves == 0.0
    assert not found.unsupported_at_max


def test_a_shelf_over_the_ceiling_is_measured_where_it_exceeds():
    found = evidence_excess(SHELF, DEVICE, np.full_like(DESIGN_GRID, 6.0), MEASURED)
    # a +10 dB shelf against a 6 dB licence: about 4 dB over, at the bottom of the band
    assert found.max_db == pytest.approx(4.0, abs=0.2)
    assert found.at_hz < 10.0
    assert found.width_octaves > 1.0
    assert found.integrated_db_octaves > 0.0
    assert not found.unsupported_at_max


def test_a_hole_in_the_ceiling_is_flagged_as_unsupported():
    ceiling = np.full_like(DESIGN_GRID, 20.0)
    hole = np.argmin(np.abs(DESIGN_GRID - 10.0))
    ceiling[hole] = 0.0
    found = evidence_excess(SHELF, DEVICE, ceiling, MEASURED)
    assert found.at_hz == pytest.approx(DESIGN_GRID[hole])
    assert found.unsupported_at_max
    # one bin wide: the neighbours are licensed
    assert found.width_octaves == 0.0


def test_exclusions_are_reported_apart_from_the_main_excess():
    ceiling = np.full_like(DESIGN_GRID, 20.0)
    found = evidence_excess(SHELF, DEVICE, ceiling, MEASURED, ((8.0, 12.0),))
    assert found.max_db < 0.0
    assert found.excluded_max_db == pytest.approx(10.0, abs=0.5)


def test_unmeasured_frequencies_are_not_read_as_zero_licence():
    """Below the analysed band the ceiling reads zero only because nothing was measured."""
    below = [BiquadSpec("peaking_eq", 3.5, 10.0, 4.0)]
    found = evidence_excess(
        below, DEVICE, np.full_like(DESIGN_GRID, 1.0), (10.0, 200.0)
    )
    # +10 dB at 3.5 Hz, outside what was measured; by 10 Hz it has all but fallen away
    assert found.max_db < 1.0
    assert found.at_hz >= 10.0


def test_an_unstable_cascade_has_no_steady_state_excess(monkeypatch):
    import beqforge.pipeline as P

    monkeypatch.setattr(P, "unstable_sections", lambda *a: [0])
    assert evidence_excess(SHELF, DEVICE, np.zeros_like(DESIGN_GRID), MEASURED) is None


def test_every_run_candidate_carries_it_into_the_record(monkeypatch):
    from dataclasses import replace

    import beqforge.pipeline as P
    from tests.test_design_strategy_config import inputs

    material, diagnosis, envelopes, identification = inputs()
    monkeypatch.setattr(P, "diagnose", lambda *a: diagnosis)
    monkeypatch.setattr(P, "extract", lambda *a: envelopes)
    monkeypatch.setattr(P, "identify_rolloff", lambda *a: identification)
    monkeypatch.setattr(P, "passband_ripple_db", lambda *a, **k: None)
    params = P.PipelineParams(strategies=("parametric",), max_sections=1)
    report = P.run(material, params)
    assert report.candidates
    for candidate in report.candidates:
        written = record._candidate(candidate)["evidence_excess"]
        assert written is not None
        assert math.isfinite(written["max_db"])
        # nothing excluded: NaN, written as null
        assert written["excluded_max_db"] is None
    # a verdict is never touched by it
    bare = replace(report.candidates[0], evidence_excess=None)
    assert (
        record._candidate(bare)["verdict"]
        == record._candidate(report.candidates[0])["verdict"]
    )
