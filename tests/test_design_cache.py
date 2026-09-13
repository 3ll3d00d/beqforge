"""The stage cache must return exactly what it was given, or nothing at all.

A cache whose answer differs from a fresh computation is worse than no cache: every result
downstream of it is then a result of the cache rather than of the code. So the round trip is
asserted bit for bit and not to a tolerance — `record.py` may round its curves because it
draws pictures with them, and this may not because the pipeline computes with them.

The other half of the contract is the key. A stage that goes stale and does not say so serves
superseded work under a current label, which is the one failure mode worth more than the time
the cache saves, so each field of the key is asserted to be load-bearing.
"""

import math

import numpy as np
import pytest

from beqanalyser.design import Alignment, BiquadSpec, HighPass
from beqanalyser.design import cache as C
from beqanalyser.design.diagnose import ChannelDiagnosis, Diagnosis, DiagnoseParams
from beqanalyser.design.extraction import Envelopes, ExtractionParams
from beqanalyser.design.identify import Identification, IdentifyParams
from beqanalyser.design.material import Material
from beqanalyser.design.pipeline import STRATEGIES, Proposal
from beqanalyser.design.rolloff import RolloffFit


def material(seed: int = 0) -> Material:
    rng = np.random.default_rng(seed)
    return Material(
        name="synthetic",
        fs=1000,
        mono_mix=rng.standard_normal(4096),
        channels={"LFE": rng.standard_normal(4096)},
        coverage="complete_programme",
    )


def analysis() -> C.Analysis:
    rng = np.random.default_rng(1)
    freqs = np.geomspace(4.0, 200.0, 64)
    channel = ChannelDiagnosis(
        name="LFE",
        response_db=rng.standard_normal(64),
        share=rng.random(64),
        max_slope_db_per_octave=15.9,
        max_slope_hz=19.5,
        passband_share=0.81,
        is_filtered=True,
        plateau_hz=(25.8, 52.2),
    )
    diagnosis = Diagnosis(
        freqs=freqs,
        mix_db=rng.standard_normal(64),
        channels={"LFE": channel},
        stratified={"p40-80": rng.standard_normal(64)},
        level_spread_db=rng.standard_normal(64),
        filter_floor_hz=22.5,
        noise_floor_hz=math.nan,
    )
    envelopes = Envelopes(
        freqs=freqs,
        mean_db=rng.standard_normal(64),
        peak_db=rng.standard_normal(64),
        quiet_db=rng.standard_normal(64),
        coherence=rng.random(64),
        reference_band_hz=(60.0, 120.0),
        loud_frames=593,
        quiet_frames=2461,
        total_frames=13247,
        margin_se_db=np.where(rng.random(64) > 0.5, rng.random(64), np.inf),
    )
    identification = Identification(
        fit=RolloffFit(18.4, 15.4, 64.0, 1.96),
        rolloff=HighPass(Alignment.BUTTERWORTH, 2, 18.4),
        improvement_db=0.69,
        smooth_residual_db=1.96,
        weighted_bins=221,
        coherent_bandwidth_octaves=5.0,
        min_improvement_db=0.1,
    )
    return C.Analysis(diagnosis, envelopes, identification)


def analysis_key(subject: Material | None = None) -> dict:
    return C.key_for(
        "analysis",
        C.ANALYSIS_MODULES,
        subject or material(),
        DiagnoseParams(),
        ExtractionParams(),
        IdentifyParams(),
    )


def store_analysis(path) -> None:
    C.store(path, "analysis", analysis_key(), C.analysis_to_json(analysis()))


def test_analysis_round_trip_is_bit_identical(tmp_path) -> None:
    path = tmp_path / "c.json.gz"
    store_analysis(path)
    after = C.analysis_from_json(C.load(path, "analysis", analysis_key()))
    before = analysis()

    for name in ("freqs", "mix_db", "level_spread_db"):
        assert np.array_equal(
            getattr(before.diagnosis, name), getattr(after.diagnosis, name)
        )
    assert np.array_equal(
        before.diagnosis.stratified["p40-80"], after.diagnosis.stratified["p40-80"]
    )
    a, b = before.diagnosis.channels["LFE"], after.diagnosis.channels["LFE"]
    assert np.array_equal(a.response_db, b.response_db)
    assert np.array_equal(a.share, b.share)
    assert (a.max_slope_db_per_octave, a.plateau_hz, a.is_filtered) == (
        b.max_slope_db_per_octave,
        b.plateau_hz,
        b.is_filtered,
    )
    for name in (
        "freqs",
        "mean_db",
        "peak_db",
        "quiet_db",
        "coherence",
        "margin_se_db",
    ):
        assert np.array_equal(
            getattr(before.envelopes, name), getattr(after.envelopes, name)
        )
    assert after.envelopes.total_frames == before.envelopes.total_frames
    assert after.identification == before.identification


def test_a_nan_floor_survives_the_round_trip(tmp_path) -> None:
    """NaN is not JSON, and it is the answer when content reaches the bottom of the band."""
    path = tmp_path / "c.json.gz"
    store_analysis(path)
    after = C.analysis_from_json(C.load(path, "analysis", analysis_key()))
    assert math.isnan(after.diagnosis.noise_floor_hz)
    assert after.diagnosis.filter_floor_hz == 22.5


def test_an_absent_identification_survives(tmp_path) -> None:
    path = tmp_path / "c.json.gz"
    without = C.Analysis(analysis().diagnosis, analysis().envelopes, None)
    C.store(path, "analysis", analysis_key(), C.analysis_to_json(without))
    after = C.analysis_from_json(C.load(path, "analysis", analysis_key()))
    assert after.identification is None


def test_proposals_round_trip(tmp_path) -> None:
    """Both shapes a proposal takes: a curve to fit, and a cascade already known."""
    grid = np.geomspace(3.0, 400.0, 400)
    before = [
        Proposal("flatten", target_db=np.sin(grid), notes=("a note",)),
        Proposal(
            "parametric",
            filters=[BiquadSpec("low_shelf", 18.4, 12.5, 0.707)],
            residual_db=0.432,
        ),
    ]
    key = C.key_for("parametric", C.PARAMETRIC_MODULES, material(), DiagnoseParams())
    C.store(tmp_path / "c.json.gz", "parametric", key, C.proposals_to_json(before))
    after = C.proposals_from_json(
        C.load(tmp_path / "c.json.gz", "parametric", key), Proposal
    )
    assert [p.label for p in after] == ["flatten", "parametric"]
    assert np.array_equal(after[0].target_db, before[0].target_db)
    assert after[0].notes == ("a note",)
    assert after[1].target_db is None
    assert after[1].filters == before[1].filters
    assert after[1].residual_db == 0.432


@pytest.mark.parametrize("field", ["schema", "stage", "material", "params", "modules"])
def test_every_key_field_is_load_bearing(tmp_path, field) -> None:
    path = tmp_path / "c.json.gz"
    store_analysis(path)
    moved = dict(analysis_key())
    moved[field] = "something else"
    assert C.load(path, "analysis", moved) is None


def test_different_material_is_a_miss(tmp_path) -> None:
    path = tmp_path / "c.json.gz"
    store_analysis(path)
    assert C.load(path, "analysis", analysis_key(material(seed=99))) is None


def test_stages_do_not_evict_each_other(tmp_path) -> None:
    """One file, several stages. Writing the fit must not drop the analysis."""
    path = tmp_path / "c.json.gz"
    store_analysis(path)
    key = C.key_for("parametric", C.PARAMETRIC_MODULES, material(), DiagnoseParams())
    C.store(path, "parametric", key, C.proposals_to_json([Proposal("parametric")]))
    assert C.load(path, "analysis", analysis_key()) is not None
    assert C.load(path, "parametric", key) is not None


def test_an_absent_or_corrupt_cache_is_a_miss(tmp_path) -> None:
    assert C.load(tmp_path / "nothing.json.gz", "analysis", analysis_key()) is None
    corrupt = tmp_path / "corrupt.json.gz"
    corrupt.write_bytes(b"not gzip at all")
    assert C.load(corrupt, "analysis", analysis_key()) is None
    assert C.load(None, "analysis", analysis_key()) is None


def test_the_module_sets_name_what_each_stage_is_computed_by() -> None:
    """The key's correctness argument, asserted rather than left to a comment.

    A module a stage can reach and that is not listed leaves a stale answer looking fresh.
    `filters.py` reaches the *package root* for its RBJ classes, which is why the parametric
    set carries a bare `__init__.py` as well as `design/__init__.py`.
    """
    assert set(C.ANALYSIS_MODULES) == {
        "design/__init__.py",
        "design/diagnose.py",
        "design/extraction.py",
        "design/identify.py",
        "design/material.py",
        "design/rolloff.py",
    }
    assert set(C.PARAMETRIC_MODULES) >= set(C.ANALYSIS_MODULES) | {
        "__init__.py",
        "design/design.py",
        "design/filters.py",
        "design/pipeline.py",
    }
    for name in C.ANALYSIS_MODULES + C.PARAMETRIC_MODULES:
        assert (C._package_root() / name).is_file(), name


def test_only_the_strategy_that_fits_declares_a_cache() -> None:
    """`flatten` and `counterfactual` derive a curve; `parametric` runs an optimiser."""
    assert STRATEGIES["parametric"].cache_modules == C.PARAMETRIC_MODULES
    assert STRATEGIES["flatten"].cache_modules is None
    assert STRATEGIES["counterfactual"].cache_modules is None
