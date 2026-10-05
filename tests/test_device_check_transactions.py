import json
from dataclasses import replace

import numpy as np
import pytest

from beqforge_device_check.analyse import analyse
from beqforge_device_check.evidence import bundle, import_bundle, run_lock
from beqforge_device_check.manifest import digest, generate
from beqforge_device_check.measurement import CaptureInterrupted, SweepSettings
from beqforge_device_check.profiles import PROFILES
from beqforge_device_check.transactions import Simulation, measure, qualify, run


@pytest.fixture
def bench(tmp_path):
    pytest.importorskip("pyfar")
    manifest = generate(
        PROFILES["simulation-float64"], rate=48000, levels=(-30.0, -50.0)
    )
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
    from beqforge_device_check.evidence import atomic_json, register

    atomic_json(
        directory / "inventory.json",
        {
            "source": {"complete_snapshot_declared": True},
            "entries": [
                {
                    "id": "first",
                    "case": manifest["cases"][1]["id"],
                    "status": "planned",
                },
                {
                    "id": "duplicate",
                    "case": manifest["cases"][1]["id"],
                    "status": "planned",
                },
                {"id": "unsupported", "status": "unsupported", "reason": "capacity"},
            ],
        },
    )
    register(directory)
    report = analyse(directory, directory)
    assert len(report["results"]) == 6
    assert max(item["exact"]["worst_db"] for item in report["results"]) < 0.002
    assert (directory / "report.html").exists()
    assert (directory / "charts" / "catalogue-population.png").exists()
    assert report["catalogue"]["unique_cascade_weighted"]["count"] == 1
    assert (
        report["results"][0]["accuracy_assessment"]["outcome"] == "within-requirement"
    )
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
    imported = tmp_path / "imported"
    import_bundle(tmp_path / "results.zip", imported)
    replayed = analyse(imported, tmp_path / "replayed")
    assert replayed["results"] == report["results"]
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


def test_interrupted_stream_retains_samples_and_metadata(tmp_path, bench):
    config, manifest, engine = bench

    class Interrupted:
        def capture(self, samples, rate):
            raise CaptureInterrupted(
                "input overflow",
                np.ones((64, 1), dtype=np.float32),
                {"valid": False, "sample_count": 64, "statuses": [2]},
            )

    directory = tmp_path / "partial"
    with pytest.raises(CaptureInterrupted, match="overflow"):
        run(
            config,
            manifest,
            tmp_path / "qualification",
            directory,
            engine,
            Interrupted(),
        )
    capture = next((directory / "captures").glob("*.npz"))
    with np.load(capture, allow_pickle=False) as data:
        assert data["samples"].shape == (64, 1)
    assert json.loads(capture.with_suffix(".json").read_text())["statuses"] == [2]
    assert json.loads((directory / "run.json").read_text())["restored"]


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


def test_storage_conversion_and_recursive_arithmetic_are_separate_controls():
    from scipy.signal import sosfilt

    case = generate(PROFILES["simulation-float64"], rate=48000)["cases"][1]
    samples = np.random.default_rng(123).normal(0, 0.01, 48000).astype(np.float32)
    storage_only = Simulation(48000, "float32", "float64")
    recursive = Simulation(48000, "float32", "float32")
    payload = storage_only.load(case)
    recursive.load(case)
    assert payload["sent_sos"] == case["exact_sos"]
    assert payload["readback_sos"] != payload["sent_sos"]
    first, _ = storage_only.capture(samples, 48000)
    second, metadata = recursive.capture(samples, 48000)
    assert first.dtype == np.float64 and second.dtype == np.float32
    assert metadata["format"] == "float32"
    expected = sosfilt(np.asarray(payload["readback_sos"], dtype=np.float32), samples)
    assert np.array_equal(second[:, 0], expected)
    assert np.max(np.abs(first[:, 0] - second[:, 0])) > 1e-7


def test_each_cascade_is_swept_with_its_own_settling_tail(tmp_path):
    pytest.importorskip("pyfar")
    manifest = generate(PROFILES["simulation-float64"], rate=48000)
    engine = Simulation(48000)
    settings = SweepSettings(rate=48000, duration_s=1, tail_s=0.5, preroll_s=0.25)
    identity = next(c for c in manifest["cases"] if c["name"] == "identity")
    slow = max(manifest["cases"], key=lambda c: c["settling_seconds"] or 0)
    assert slow["settling_seconds"] > settings.tail_s
    for case in (identity, slow):
        result = measure(tmp_path, case, settings, engine, engine)
        metadata = json.loads(
            (tmp_path / "stimuli" / f"{result['attempt']}.json").read_text()
        )
        # The identity keeps the short minimum; the ringing cascade gets its decay.
        assert metadata["settings"]["tail_s"] == max(
            settings.tail_s, case["settling_seconds"] or 0
        )
    # Convergence's tail variant doubles an extended tail too, not just the minimum.
    doubled = replace(settings, tail_s=1, settling_multiple=2)
    assert doubled.for_settling(slow["settling_seconds"]).tail_s == pytest.approx(
        2 * slow["settling_seconds"]
    )


def test_identities_bracket_groups_of_loads(tmp_path):
    pytest.importorskip("pyfar")
    manifest = generate(PROFILES["simulation-float64"], rate=48000)
    benign = next(c["id"] for c in manifest["cases"] if c["name"] == "benign")
    manifest["order"] = [benign] * 5
    manifest["identity_bracket_every"] = 2
    manifest["hash"] = digest({k: v for k, v in manifest.items() if k != "hash"})
    engine = Simulation(48000)
    config = {"profile": manifest["profile"], "route": "filter", "rate": 48000}
    settings = SweepSettings(rate=48000, duration_s=1, tail_s=0.5, preroll_s=0.25)
    qualify(config, manifest, tmp_path / "q", engine, engine, settings, accuracy_db=0.1)
    summary = run(config, manifest, tmp_path / "q", tmp_path / "run", engine, engine)
    assert summary["complete"]
    groups = {}
    for item in summary["completed"]:
        groups.setdefault((item["before"], item["after"]), []).append(item)
    # 5 loads, an identity after every 2: groups of 2, 2 and 1, sharing brackets.
    assert sorted(len(g) for g in groups.values()) == [1, 2, 2]
    befores = [before for before, _ in groups]
    afters = [after for _, after in groups]
    assert len(set(befores) | set(afters)) == 4
