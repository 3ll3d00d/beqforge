"""Strategies are first-class and interchangeable.

Each derives a target its own way; all are fitted and judged identically, so their outputs are
comparable and the acceptance model rather than a preference decides between them.
"""

import numpy as np
import pytest

from beqanalyser.design.extraction import extract
from beqanalyser.design.pipeline import (
    DESIGN_GRID,
    STRATEGIES,
    PipelineParams,
    Proposal,
    Strategy,
    flatten_targets,
    run,
)
from tests.test_design_diagnose import (
    FS,
    high_passed,
    material_from,
    scened_noise as _scened_noise,
)


def scened_noise(seed, samples):
    """Include shared quiet scenes so target tests have measured contrast (R1)."""
    loud = _scened_noise(seed, samples).reshape(-1, int(10 * FS))
    quiet = loud[:, : int(5 * FS)] * 1e-4
    return np.concatenate((loud, quiet), axis=1).ravel()


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

    diagnosis = diagnose(walled)
    envelopes = extract(walled.mono_mix, float(walled.fs))
    params = PipelineParams()
    for name, strategy in STRATEGIES.items():
        assert isinstance(strategy, Strategy), name
        produced = strategy.derive(walled, diagnosis, envelopes, None, params)
        assert isinstance(produced, list), name
        for proposal in produced:
            assert isinstance(proposal, Proposal), name
            assert proposal.label
            assert (proposal.target_db is not None) or (proposal.filters is not None)


def test_flatten_proposes_a_target_that_inverts_the_measured_response(walled) -> None:
    from beqanalyser.design.diagnose import diagnose

    diagnosis = diagnose(walled)
    envelopes = extract(walled.mono_mix, float(walled.fs))
    proposals = flatten_targets(walled, diagnosis, envelopes, None, PipelineParams())
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
    envelopes = extract(walled.mono_mix, float(walled.fs))
    target = flatten_targets(walled, diagnosis, envelopes, None, PipelineParams())[
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
    envelopes = extract(walled.mono_mix, float(walled.fs))
    params = PipelineParams()
    target = flatten_targets(walled, diagnosis, envelopes, None, params)[0].target_db
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
                "L": 0.01 * scened_noise(30, samples),
                "C": 0.01 * scened_noise(31, samples),
                "LFE": high_passed(scened_noise(32, samples), corner, order=6),
            }
        )

    def stop_hz(corner: float) -> float:
        material = walled_at(corner)
        envelopes = extract(material.mono_mix, float(material.fs))
        target = flatten_targets(
            material, diagnose(material), envelopes, None, PipelineParams()
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
    envelopes = extract(material.mono_mix, float(material.fs))
    target = flatten_targets(
        material, diagnose(material), envelopes, None, PipelineParams()
    )[0].target_db
    assert np.all(target[DESIGN_GRID > 120.0] == 0.0)


def test_the_restore_caps_share_what_does_not_depend_on_the_cap(walled) -> None:
    """A cap changes only the ceiling on the boost, so the transforms under it are shared.

    Sharing them must not change any target — this is three forward and three inverse
    transforms of a two-hour signal collapsing to one each, not a different calculation.
    """
    from beqanalyser.design.diagnose import diagnose
    from beqanalyser.design.pipeline import _Restoration, counterfactual_target

    diagnosis = diagnose(walled)
    if not diagnosis.filtered_channels:
        pytest.skip("no channel is filtered, so there is nothing to restore")
    params = PipelineParams()
    shared = _Restoration(walled, diagnosis)
    for cap in params.restore_caps_db:
        alone = counterfactual_target(walled, diagnosis, cap, params)
        pooled = counterfactual_target(walled, diagnosis, cap, params, shared)
        assert np.array_equal(alone, pooled), f"cap {cap}"


def test_parametric_fits_from_the_same_seeds_as_every_other_candidate() -> None:
    """`design` inherited `fit_minimal_biquads`' own default and so fitted from three seeds.

    Every other candidate fits from `PipelineParams.fit_seeds`. The parametric route reaching
    the fitter without a `seeds` argument made it three times the optimiser of anything else,
    for the strategy that is rejected on all four titles — a quarter of a run.
    """
    from beqanalyser.design.design import DesignParams

    params = PipelineParams(fit_seeds=(0, 1, 2, 3))
    assert DesignParams().fit_seeds == PipelineParams().fit_seeds
    # and the pipeline hands its own choice down rather than letting the default stand
    from beqanalyser.design.pipeline import parametric_params

    assert parametric_params(params).fit_seeds == (0, 1, 2, 3)


def test_section_placement_follows_the_target_not_a_fixed_ceiling(monkeypatch) -> None:
    """A correction above 40 Hz must be allowed a section above 40 Hz.

    `_fit_all` used to hand every proposal of every title the literal `(5.0, 40.0)`, which
    hard-bounds each section's centre frequency. Measured on the eight records on hand, every
    title whose `flatten` target fitted under that ceiling accepted a filter and every title
    whose target reached past it had its sections pinned against it. Blazing Saddles needs
    23 dB at 50 Hz and got four sections crowded into 29-40 Hz.
    """
    from beqanalyser.design import pipeline

    captured: list = []

    def spy(requests, *args, **kwargs):
        captured.append((requests, kwargs))
        return [([], 0.0) for _ in requests]

    monkeypatch.setattr(pipeline, "fit_minimal_biquads_all", spy)

    # one low-frequency target, one that lives where the old ceiling was not
    low = np.where(DESIGN_GRID <= 20.0, 12.0, 0.0)
    high = np.where((DESIGN_GRID >= 40.0) & (DESIGN_GRID <= 70.0), 12.0, 0.0)
    params = PipelineParams()
    pipeline._fit_all(
        [Proposal("low", target_db=low), Proposal("high", target_db=high)], params
    )

    requests, kwargs = captured[0]
    bands = {r.label: r.placement_band_hz for r in requests}
    # the ceiling tracks the target rather than a constant: both are widened by the same
    # `WIDEN_OCTAVES`, so the low target's sits below the high one's in the same ratio their
    # corrections do. Asserting an absolute figure here would just restate the widening.
    assert bands["low"][1] < bands["high"][1] / 2.0, (
        f"the ceiling should follow the correction: {bands['low']} vs {bands['high']}"
    )
    assert bands["high"][0] > 30.0, (
        f"a 40-70 Hz target must not place sections at 5 Hz: {bands['high']}"
    )
    assert bands["high"][1] > 70.0, (
        f"a 40-70 Hz target must be allowed a section above 40 Hz: {bands['high']}"
    )
    for band in bands.values():
        assert band[0] >= params.lowest_frequency_hz, band

    # evaluate wide, place narrow: the scored band has to contain every placement band
    scored = kwargs["band_hz"]
    assert scored[1] >= max(high for _, high in bands.values()), scored


def test_the_judged_band_starts_at_the_measured_noise_floor() -> None:
    """§6.2's "should be derived, not defaulted", for the edge that can be.

    `flatten` deliberately holds its target flat below the noise floor, on evidence. Judging
    down to 5.0 Hz regardless then failed the candidate for not having corrected there —
    Nocturnal Animals' candidate reads +2.84 dB/oct and -3.4 dB over 5-45 Hz and +0.97 and -1.9
    over its own 19.8-45 Hz. Same filter, judged where its material exists.
    """
    import math
    from dataclasses import replace

    from beqanalyser.design.diagnose import Diagnosis
    from beqanalyser.design.pipeline import judged_band_hz

    from tests.test_design_diagnose import FS, material_from, scened_noise

    params = PipelineParams()
    samples = int(FS * 120.0)
    # flat material, so the top edge has no deficit to follow and stays nominal
    material = material_from(
        {"C": scened_noise(5, samples), "LFE": scened_noise(6, samples)}
    )
    bare = Diagnosis(freqs=np.array([1.0]), mix_db=np.array([0.0]), channels={})

    floored = replace(bare, noise_floor_hz=19.8)
    assert judged_band_hz(material, floored, params)[0] == 19.8

    # NaN means content was found all the way down, so the bottom does not move
    unfloored = replace(bare, noise_floor_hz=math.nan)
    assert judged_band_hz(material, unfloored, params)[0] == params.verify_band_hz[0]

    # and a floor below the nominal bottom cannot widen the band past what was measured
    shallow = replace(bare, noise_floor_hz=2.0)
    assert judged_band_hz(material, shallow, params)[0] == params.verify_band_hz[0]

    # the top edge never contracts below the nominal one
    for d in (floored, unfloored, shallow):
        assert judged_band_hz(material, d, params)[1] >= params.verify_band_hz[1]


def test_the_counterfactual_target_ends_where_its_deficit_does(walled) -> None:
    """Not at `share_band_hz[1]`, which is a cross-channel yardstick and says so.

    That hard zero at 35 Hz made the whole strategy incapable on any title whose knee is higher
    — Blazing Saddles at 44.4 Hz and Alien at 34.4-48.1 Hz, two of the three that abstain. Their
    candidates came out wrecked rather than marginal: a -39.7 dB hole at 40 Hz.
    """
    from beqanalyser.design.diagnose import diagnose
    from beqanalyser.design.pipeline import counterfactual_target

    params = PipelineParams()
    diagnosis = diagnose(walled)
    if not diagnosis.filtered_channels:
        pytest.skip("fixture shows no knee, so there is nothing to restore")
    target = counterfactual_target(walled, diagnosis, 25.0, params)
    live = np.flatnonzero(target > 1e-9)
    assert live.size, "the fixture's LFE is high-passed; there should be a deficit"
    # the old rule put the last live point exactly at the share band's top edge
    assert DESIGN_GRID[live[-1]] != pytest.approx(
        params.diagnose.share_band_hz[1], rel=0.02
    )
    # tapered rather than cut: no single-point step at the top of the correction
    steps = np.abs(np.diff(target[: live[-1] + 1]))
    assert steps.max() < 1.0, (
        f"a step of {steps.max():.2f} dB is a cliff the fitter must chase"
    )
