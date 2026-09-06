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

    # where it stops is derived from the material now, so the test finds it rather than
    # naming it: the taper's endpoint is the top of the non-zero target
    live = np.flatnonzero(target > 1e-9)
    stop = DESIGN_GRID[live[-1]]
    anchor = stop / PipelineParams().flatten_taper_ratio
    steps = np.abs(np.diff(target))
    # the taper's own span only. Below the anchor the target is still following the
    # correction, where a step is the rolloff and not a truncation.
    tapering = (DESIGN_GRID >= anchor * 0.9) & (DESIGN_GRID <= stop)
    assert steps[tapering[:-1]].max() < 0.25, "the target still stops with a step"
    assert np.interp(stop * 1.1, DESIGN_GRID, target) == pytest.approx(0.0, abs=1e-9)


def test_the_taper_does_not_reach_into_the_correction(walled) -> None:
    """It has to stop the target, not shrink it."""
    from beqanalyser.design.diagnose import diagnose

    diagnosis = diagnose(walled)
    params = PipelineParams()
    target = flatten_targets(walled, diagnosis, None, None, params)[0].target_db
    live = np.flatnonzero(target > 1e-9)
    assert target[: live[-1]].max() > 1.0, "the correction itself has gone"
    # and it survives well under the stop, not only at its shoulder
    assert np.interp(15.0, DESIGN_GRID, target) > 1.0


def test_flatten_stops_where_the_material_stops_being_short() -> None:
    """The anchor moves with the corner, because it is derived rather than named.

    `flatten_reference_hz` was 40.0 for every title, justified as "above the knee, below bass
    management" — the sentence §3.1 had to remove from the channel reference. A wall an octave
    higher must push the correction an octave higher with it.
    """
    from beqanalyser.design.diagnose import diagnose

    samples = int(FS * 300.0)

    def walled_at(corner: float):
        return material_from(
            {
                "L": scened_noise(30, samples),
                "C": scened_noise(31, samples),
                "LFE": high_passed(scened_noise(32, samples), corner, order=6),
            }
        )

    def stop_hz(corner: float) -> float:
        material = walled_at(corner)
        target = flatten_targets(
            material, diagnose(material), None, None, PipelineParams()
        )[0].target_db
        return float(DESIGN_GRID[np.flatnonzero(target > 1e-9)[-1]])

    assert stop_hz(44.0) > stop_hz(18.0) * 1.3


def test_flatten_does_not_read_the_high_frequency_fall_as_deficit() -> None:
    """Referenced to a plateau level, the mix drops below it again above the plateau's top.

    That return is programme, not deficit. The anchor is the *first* upward crossing into
    nothing for exactly this reason, so nothing above it may reach the target.
    """
    from beqanalyser.design.diagnose import diagnose

    samples = int(FS * 300.0)
    material = material_from(
        {
            "L": scened_noise(40, samples),
            "C": scened_noise(41, samples),
            "LFE": high_passed(scened_noise(42, samples), 22.0, order=6),
        }
    )
    target = flatten_targets(
        material, diagnose(material), None, None, PipelineParams()
    )[0].target_db
    assert np.all(target[DESIGN_GRID > 120.0] == 0.0)
