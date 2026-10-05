import json

import pytest

from beqforge_device_check.manifest import digest, generate
from beqforge_device_check.measurement import SweepSettings
from beqforge_device_check.profiles import PROFILES
from beqforge_device_check.transactions import Simulation
from beqforge_device_check.verify import verify


def manifest_of(full: dict, names: list[str]) -> dict:
    manifest = dict(full)
    manifest["cases"] = [c for c in full["cases"] if c["name"] in ("identity", *names)]
    manifest["order"] = [c["id"] for c in manifest["cases"] if c["name"] in names]
    manifest["hash"] = digest({k: v for k, v in manifest.items() if k != "hash"})
    return manifest


def test_verify_measures_only_what_no_stored_stage_proves(tmp_path):
    pytest.importorskip("pyfar")
    full = generate(PROFILES["simulation-float64"], rate=48000)
    config = {
        "rate": 48000,
        "common_clock": True,
        "clock_basis": "numerical samples share one clock",
        "all_digital": True,
        "all_digital_basis": "numerical control",
    }
    engine = Simulation(48000)
    settings = SweepSettings(rate=48000, duration_s=1, tail_s=0.5, preroll_s=0.25)
    store = tmp_path / "store"

    def once(manifest, out):
        return verify(
            config,
            manifest,
            store,
            tmp_path / out,
            engine,
            engine,
            settings,
            accuracy_db=0.1,
        )

    first = once(manifest_of(full, ["benign"]), "first")
    assert first["measured"] == [
        "identity",
        "device-bypass",
        "convergence (1 cascade(s))",
    ]
    assert first["complete"] and first["restored"]
    assert [r["case"] for r in first["results"]] == ["benign", "benign"]
    qualification = json.loads(
        (tmp_path / "first" / "qualification" / "qualification.json").read_text()
    )
    assert qualification["qualified"]
    assert qualification["waived_stages"] == {"direct-loopback": "numerical control"}

    # Same bench, settings and cases: every stage is reused; only the run measures.
    again = once(manifest_of(full, ["benign"]), "again")
    assert again["measured"] == []
    assert again["complete"]

    # One new cascade: identity and bypass carry over; only it is converged.
    wider = once(manifest_of(full, ["benign", "sensitive"]), "wider")
    assert wider["measured"] == ["convergence (1 cascade(s))"]
    assert {r["case"] for r in wider["results"]} == {"benign", "sensitive"}

    # Results never overwrite.
    with pytest.raises(ValueError, match="already exists"):
        once(manifest_of(full, ["benign"]), "first")
    # Different sweep settings prove nothing about these: everything is measured again.
    longer = verify(
        config,
        manifest_of(full, ["benign"]),
        store,
        tmp_path / "longer",
        engine,
        engine,
        SweepSettings(rate=48000, duration_s=2, tail_s=0.5, preroll_s=0.25),
        accuracy_db=0.1,
    )
    assert "identity" in longer["measured"]
