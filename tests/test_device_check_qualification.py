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
