"""Strategies are first-class and interchangeable.

Each derives a target its own way; all are fitted and judged identically, so their outputs are
comparable and the acceptance model rather than a preference decides between them.
"""

import numpy as np
import pytest

from beqanalyser.design.pipeline import (
    STRATEGIES,
    PipelineParams,
    Proposal,
    flatten_targets,
    run,
)
from tests.test_design_diagnose import FS, high_passed, material_from, scened_noise


@pytest.fixture(scope="module")
def walled():
    samples = int(FS * 300.0)
    return material_from(
        {
            "L": scened_noise(20, samples),
            "C": scened_noise(21, samples),
            "LFE": high_passed(scened_noise(22, samples), 22.0, order=6),
        }
    )


def test_every_registered_strategy_has_the_same_signature(walled) -> None:
    from beqanalyser.design.diagnose import diagnose
    from beqanalyser.design.extraction import extract

    diagnosis = diagnose(walled)
    envelopes = extract(walled.mono_mix, float(walled.fs))
    params = PipelineParams()
    for name, strategy in STRATEGIES.items():
        produced = strategy(walled, diagnosis, envelopes, None, params)
        assert isinstance(produced, list), name
        for proposal in produced:
            assert isinstance(proposal, Proposal), name
            assert proposal.label
            assert (proposal.target_db is not None) or (proposal.filters is not None)


def test_flatten_proposes_a_target_that_inverts_the_measured_response(walled) -> None:
    from beqanalyser.design.diagnose import diagnose

    diagnosis = diagnose(walled)
    proposals = flatten_targets(walled, diagnosis, None, None, PipelineParams())
    assert len(proposals) == 1
    target = proposals[0].target_db
    from beqanalyser.design.pipeline import DESIGN_GRID

    # boost where the material is attenuated, none where it is not
    assert np.interp(8.0, DESIGN_GRID, target) > np.interp(30.0, DESIGN_GRID, target)
    assert np.interp(60.0, DESIGN_GRID, target) == pytest.approx(0.0, abs=0.01)


def test_an_unknown_strategy_is_refused(walled) -> None:
    with pytest.raises(ValueError, match="unknown strategy"):
        run(walled, PipelineParams(strategies=("nonesuch",)))


def test_a_single_strategy_can_be_selected(walled) -> None:
    report = run(
        walled,
        PipelineParams(strategies=("flatten",), max_sections=1, fit_seeds=(0,)),
    )
    assert report.candidates
    assert all(c.label.startswith("flatten") for c in report.candidates)
