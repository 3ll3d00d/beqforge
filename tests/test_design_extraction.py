"""Reduction to envelopes.

The property that matters is differential: apply a known high-pass and the change in the
extracted envelope must be the filter's own response. That validates the whole chain —
framing, scene selection, percentile envelopes, rumble differencing — without needing to know
anything about the source, which is what makes it usable on real material too (§6.1).

**Coherence is deliberately barely tested here.** Reproducing it synthetically needs a model
of how real bass content covaries across frequency, and inventing one would mean validating
the coherence weighting against my own assumption about what content looks like — circular,
and the failure §2.4 warns about. What the harness can show is that the partial correlation
discriminates at all. Its behaviour on the band that matters is a measurement on real
material, recorded in §3.4.
"""

import dataclasses

import numpy as np
import pytest

from beqanalyser.design import Alignment, HighPass
from beqanalyser.design.extraction import ExtractionParams, extract
from beqanalyser.design.filters import high_pass_sos, magnitude_db
from beqanalyser.design.harness import SyntheticProfile, apply_high_pass, synthesise

FS = 1000.0
RECOVERY_BAND = (8.0, 63.0)


@pytest.fixture(scope="module")
def source() -> np.ndarray:
    return synthesise(
        SyntheticProfile(duration_s=1800.0, event_rate_hz=0.08), FS, seed=11
    )


@pytest.fixture(scope="module")
def baseline(source: np.ndarray):
    return extract(source, FS)


@pytest.mark.parametrize(
    "rolloff",
    [
        HighPass(Alignment.BUTTERWORTH, 2, 25.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 25.0),
        HighPass(Alignment.BUTTERWORTH, 4, 18.0),
    ],
)
def test_injected_rolloff_is_recovered_differentially(
    source: np.ndarray, baseline, rolloff: HighPass
) -> None:
    filtered = extract(apply_high_pass(source, rolloff, FS), FS)
    measured = filtered.content_db - baseline.content_db
    truth = magnitude_db(high_pass_sos(rolloff, FS), baseline.freqs, FS)

    band = (baseline.freqs >= RECOVERY_BAND[0]) & (baseline.freqs <= RECOVERY_BAND[1])
    assert np.max(np.abs((measured - truth)[band])) < 1.5


def test_coherence_is_highest_inside_the_reference_band(baseline) -> None:
    """A raw correlation scores 0.5-0.9 everywhere on real material because every bin follows
    the programme level; the partial has to discriminate. This is the only coherence property
    the synthetic harness can speak to — see the module docstring.
    """
    inside = baseline.coherence[(baseline.freqs >= 60.0) & (baseline.freqs <= 120.0)]
    outside = baseline.coherence[baseline.freqs <= 30.0]
    assert np.median(inside) > 0.15
    assert np.median(inside) - np.median(outside) > 0.15


def test_scene_selection_is_absolute_so_a_quiet_title_yields_few_scenes() -> None:
    """§3.2 — relative selection would manufacture false positives on exactly this material."""
    loud_title = synthesise(
        SyntheticProfile(duration_s=900.0, event_rate_hz=0.08, floor_db=-60.0),
        FS,
        seed=3,
    )
    # sparse, weak events over a high floor: the bass-light case
    quiet_title = synthesise(
        SyntheticProfile(
            duration_s=900.0,
            event_rate_hz=0.004,
            floor_db=-14.0,
            event_level_spread_db=3.0,
        ),
        FS,
        seed=3,
    )
    loud = extract(loud_title, FS)
    quiet = extract(quiet_title, FS)

    loud_fraction = loud.loud_frames / loud.total_frames
    quiet_fraction = quiet.loud_frames / quiet.total_frames
    assert quiet_fraction < 0.5 * loud_fraction


def test_rumble_in_the_selection_band_forces_abstention(caplog) -> None:
    """Rumble does not change which frames are loudest — it is stationary — but it does lift
    the floor an absolute margin is measured against, and the selection band now sits where
    rumble lives (§3.2). Strong rumble therefore starves the selection entirely.

    That is the right outcome, not a bug: a title whose bass band is filled by something
    stationary has nothing identifiable in it. What matters is that it says so.
    """
    rumbly = extract(
        synthesise(
            SyntheticProfile(
                duration_s=900.0, event_rate_hz=0.08, rumble_db=-20.0, rumble_hz=12.0
            ),
            FS,
            seed=5,
        ),
        FS,
    )
    assert rumbly.loud_frames == 0
    assert not rumbly.measurable.any()
    assert np.all(np.isneginf(rumbly.content_db))
    assert "abstain" in caplog.text


def test_content_is_flagged_unmeasurable_rather_than_reported_as_a_deep_rolloff(
    baseline,
) -> None:
    """A peak envelope at or below the quiet one means floor, not attenuation."""
    assert baseline.measurable.any()
    assert np.all(np.isfinite(baseline.content_db[baseline.measurable]))
    assert np.all(np.isneginf(baseline.content_db[~baseline.measurable]))


def test_reference_band_does_not_move_with_the_signal(source: np.ndarray) -> None:
    """§3.4 — fixed before any corner search, or the fit landscape is reshaped by the fit."""
    params = ExtractionParams()
    plain = extract(source, FS, params)
    filtered = extract(
        apply_high_pass(source, HighPass(Alignment.BUTTERWORTH, 4, 40.0), FS),
        FS,
        params,
    )
    assert plain.reference_band_hz == filtered.reference_band_hz == (60.0, 120.0)


def test_every_analysed_bin_is_priced_against_its_own_evidence() -> None:
    """The confidence band is gone, not widened.

    It was (4, 60) — "every knee measured so far sits inside it", §2.1's move — and above it
    `margin_se_db` is `inf`, which by convention means *no restriction*. Three titles ask for
    boost above 60 Hz, so the one mechanism that prices boost was silent where they needed it.
    Deriving the edge from the mix plateau was tried first and Alien disproves its premise: its
    plateau begins at 49.7 Hz and `flatten` asks for 14.6 dB above 40 Hz.
    """
    samples = synthesise(
        SyntheticProfile(duration_s=600.0, event_rate_hz=0.08), FS, seed=7
    )
    envelopes = extract(samples, FS)

    priced = np.isfinite(envelopes.margin_se_db)
    assert priced.all(), (
        f"{(~priced).sum()} of {priced.size} bins carry no standard error; every analysed bin "
        "should be priced"
    )
    # and the cap still works, for a profiling run that wants to pin the cost
    pinned = extract(
        samples, FS, dataclasses.replace(ExtractionParams(), confidence_bins=10)
    )
    assert np.isfinite(pinned.margin_se_db).sum() == 10


def test_chunking_the_bootstrap_cannot_change_what_it_returns() -> None:
    """Memory bound only: the replicate indices are shared across bins by construction."""
    from beqanalyser.design import extraction

    samples = synthesise(
        SyntheticProfile(duration_s=300.0, event_rate_hz=0.08), FS, seed=11
    )
    whole = extract(samples, FS)
    original = extraction._BOOTSTRAP_ELEMENTS
    try:
        extraction._BOOTSTRAP_ELEMENTS = 1  # forces one bin per chunk
        chunked = extract(samples, FS)
    finally:
        extraction._BOOTSTRAP_ELEMENTS = original
    assert np.array_equal(whole.margin_se_db, chunked.margin_se_db)
