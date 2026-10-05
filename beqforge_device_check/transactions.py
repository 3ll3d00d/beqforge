"""Recoverable case transactions and qualified identity references."""

import json
import logging
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

logger = logging.getLogger(__name__)


def sweep_seconds(settings: SweepSettings) -> float:
    return settings.preroll_s + settings.duration_s + settings.tail_s


def case_seconds(settings: SweepSettings, case: dict) -> float:
    """Wall time of one measurement: its settling wait and its own sweep."""
    settle = case["settling_seconds"] or 0
    return settle + sweep_seconds(settings.for_settling(settle))


def eta(sweeps: int, seconds: float) -> str:
    return f"{sweeps} sweeps, about {seconds / 60:.1f} min"


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


def covers(qualification: dict, manifest: dict) -> bool:
    """Whether a completed qualification proves this manifest, though built for another.

    Identity, bypass and direct loopback never involve the cascades under test, so they
    carry over whenever the identity case and levels match; convergence must have been
    shown for every planned cascade here.
    """
    if not qualification.get("qualified") or "convergence_covers" not in qualification:
        return False
    identity = next(c["id"] for c in manifest["cases"] if c["name"] == "identity")
    planned = {
        c["id"]
        for c in manifest["cases"]
        if c["status"] == "planned" and c["name"] != "identity"
    }
    levels = {f"qualification-{level:g}.npz" for level in manifest["levels_dbfs"]}
    return (
        qualification.get("identity_case") == identity
        and set(qualification["reference_files"]) == levels
        and planned <= set(qualification["convergence_covers"])
    )


def bench_hash(config: dict) -> str:
    # Qualification identity includes the complete route, levels, stream settings,
    # engine build/firmware and restoration assumptions, not only a profile name.
    return digest(config)


def restore_state(engine: Engine, snapshot: dict) -> tuple[bool, list[str]]:
    errors = []
    logger.info("Restoring device state")
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
    if errors:
        logger.error("Restoration problems: %s", "; ".join(errors))
    elif restored:
        logger.info("Device state restored and verified")
    else:
        logger.info("Restoration commands sent, unverified; device left muted")
    return restored, errors


def recompute(directory: Path, attempt: str, config: dict, size: int) -> dict:
    """Recover a saved attempt again at FFT length `size`, from its raw sweep.

    A cascade with a long settling time gets a long tail, so a longer capture and a finer
    grid than the identity sweeps it is divided by. Re-deconvolving the identity's exact
    stimulus and capture at that length puts it on the same grid exactly: both signals
    are finite, so the longer zero-padding cannot wrap.
    """
    with np.load(directory / "stimuli" / f"{attempt}.npz", allow_pickle=False) as x:
        stimulus = x["samples"].copy()
    with np.load(directory / "captures" / f"{attempt}.npz", allow_pickle=False) as y:
        captured = y["samples"].copy()
    metadata = json.loads((directory / "stimuli" / f"{attempt}.json").read_text())
    stream = json.loads((directory / "captures" / f"{attempt}.json").read_text())
    dut = config.get("audio", {}).get("input", {}).get("channel", 0)
    reference = config.get("reference_channel")
    result = recover(
        stimulus,
        captured[:, dut],
        metadata,
        reference=captured[:, reference] if reference is not None else None,
        statuses=[str(s) for s in stream.get("statuses", []) if s],
        size=size,
    )
    if not result["valid"]:
        raise ValueError(
            f"saved attempt {attempt} no longer recovers: {result['failures']}"
        )
    return result


def measure(
    directory: Path,
    case: dict,
    settings: SweepSettings,
    engine: Engine,
    capture,
    *,
    reference_channel: int | None = None,
    progress: str = "",
) -> dict:
    attempt = uuid.uuid4().hex
    settle = case["settling_seconds"] or 0
    if settle > 60:
        raise ValueError("settling exceeds the supported 60-second control bound")
    # The tail covers this cascade's own decay, not the slowest one in the manifest.
    settings = settings.for_settling(settle)
    label = f"{progress + ' ' if progress else ''}{case['name']} @ {settings.level_dbfs:g} dBFS"
    started = time.monotonic()
    logger.info(
        "%s: loading %d section(s), then a %.1f s sweep (%g-%g Hz, %.1f s tail) [%s]",
        label,
        len(case["exact_sos"]),
        sweep_seconds(settings),
        settings.low_hz,
        settings.high_hz,
        settings.tail_s,
        attempt[:8],
    )
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
        logger.error("%s: capture interrupted: %s", label, error)
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
        logger.error("%s: invalid: %s", label, "; ".join(result["failures"]))
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
    usable = arrays["mask"]
    logger.info(
        "%s: done in %.0f s; %d/%d bins usable, lowest usable SNR %s, delay %d samples%s",
        label,
        time.monotonic() - started,
        int(np.count_nonzero(usable)),
        len(usable),
        f"{np.min(arrays['snr_db'][usable]):.1f} dB" if np.any(usable) else "n/a",
        result["delay_samples"],
        f", drift {result['drift_ppm']:.2f} ppm"
        if result.get("drift_ppm") is not None
        else "",
    )
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
    repeats = max(5, manifest["identity_repeats"])
    total = repeats * len(manifest["levels_dbfs"])
    logger.info(
        "%s qualification: %d repeats at %s dBFS = %s; evidence in %s",
        stage,
        repeats,
        ", ".join(f"{level:g}" for level in manifest["levels_dbfs"]),
        eta(total, total * case_seconds(settings, identity)),
        directory,
    )
    results = []
    with run_lock(directory):
        snapshot = engine.snapshot()
        atomic_json(directory / "bench.json", config)
        atomic_json(directory / "manifest.json", manifest)
        try:
            for level in manifest["levels_dbfs"]:
                traces, masks, biases, noise_bounds = [], [], [], []
                for _ in range(repeats):
                    result = measure(
                        directory,
                        identity,
                        replace(settings, level_dbfs=level),
                        engine,
                        capture,
                        reference_channel=config.get("reference_channel"),
                        progress=f"[{len(results) + 1}/{total}]",
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
                logger.info(
                    "%g dBFS: %d/%d bins within the %.3g dB uncertainty budget%s",
                    level,
                    int(np.count_nonzero(valid)),
                    len(valid),
                    accuracy_db / 3,
                    f" ({frequencies[valid][0]:.2f}-{frequencies[valid][-1]:.1f} Hz)"
                    if np.any(valid)
                    else "",
                )
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
            logger.info(
                "%s stage complete: %s (not qualified until every stage is assembled)",
                stage,
                directory / "qualification.json",
            )
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
    if qualification["bench_hash"] != bench_hash(config) or (
        qualification["manifest_hash"] != manifest["hash"]
        and not covers(qualification, manifest)
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
        planned = [
            cases[c] for c in manifest["order"] if cases[c]["status"] == "planned"
        ]
        total = len(manifest["levels_dbfs"]) * (1 + 2 * len(planned))
        seconds = len(manifest["levels_dbfs"]) * (
            case_seconds(settings, identity)
            + sum(
                case_seconds(settings, case) + case_seconds(settings, identity)
                for case in planned
            )
        )
        swept = [0]

        def counter() -> str:
            swept[0] += 1
            return f"[{swept[0]}/{total}]"

        logger.info(
            "run: %d planned case(s) bracketed by identities at %s dBFS = up to %s%s",
            len(planned),
            ", ".join(f"{level:g}" for level in manifest["levels_dbfs"]),
            eta(total, seconds),
            f"; resuming with {len(summary['completed'])} already done"
            if summary["completed"]
            else "",
        )
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
                    progress=counter(),
                )
                for ordinal, case_id in enumerate(manifest["order"]):
                    key = digest(
                        [manifest["hash"], bench_hash(config), level, ordinal, case_id]
                    )
                    if any(item["key"] == key for item in summary["completed"]):
                        continue
                    case = cases[case_id]
                    if case["status"] != "planned":
                        logger.info(
                            "%s @ %g dBFS: %s, not measured (%s)",
                            case["name"],
                            level,
                            case["status"],
                            case["reason"],
                        )
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
                        progress=counter(),
                    )
                    after = measure(
                        directory,
                        identity,
                        replace(settings, level_dbfs=level),
                        engine,
                        capture,
                        reference_channel=config.get("reference_channel"),
                        progress=counter(),
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
                        worst = np.max(np.abs(drift[mask])) if np.any(mask) else None
                        if worst is None or worst > qualification["accuracy_db"] / 3:
                            logger.error(
                                "%s @ %g dBFS: identity bracket drift %s exceeds %.3g dB",
                                case["name"],
                                level,
                                "unmeasurable" if worst is None else f"{worst:.4f} dB",
                                qualification["accuracy_db"] / 3,
                            )
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
                    logger.info(
                        "%s @ %g dBFS: measured; identity bracket drift %.4f dB",
                        case["name"],
                        level,
                        worst,
                    )
                    before = after
            summary["complete"] = True
            logger.info("run complete: %d case result(s)", len(summary["completed"]))
        except BaseException as error:
            logger.error("run stopped: %s: %s", type(error).__name__, error)
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
