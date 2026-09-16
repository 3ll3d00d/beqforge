"""R8: a reference is one broad, flat region shared by construction and judging."""

import numpy as np
import pytest

from beqanalyser.design.diagnose import (
    DiagnoseParams,
    REFERENCE_POINTS,
    _trim_to_flat_subwindow,
    band_slope,
    plateau_reference,
)


def test_scatter_that_the_median_filter_absorbs_does_not_reject_a_flat_region():
    """A few estimator-bin spikes must not cost a title its reference.

    The trend check has to read the same scatter-suppressed curve region membership was
    decided from — reading the raw curve instead let bin-to-bin acoustic scatter reject a
    genuinely flat region on real material (Tron: an 81-point, 1.1-octave candidate at
    +3.01 dB/octave raw against the 3.0 limit, +2.92 on the discovery curve). Reproduced
    here with a handful of spikes an 11-point median filter erases but a raw least-squares
    fit does not: on their own they swing the raw slope to -4.0 dB/octave.
    """
    freqs = np.geomspace(4, 200, REFERENCE_POINTS)
    curve = np.full_like(freqs, -30.0)
    curve[(freqs >= 25) & (freqs <= 55)] = 0.0
    spike_at = np.flatnonzero((freqs >= 25) & (freqs <= 27))[[1, 4, 7]]
    curve[spike_at] += 22.0
    level, (low, high) = plateau_reference(curve, freqs, DiagnoseParams())
    assert level == 0.0
    assert 25 <= low < high <= 55


def test_a_peaks_falling_edge_does_not_veto_the_plateau_beside_it():
    """A human sees a plateau, a peak just below it, then a rolloff — and the plateau is
    real. Measured on Test 71: the one connected within-tolerance region merged a peak's
    falling edge with a genuinely flat stretch beside it, and the region's own least-squares
    slope over all of it — -4.83 dB/octave — failed the 3.0 limit even though the flat part
    alone reads -1.99. Trimming the peak-side end must recover it rather than discard the
    whole region.

    Values below are the real measured curve (dB relative to the channel's own plateau,
    read off the grid `plateau_reference` builds internally) over the region in question.
    """
    freqs = np.array(
        [
            22.464, 22.685, 22.908, 23.134, 23.362, 23.592, 23.825, 24.060, 24.297,
            24.536, 24.778, 25.022, 25.268, 25.517, 25.769, 26.023, 26.279, 26.538,
            26.799, 27.063, 27.330, 27.599, 27.871, 28.146, 28.423, 28.703, 28.986,
            29.272, 29.560, 29.851, 30.145, 30.443, 30.742, 31.045, 31.351, 31.660,
            31.972, 32.287, 32.605, 32.926, 33.251, 33.578, 33.909, 34.243, 34.581,
            34.922, 35.266, 35.613, 35.964, 36.318, 36.676, 37.038, 37.402, 37.771,
            38.143, 38.519, 38.898, 39.282, 39.669, 40.060, 40.454, 40.853, 41.255,
            41.662,
        ]
    )
    discovery = np.array(
        [
            -55.296, -56.418, -58.225, -59.003, -59.317, -59.712, -59.682, -59.347,
            -59.646, -60.136, -60.243, -60.698, -61.368, -61.582, -61.115, -61.158,
            -61.936, -62.343, -62.480, -62.511, -62.218, -63.121, -63.143, -62.926,
            -63.277, -62.913, -62.850, -62.135, -62.506, -62.590, -62.484, -63.128,
            -62.356, -61.651, -62.051, -62.491, -62.739, -62.191, -62.011, -62.232,
            -62.368, -62.935, -63.060, -62.905, -63.179, -63.285, -63.252, -64.312,
            -64.568, -63.928, -63.456, -63.182, -62.591, -62.742, -63.114, -62.720,
            -62.290, -61.578, -62.492, -63.332, -63.209, -62.801, -63.364, -63.634,
        ]
    )
    region = np.arange(len(freqs))
    whole_slope = band_slope(discovery, freqs, freqs[0], freqs[-1])
    assert abs(whole_slope) > 3.0, "fixture no longer reproduces the whole-region failure"

    trimmed = _trim_to_flat_subwindow(discovery, freqs, region, 1 / 3, 3.0)
    assert trimmed is not None, "a genuinely flat plateau exists beside the peak's edge"
    assert trimmed[0] > region[0], "the peak-side end is what needed trimming"
    assert trimmed[-1] == region[-1], "the plateau's own far end needed no trimming"
    kept_slope = band_slope(discovery, freqs, freqs[trimmed[0]], freqs[trimmed[-1]])
    assert abs(kept_slope) <= 3.0


def test_disjoint_plateaus_do_not_bridge_valley():
    freqs = np.geomspace(4, 200, 4000)
    curve = np.full_like(freqs, -30)
    curve[((freqs >= 10) & (freqs <= 20)) | ((freqs >= 80) & (freqs <= 110))] = 0
    level, (low, high) = plateau_reference(curve, freqs, DiagnoseParams())
    assert level == 0
    assert 10 <= low < high <= 20


def test_narrow_authored_peak_does_not_replace_broad_plateau():
    freqs = np.geomspace(4, 200, 4000)
    curve = np.full_like(freqs, -30)
    curve[(freqs >= 30) & (freqs <= 100)] = 0
    curve[(freqs >= 15) & (freqs <= 15.5)] = 20
    level, (low, high) = plateau_reference(curve, freqs, DiagnoseParams())
    assert level == 0
    assert 30 <= low < high <= 100


@pytest.mark.parametrize(
    "curve", [lambda f: 12 * np.log2(f), lambda f: np.full_like(f, np.nan)]
)
def test_no_usable_plateau_is_explicit(curve):
    freqs = np.geomspace(4, 200, 4000)
    level, region = plateau_reference(curve(freqs), freqs, DiagnoseParams())
    assert np.isnan(level)
    assert np.isnan(region).all()


def test_reference_level_is_median_of_selected_log_region():
    freqs = np.geomspace(4, 200, 400)
    curve = np.where((freqs >= 20) & (freqs <= 80), np.log2(freqs / 20), -30)
    level, (low, high) = plateau_reference(curve, freqs, DiagnoseParams())
    assert level == pytest.approx(np.median(curve[(freqs >= low) & (freqs <= high)]))


def test_construction_and_verification_share_reference(monkeypatch):
    import importlib
    from beqanalyser.design import pipeline
    from beqanalyser.design.material import Material

    verification = importlib.import_module("beqanalyser.design.verify")
    freqs = np.linspace(0.25, 500, 2000)
    curve = np.where(freqs < 30, -12.0, 0.0)
    curve[freqs > 120] = -20.0
    monkeypatch.setattr(pipeline, "mean_spectrum", lambda *args: (freqs, curve))
    monkeypatch.setattr(verification, "_mean_db", lambda *args: (freqs, curve))
    monkeypatch.setattr(
        pipeline, "priced_by_evidence", lambda target, *args: (target, [])
    )
    material = Material("reference", 1000, np.ones(5000), {}, "complete_programme")
    from beqanalyser.design.diagnose import Diagnosis

    diagnosis = Diagnosis(freqs, curve, {})
    proposals = pipeline.flatten_targets(
        material, diagnosis, None, None, pipeline.PipelineParams()
    )
    from beqanalyser.design import BiquadSpec

    correction = verification.verify(
        [BiquadSpec("low_shelf", 30, 0, 0.707)], material.mono_mix, 1000
    )
    assert np.interp(10, pipeline.DESIGN_GRID, proposals[0].target_db) == pytest.approx(
        12
    )
    assert np.interp(10, correction.freqs, correction.before_db) == pytest.approx(-12)
