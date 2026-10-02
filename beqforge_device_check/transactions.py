"""Recoverable case transactions and qualified identity references."""

import json
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Protocol

import numpy as np
from scipy.signal import sosfilt

from beqforge_device_check.coefficients import rounded, stable
from beqforge_device_check.evidence import (
    append,
    atomic_arrays,
    atomic_bytes,
    atomic_json,
    evidence_name,
    file_hash,
    register,
    run_lock,
)
from beqforge_device_check.manifest import digest, validate
from beqforge_device_check.measurement import (
    CaptureInterrupted,
    SweepSettings,
    recover,
    sweep,
)


class Engine(Protocol):
    def identify(self) -> dict: ...
    def snapshot(self) -> dict: ...
    def mute(self, value: bool) -> None: ...
    def load(self, case: dict) -> dict: ...
    def restore(self, snapshot: dict) -> bool: ...


class Simulation:
    """Numerical control with actual time-domain filtering, never hardware evidence."""

    live = False

    def __init__(self, rate: int, model: str = "float64", arithmetic: str = "float64"):
        if arithmetic not in ("float32", "float64"):
            raise ValueError("simulation arithmetic must be float32 or float64")
        self.rate = rate
        self.model = model
        self.arithmetic = arithmetic
        self.sos = np.empty((0, 6))
        self.muted = False

    def identify(self) -> dict:
        return {
            "engine": "simulation",
            "rate": self.rate,
            "model": self.model,
            "arithmetic": f"SciPy sosfilt {self.arithmetic}; not a device implementation model",
            "scope": "file-in/file-out numerical control",
            "numpy": np.__version__,
        }

    def snapshot(self) -> dict:
        return {"sos": self.sos.tolist(), "muted": self.muted}

    def mute(self, value: bool) -> None:
        self.muted = value

    def load(self, case: dict) -> dict:
        if case["rate"] != self.rate:
            raise ValueError("simulation internal rate mismatch")
        sent = np.asarray(case.get("transport_sos", case["exact_sos"])).reshape(-1, 6)
        self.sos = rounded(
            sent,
            self.model,
        )
        if not stable(self.sos):
            raise ValueError("unstable simulation coefficients")
        return {
            "sent_sos": sent.tolist(),
            "readback_sos": self.sos.tolist(),
            "storage_verified": True,
            "model": self.model,
        }

    def capture(self, stimulus: np.ndarray, rate: int) -> tuple[np.ndarray, dict]:
        if self.muted or rate != self.rate:
            raise ValueError("simulation is muted or rate differs")
        dtype = np.float32 if self.arithmetic == "float32" else np.float64
        y = (
            sosfilt(self.sos.astype(dtype), stimulus.astype(dtype))
            if len(self.sos)
            else stimulus.astype(dtype)
        )
        return y[:, None], {
            "format": self.arithmetic,
            "statuses": [],
            "scope": "numerical control",
        }

    def restore(self, snapshot: dict) -> bool:
        self.sos = np.asarray(snapshot["sos"]).reshape(-1, 6)
        self.muted = snapshot["muted"]
        return True


def bench_hash(config: dict) -> str:
    # Qualification identity includes the complete route, levels, stream settings,
    # engine build/firmware and restoration assumptions, not only a profile name.
    return digest(config)


def restore_state(engine: Engine, snapshot: dict) -> tuple[bool, list[str]]:
    errors = []
    try:
        engine.mute(True)
        restored = engine.restore(snapshot)
    except Exception as error:  # noqa: BLE001 - save any adapter failure during emergency restoration
        errors.append(f"restoration: {type(error).__name__}: {error}")
        restored = False
    if not restored:
        try:
            engine.mute(True)
        except Exception as error:  # noqa: BLE001 - save any adapter failure during emergency restoration
            errors.append(f"could not verify final mute: {error}")
    return restored, errors


def measure(
    directory: Path,
    case: dict,
    settings: SweepSettings,
    engine: Engine,
    capture,
    *,
    reference_channel: int | None = None,
) -> dict:
    attempt = uuid.uuid4().hex
    log = directory / "attempts.jsonl"
    append(
        log,
        {
            "attempt": attempt,
            "state": "planned",
            "case": case["id"],
            "settings": asdict(settings),
        },
    )
    engine.mute(True)
    payload = engine.load(case)
    atomic_json(directory / "transport" / f"{attempt}.json", payload)
    append(log, {"attempt": attempt, "state": "loaded"})
    x, metadata = sweep(settings)
    atomic_arrays(directory / "stimuli" / f"{attempt}.npz", samples=x)
    atomic_json(directory / "stimuli" / f"{attempt}.json", metadata)
    settle = case["settling_seconds"] or 0
    if settle > settings.tail_s:
        raise ValueError("tail is shorter than the cascade's required linear decay")
    if settle > 60:
        raise ValueError("settling exceeds the supported 60-second control bound")
    engine.mute(False)
    if settle and getattr(engine, "live", True):
        time.sleep(settle)
    try:
        y, stream = capture.capture(x, settings.rate)
    except CaptureInterrupted as error:
        atomic_arrays(directory / "captures" / f"{attempt}.npz", samples=error.samples)
        atomic_json(directory / "captures" / f"{attempt}.json", error.metadata)
        append(
            log,
            {
                "attempt": attempt,
                "state": "failed",
                "failures": [str(error)],
                "partial_capture": True,
            },
        )
        raise
    if y.ndim != 2 or y.shape[0] != len(x):
        raise ValueError("capture backend returned missing samples")
    atomic_arrays(directory / "captures" / f"{attempt}.npz", samples=y)
    atomic_json(directory / "captures" / f"{attempt}.json", stream)
    append(log, {"attempt": attempt, "state": "captured"})
    dut_channel = getattr(capture, "config", {}).get("input", {}).get("channel", 0)
    result = recover(
        x,
        y[:, dut_channel],
        metadata,
        reference=y[:, reference_channel] if reference_channel is not None else None,
        statuses=[str(s) for s in stream.get("statuses", []) if s],
    )
    if not result["valid"]:
        append(
            log, {"attempt": attempt, "state": "failed", "failures": result["failures"]}
        )
        raise ValueError("; ".join(result["failures"]))
    arrays = {
        k: result.pop(k)
        for k in (
            "frequencies",
            "response",
            "mask",
            "snr_db",
            "inversion_bias_db",
            "impulse",
        )
    }
    atomic_arrays(directory / "analysis" / f"{attempt}.npz", **arrays)
    result.update(
        {"attempt": attempt, "case": case["id"], "level_dbfs": settings.level_dbfs}
    )
    atomic_json(directory / "analysis" / f"{attempt}.json", result)
    append(
        log,
        {
            "attempt": attempt,
            "state": "completed",
            "case": case["id"],
            "level_dbfs": settings.level_dbfs,
        },
    )
    return result


def qualify(
    config: dict,
    manifest: dict,
    directory: Path,
    engine: Engine,
    capture,
    settings: SweepSettings,
    *,
    accuracy_db: float,
    stage: str = "identity",
    path_description: str | None = None,
) -> dict:
    validate(manifest)
    if stage not in ("identity", "direct-loopback", "device-bypass"):
        raise ValueError("unsupported repeatability qualification stage")
    if stage != "identity" and not path_description:
        raise ValueError("describe the actual direct/bypass measurement path")
    if getattr(engine, "live", True) and not config.get(
        "electrical_bench_acknowledged"
    ):
        raise ValueError(
            "explicit disconnected electrical-bench acknowledgement is required"
        )
    if accuracy_db <= 0 or not np.isfinite(accuracy_db):
        raise ValueError("predeclare a positive engineering accuracy requirement")
    identity = next(case for case in manifest["cases"] if case["name"] == "identity")
    results = []
    with run_lock(directory):
        snapshot = engine.snapshot()
        atomic_json(directory / "bench.json", config)
        atomic_json(directory / "manifest.json", manifest)
        try:
            for level in manifest["levels_dbfs"]:
                traces, masks, biases, noise_bounds = [], [], [], []
                for _ in range(max(5, manifest["identity_repeats"])):
                    result = measure(
                        directory,
                        identity,
                        replace(settings, level_dbfs=level),
                        engine,
                        capture,
                        reference_channel=config.get("reference_channel"),
                    )
                    results.append(result)
                    with np.load(
                        directory / "analysis" / f"{result['attempt']}.npz",
                        allow_pickle=False,
                    ) as arrays:
                        frequencies = arrays["frequencies"].copy()
                        traces.append(arrays["response"].copy())
                        masks.append(arrays["mask"].copy())
                        biases.append(arrays["inversion_bias_db"].copy())
                        noise_bounds.append(
                            -20
                            * np.log10(
                                np.maximum(1 - 10 ** (-arrays["snr_db"] / 20), 1e-15)
                            )
                        )
                magnitudes = 20 * np.log10(np.maximum(np.abs(traces), 1e-300))
                uncertainty = (
                    np.max(np.abs(magnitudes - np.median(magnitudes, axis=0)), axis=0)
                    * 2
                    + 2 * np.max(biases, axis=0)
                    + 2 * np.max(noise_bounds, axis=0)
                )
                valid = np.all(masks, axis=0) & (uncertainty < accuracy_db / 3)
                atomic_arrays(
                    directory / "analysis" / f"qualification-{level:g}.npz",
                    frequencies=frequencies,
                    uncertainty_db=uncertainty,
                    mask=valid,
                    references=np.asarray(traces),
                )
            qualification = {
                "schema_version": 1,
                "stage": stage,
                "path_description": path_description,
                "bench_hash": bench_hash(config),
                "manifest_hash": manifest["hash"],
                "settings": asdict(settings),
                "accuracy_db": accuracy_db,
                "engine": engine.identify(),
                "results": results,
                "scope": "identity repeatability only; convergence/direct-loopback/bypass still required",
                "qualified": False,
                "reference_files": {
                    f"qualification-{level:g}.npz": file_hash(
                        directory / "analysis" / f"qualification-{level:g}.npz"
                    )
                    for level in manifest["levels_dbfs"]
                },
            }
            qualification["hash"] = digest(qualification)
            atomic_json(directory / "qualification.json", qualification)
            return qualification
        finally:
            restored, errors = restore_state(engine, snapshot)
            atomic_json(
                directory / "run.json",
                {
                    "restored": restored,
                    "restoration_errors": errors,
                    "engine": engine.identify(),
                },
            )
            register(directory)


def run(
    config: dict,
    manifest: dict,
    qualification_dir: Path,
    directory: Path,
    engine: Engine,
    capture,
    *,
    resume: bool = False,
) -> dict:
    validate(manifest)
    if (directory / "bundle-import.json").exists():
        raise ValueError(
            "imported evidence is for offline analysis; use a new local measurement run"
        )
    qualification = json.loads((qualification_dir / "qualification.json").read_text())
    if qualification["hash"] != digest(
        {k: v for k, v in qualification.items() if k != "hash"}
    ):
        raise ValueError("qualification hash mismatch")
    if (
        qualification["bench_hash"] != bench_hash(config)
        or qualification["manifest_hash"] != manifest["hash"]
    ):
        raise ValueError("qualification is stale for this bench/manifest")
    if not qualification["qualified"] and getattr(engine, "live", True):
        raise ValueError(
            "live bench is not qualified: complete loopback/bypass/convergence checks"
        )
    settings = SweepSettings(**qualification["settings"])
    if qualification["engine"] != engine.identify():
        raise ValueError("qualification engine/build identity differs")
    if getattr(engine, "live", True) and not config.get(
        "electrical_bench_acknowledged"
    ):
        raise ValueError(
            "explicit disconnected electrical-bench acknowledgement is required"
        )
    with run_lock(directory):
        identity = next(
            case for case in manifest["cases"] if case["name"] == "identity"
        )
        prior = directory / "run.json"
        if prior.exists() and not resume:
            raise ValueError("run already exists; use explicit resume")
        if prior.exists():
            old = json.loads(prior.read_text())
            if old.get("manifest_hash") != manifest["hash"] or old.get(
                "bench_hash"
            ) != bench_hash(config):
                raise ValueError("resume identity differs")
        snapshot = engine.snapshot()
        summary = {
            "schema_version": 1,
            "manifest_hash": manifest["hash"],
            "bench_hash": bench_hash(config),
            "engine": engine.identify(),
            "snapshot": snapshot,
            "completed": [],
            "failures": [],
            "scope": engine.identify()["scope"],
        }
        if prior.exists():
            summary["completed"] = old["completed"]
            summary["failures"] = old["failures"]
        atomic_json(prior, summary)
        atomic_json(directory / "bench.json", config)
        atomic_json(directory / "manifest.json", manifest)
        atomic_json(directory / "qualification.json", qualification)
        for name, expected_hash in qualification["reference_files"].items():
            if Path(name).name != name:
                raise ValueError("invalid qualification reference path")
            path = qualification_dir / "analysis" / name
            if file_hash(path) != expected_hash:
                raise ValueError("qualification reference evidence changed")
            atomic_bytes(directory / "analysis" / name, path.read_bytes())
        for relative, expected_hash in qualification.get(
            "supporting_files", {}
        ).items():
            if not evidence_name(relative) or relative.split("/")[0] not in (
                "captures",
                "stimuli",
                "analysis",
                "transport",
            ):
                raise ValueError("invalid supporting qualification evidence path")
            path = qualification_dir / relative
            if file_hash(path) != expected_hash:
                raise ValueError("supporting qualification evidence changed")
            atomic_bytes(directory / relative, path.read_bytes())
        cases = {case["id"]: case for case in manifest["cases"]}
        try:
            for level in manifest["levels_dbfs"]:
                # Resume always starts with a newly loaded identity, never trusting stale state.
                before = measure(
                    directory,
                    identity,
                    replace(settings, level_dbfs=level),
                    engine,
                    capture,
                    reference_channel=config.get("reference_channel"),
                )
                for ordinal, case_id in enumerate(manifest["order"]):
                    key = digest(
                        [manifest["hash"], bench_hash(config), level, ordinal, case_id]
                    )
                    if any(item["key"] == key for item in summary["completed"]):
                        continue
                    case = cases[case_id]
                    if case["status"] != "planned":
                        summary["completed"].append(
                            {
                                "key": key,
                                "case": case_id,
                                "status": case["status"],
                                "reason": case["reason"],
                            }
                        )
                        atomic_json(prior, summary)
                        continue
                    result = measure(
                        directory,
                        case,
                        replace(settings, level_dbfs=level),
                        engine,
                        capture,
                        reference_channel=config.get("reference_channel"),
                    )
                    after = measure(
                        directory,
                        identity,
                        replace(settings, level_dbfs=level),
                        engine,
                        capture,
                        reference_channel=config.get("reference_channel"),
                    )
                    with (
                        np.load(
                            directory / "analysis" / f"{before['attempt']}.npz",
                            allow_pickle=False,
                        ) as left,
                        np.load(
                            directory / "analysis" / f"{after['attempt']}.npz",
                            allow_pickle=False,
                        ) as right,
                    ):
                        mask = left["mask"] & right["mask"]
                        drift = 20 * np.log10(
                            np.maximum(
                                np.abs(right["response"] / left["response"]), 1e-300
                            )
                        )
                        if (
                            not np.any(mask)
                            or np.max(np.abs(drift[mask]))
                            > qualification["accuracy_db"] / 3
                        ):
                            raise ValueError(
                                "identity bracket drift exceeds frozen uncertainty budget"
                            )
                    # Do not complete a case until both reference brackets are saved.
                    summary["completed"].append(
                        {
                            "key": key,
                            "case": case_id,
                            "status": "measured",
                            "result": result,
                            "before": before["attempt"],
                            "after": after["attempt"],
                        }
                    )
                    atomic_json(prior, summary)
                    before = after
            summary["complete"] = True
        except BaseException as error:
            summary["failures"].append(
                {"type": type(error).__name__, "reason": str(error)}
            )
            summary["complete"] = False
            raise
        finally:
            summary["restored"], summary["restoration_errors"] = restore_state(
                engine, snapshot
            )
            atomic_json(prior, summary)
            register(directory)
    return summary
