import json

import numpy as np
import pytest

from beqforge_device_check.manifest import digest, generate
from beqforge_device_check.measurement import SweepSettings
from beqforge_device_check.profiles import PROFILES
from beqforge_device_check.qualification import (
    BypassReference,
    DirectReference,
    complete,
    convergence,
)
from beqforge_device_check.transactions import Simulation, qualify, run


def test_direct_reference_never_controls_a_device():
    engine = DirectReference()
    engine.mute(True)
    assert engine.load({})["sent_sos"] == []
    assert engine.restore(engine.snapshot())
    assert "no DUT control" in engine.identify()["scope"]


def test_bypass_is_explicit_and_capability_checked():
    with pytest.raises(ValueError, match="does not support"):
        BypassReference(Simulation(48000))

    class Engine:
        def load(self, case):
            return {"case": case}

        def bypass(self, case):
            return ["input", "0", "peq", "all", "bypass", "on"]

    payload = BypassReference(Engine()).load({})
    assert payload["bypass_command"][-2:] == ["bypass", "on"]


def test_qualification_stages_assemble_and_license_only_measured_bins(tmp_path):
    pytest.importorskip("pyfar")
    manifest = generate(PROFILES["simulation-float64"], rate=48000)
    manifest["cases"] = manifest["cases"][:2]
    manifest["levels_dbfs"] = [-30]
    manifest["order"] = [manifest["cases"][1]["id"]] * 3
    manifest["hash"] = digest({k: v for k, v in manifest.items() if k != "hash"})
    config = {
        "rate": 48000,
        "common_clock": True,
        "clock_basis": "numerical samples share the same clock",
    }
    engine = Simulation(48000)
    settings = SweepSettings(rate=48000, duration_s=1, tail_s=2, preroll_s=0.25)
    supporting = []
    for stage in ("identity", "direct-loopback", "device-bypass"):
        directory = tmp_path / stage
        qualify(
            config,
            manifest,
            directory,
            engine,
            engine,
            settings,
            accuracy_db=0.1,
            stage=stage,
            path_description="numerical control for stage assembly",
        )
        if stage != "identity":
            supporting.append(directory)
    result = convergence(
        config,
        manifest,
        tmp_path / "convergence",
        engine,
        engine,
        settings,
        accuracy_db=0.1,
    )
    assert len(result["results"]) == 6
    supporting.append(tmp_path / "convergence")
    with pytest.raises(ValueError, match="common-clock"):
        complete(tmp_path / "identity", supporting)
    result = complete(tmp_path / "identity", supporting, clock_verified=True)
    assert result["qualified"] and len(result["supporting_stages"]) == 3
    with np.load(
        tmp_path / "identity" / "analysis" / "qualification--30.npz", allow_pickle=False
    ) as data:
        assert np.any(data["mask"])
        # Each cascade's convergence is its own row, not pooled into the bench budget.
        assert data["cases"].tolist() == result["convergence_covers"]
        assert data["case_uncertainty_db"].shape == (1, len(data["frequencies"]))
        assert np.any(data["case_mask"])
    completed = run(
        config, manifest, tmp_path / "identity", tmp_path / "run", engine, engine
    )
    assert completed["complete"]
    for name in result["supporting_files"]:
        assert (tmp_path / "run" / name).is_file()
    with pytest.raises(ValueError, match="already complete"):
        complete(tmp_path / "identity", supporting, clock_verified=True)


def test_supporting_stage_cannot_promote_missing_or_stale_evidence(tmp_path):
    from beqforge_device_check.evidence import atomic_json

    base = {"stage": "identity", "qualified": False}
    atomic_json(tmp_path / "identity" / "qualification.json", base)
    with pytest.raises(ValueError, match="evidence are required"):
        complete(tmp_path / "identity", [], clock_verified=True)
    bad = {"stage": "convergence", "hash": "wrong"}
    atomic_json(tmp_path / "bad" / "qualification.json", bad)
    with pytest.raises(ValueError, match="hash mismatch"):
        complete(tmp_path / "identity", [tmp_path / "bad"], clock_verified=True)


def test_convergence_failure_restores_and_keeps_raw_evidence(tmp_path):
    pytest.importorskip("pyfar")
    manifest = generate(PROFILES["simulation-float64"], rate=48000)
    engine = Simulation(48000)
    settings = SweepSettings(rate=48000, duration_s=1, tail_s=2, preroll_s=0.25)

    class Failure:
        def capture(self, samples, rate):
            raise TimeoutError("no retry")

    with pytest.raises(TimeoutError):
        convergence(
            {}, manifest, tmp_path, engine, Failure(), settings, accuracy_db=0.1
        )
    assert json.loads((tmp_path / "run.json").read_text())["restored"]
    assert list((tmp_path / "stimuli").glob("*.npz"))
    assert not (tmp_path / "qualification.json").exists()


def test_all_digital_bench_completes_without_direct_loopback_and_says_so(tmp_path):
    pytest.importorskip("pyfar")
    manifest = generate(PROFILES["simulation-float64"], rate=48000)
    manifest["cases"] = manifest["cases"][:2]
    manifest["levels_dbfs"] = [-30]
    manifest["order"] = [manifest["cases"][1]["id"]]
    manifest["hash"] = digest({k: v for k, v in manifest.items() if k != "hash"})
    config = {"rate": 48000}
    engine = Simulation(48000)
    settings = SweepSettings(rate=48000, duration_s=1, tail_s=2, preroll_s=0.25)
    for stage in ("identity", "device-bypass"):
        qualify(
            config,
            manifest,
            tmp_path / stage,
            engine,
            engine,
            settings,
            accuracy_db=0.1,
            stage=stage,
            path_description="numerical control",
        )
    convergence(
        config,
        manifest,
        tmp_path / "convergence",
        engine,
        engine,
        settings,
        accuracy_db=0.1,
    )
    supporting = [tmp_path / "device-bypass", tmp_path / "convergence"]
    # Without the bench's own all-digital basis, the missing stage still refuses.
    with pytest.raises(ValueError, match="direct-loopback"):
        complete(tmp_path / "identity", supporting, clock_verified=True)
    basis = "the DUT's own USB audio interface"
    # The waiver covers only direct loopback: bypass and convergence stay required.
    with pytest.raises(ValueError, match="device-bypass and convergence"):
        complete(
            tmp_path / "identity",
            supporting[:1],
            clock_verified=True,
            direct_loopback_waiver=basis,
        )
    result = complete(
        tmp_path / "identity",
        supporting,
        clock_verified=True,
        direct_loopback_waiver=basis,
    )
    assert result["qualified"]
    assert result["waived_stages"] == {"direct-loopback": basis}
    assert "waived" in result["scope"]


def test_an_unsettled_cascade_widens_only_its_own_budget(tmp_path):
    """The real failure: one cascade's disagreement once masked every other filter."""
    from beqforge_device_check.analyse import qualified_budgets
    from beqforge_device_check.evidence import atomic_arrays

    frequencies = np.linspace(2, 200, 50)
    unsettled = np.where(frequencies < 40, 4.0, 0.001)
    atomic_arrays(
        tmp_path / "analysis" / "qualification--30.npz",
        frequencies=frequencies,
        uncertainty_db=np.full(50, 0.002),
        mask=np.ones(50, bool),
        cases=np.asarray(["settled", "unsettled"]),
        case_uncertainty_db=np.stack([np.full(50, 0.001), unsettled]),
        case_mask=np.ones((2, 50), bool),
    )
    _, bench, mask, per_case = qualified_budgets(
        tmp_path, {"accuracy_db": 0.1}, "qualification--30.npz", {}
    )
    assert np.all(mask) and np.all(bench < 0.1 / 3)
    assert np.max(per_case["settled"][0]) == 0.001
    assert np.max(per_case["unsettled"][0]) == 4.0
