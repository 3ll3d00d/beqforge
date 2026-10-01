import json
from dataclasses import replace

import pytest

from beqforge_device_check.evidence import bundle, run_lock
from beqforge_device_check.manifest import digest, generate
from beqforge_device_check.measurement import SweepSettings
from beqforge_device_check.profiles import PROFILES
from beqforge_device_check.transactions import Simulation, qualify, run


@pytest.fixture
def bench(tmp_path):
    pytest.importorskip("pyfar")
    manifest = generate(PROFILES["simulation-float64"], rate=48000)
    manifest["order"] = [manifest["cases"][1]["id"]] * 3
    manifest["hash"] = digest({k: v for k, v in manifest.items() if k != "hash"})
    engine = Simulation(48000)
    config = {"profile": manifest["profile"], "route": "filter", "rate": 48000}
    settings = SweepSettings(rate=48000, duration_s=1, tail_s=2, preroll_s=0.25)
    qualify(
        config,
        manifest,
        tmp_path / "qualification",
        engine,
        engine,
        settings,
        accuracy_db=0.1,
    )
    return config, manifest, engine


def test_transaction_restore_resume_and_offline_bundle(tmp_path, bench):
    config, manifest, engine = bench
    directory = tmp_path / "run"
    state = engine.snapshot()
    summary = run(
        config, manifest, tmp_path / "qualification", directory, engine, engine
    )
    assert summary["complete"] and summary["restored"]
    assert engine.snapshot() == state
    assert len(summary["completed"]) == 6
    resumed = run(
        config,
        manifest,
        tmp_path / "qualification",
        directory,
        engine,
        engine,
        resume=True,
    )
    assert len(resumed["completed"]) == 6
    exported = bundle(directory, tmp_path / "results.zip")
    assert exported["replayable"]
    assert any(name.startswith("captures/") for name in exported["files"])
    (directory / "unrelated-secret.txt").write_text("do not export")
    partial = bundle(directory, tmp_path / "summary.zip", summary_only=True)
    assert not partial["replayable"]
    assert "unrelated-secret.txt" not in partial["files"]


def test_failed_capture_keeps_partial_evidence_and_restores(tmp_path, bench):
    config, manifest, engine = bench

    class BrokenCapture:
        def capture(self, samples, rate):
            raise TimeoutError("capture still active; no automatic retry")

    directory = tmp_path / "failed"
    with pytest.raises(TimeoutError):
        run(
            config,
            manifest,
            tmp_path / "qualification",
            directory,
            engine,
            BrokenCapture(),
        )
    summary = json.loads((directory / "run.json").read_text())
    assert not summary["complete"] and summary["restored"]
    assert summary["failures"][0]["type"] == "TimeoutError"
    assert list((directory / "stimuli").glob("*.npz"))
    assert not (directory / ".run.lock").exists()


def test_stale_qualification_and_concurrent_run_refused(tmp_path, bench):
    config, manifest, engine = bench
    with pytest.raises(ValueError, match="stale"):
        run(
            {**config, "rate": 96000},
            manifest,
            tmp_path / "qualification",
            tmp_path / "run",
            engine,
            engine,
        )
    with (
        run_lock(tmp_path / "locked"),
        pytest.raises(RuntimeError, match="locked"),
        run_lock(tmp_path / "locked"),
    ):
        pass


def test_live_identity_measurement_requires_disconnected_bench_ack(tmp_path, bench):
    config, manifest, _ = bench

    class NoAudio:
        pass

    with pytest.raises(ValueError, match="acknowledgement"):
        qualify(
            config,
            manifest,
            tmp_path / "live",
            NoAudio(),
            NoAudio(),
            replace(SweepSettings(), duration_s=1),
            accuracy_db=0.1,
        )
