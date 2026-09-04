"""Strategies are first-class and interchangeable.

Each derives a target its own way; all are fitted and judged identically, so their outputs are
comparable and the acceptance model rather than a preference decides between them.
"""

import numpy as np
import pytest

from beqanalyser.design.pipeline import (
    DESIGN_GRID,
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


def test_the_flatten_target_stops_without_a_step(walled) -> None:
    """A target is what the fit is scored against, so it must be followable.

    The mix keeps falling above the reference and that fall is programme, not deficit, so the
    target has to stop. Stopping it with a hard zero left a step across a single grid point —
    0.58, 0.69 and 1.08 dB on the three real titles — inside the band the residual is scored
    over. No biquad cascade follows a step 0.55 Hz wide, so the minimax residual was bounded
    below by half of it and the fit could never stop early: on the third title three sections
    reached 0.532 dB against a 0.5 target with the cut, and 0.432 with the taper.
    """
    from beqanalyser.design.diagnose import diagnose

    diagnosis = diagnose(walled)
    target = flatten_targets(walled, diagnosis, None, None, PipelineParams())[
        0
    ].target_db

    reference = PipelineParams().flatten_reference_hz
    stopping = (DESIGN_GRID >= reference * 0.9) & (DESIGN_GRID <= reference * 1.6)
    steps = np.abs(np.diff(target))
    assert steps[stopping[:-1]].max() < 0.25, "the target still stops with a step"
    assert np.interp(reference * 1.3, DESIGN_GRID, target) == pytest.approx(
        0.0, abs=1e-9
    )


def test_the_taper_does_not_reach_into_the_correction(walled) -> None:
    """It has to stop the target, not shrink it."""
    from beqanalyser.design.diagnose import diagnose

    diagnosis = diagnose(walled)
    params = PipelineParams()
    target = flatten_targets(walled, diagnosis, None, None, params)[0].target_db
    below = DESIGN_GRID < params.flatten_reference_hz
    assert target[below].max() > 1.0, "the correction itself has gone"
