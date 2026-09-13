"""Evidence constraints apply to both exact and fitted inversion."""

import numpy as np
import pytest

from beqanalyser.design import DESIGN_GRID, Alignment, HighPass
from beqanalyser.design.design import DesignParams, design
from beqanalyser.design.extraction import Envelopes
from beqanalyser.design.identify import Identification
from beqanalyser.design.rolloff import DB_PER_OCTAVE_PER_ORDER, RolloffFit


def identified_rolloff() -> Identification:
    return Identification(
        fit=RolloffFit(30.0, 4 * DB_PER_OCTAVE_PER_ORDER, 8.0, 0.0),
        rolloff=HighPass(Alignment.BUTTERWORTH, 4, 30.0),
        improvement_db=5.0,
        smooth_residual_db=5.0,
        weighted_bins=len(DESIGN_GRID),
        coherent_bandwidth_octaves=3.0,
    )


def envelopes_with_margin(margin_db: float) -> Envelopes:
    zeros = np.zeros_like(DESIGN_GRID)
    return Envelopes(
        freqs=DESIGN_GRID,
        mean_db=zeros,
        peak_db=zeros + margin_db,
        quiet_db=zeros,
        coherence=zeros + 1.0,
        reference_band_hz=(60.0, 120.0),
        loud_frames=100,
        quiet_frames=100,
        total_frames=200,
        margin_se_db=zeros,
    )


@pytest.mark.parametrize("ceiling, method", [(2.0, "fitted"), (40.0, "exact")])
def test_exact_inversion_is_used_only_when_the_evidence_licenses_it(ceiling, method):
    params = DesignParams(max_sections=2)
    result = design(identified_rolloff(), envelopes_with_margin(ceiling), params)
    assert result.method == method
    assert result.noise_ceiling_binds == (method == "fitted")
    assert result.mv_adjust_db <= min(ceiling, params.max_boost_db) + params.residual_target_db
    assert result.residual_db <= params.residual_target_db
