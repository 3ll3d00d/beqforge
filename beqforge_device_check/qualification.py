"""Measured duration/tail convergence and offline qualification assembly."""

import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from beqforge_device_check.analyse import sample_trace
from beqforge_device_check.evidence import (
    atomic_arrays,
    atomic_bytes,
    atomic_json,
    evidence_name,
    file_hash,
    register,
    run_lock,
)
from beqforge_device_check.manifest import digest, validate
from beqforge_device_check.transactions import (
    bench_hash,
    case_seconds,
    measure,
    recompute,
    restore_state,
)

logger = logging.getLogger(__name__)


class DirectReference:
    """No device controls: operator reconnects the interface as a direct loopback."""

    live = True

    def identify(self):
        return {
            "engine": "direct-loopback",
            "scope": "operator-described direct interface loopback; no DUT control",
        }

    def snapshot(self):
        return {}

    def mute(self, value):
        pass

    def load(self, case):
        return {
            "sent_sos": [],
            "model": "float64",
            "storage_verified": False,
            "scope": "direct loopback; no device commands",
        }

    def restore(self, snapshot):
        return True


class BypassReference:
    """Bypass the selected PEQ bank, with the rest of the recorded route retained."""

    live = True

    def __init__(self, engine):
        if not hasattr(engine, "bypass"):
            raise ValueError("this engine does not support explicit PEQ-bank bypass")
        self.engine = engine

    def identify(self):
        return self.engine.identify()

    def snapshot(self):
        return self.engine.snapshot()

    def mute(self, value):
        self.engine.mute(value)

    def load(self, case):
        payload = self.engine.load(case)
        payload["bypass_command"] = self.engine.bypass(case)
        payload["scope"] = "selected PEQ bank bypass; not a bypass of all DSP stages"
        return payload

    def restore(self, snapshot):
        return self.engine.restore(snapshot)


def load_trace(directory, attempt):
    with np.load(
        directory / "analysis" / f"{attempt}.npz", allow_pickle=False
    ) as arrays:
        return {name: arrays[name].copy() for name in arrays.files}


def convergence(config, manifest, directory, engine, capture, settings, *, accuracy_db):
    """Double duration and tail independently on identity and every planned cascade.

    No pass criterion is based on agreement with a hypothesised storage model. Each
    filtered measurement has its own identity, so bench phase/gain are not fitted away.
    """
    validate(manifest)
    if not np.isfinite(accuracy_db) or accuracy_db <= 0:
        raise ValueError("predeclare a positive engineering accuracy requirement")
    if getattr(engine, "live", True) and not config.get(
        "electrical_bench_acknowledged"
    ):
        raise ValueError(
            "explicit disconnected electrical-bench acknowledgement is required"
        )
    identity = next(c for c in manifest["cases"] if c["name"] == "identity")
    variants = [
        settings,
        replace(settings, duration_s=settings.duration_s * 2),
        # Doubles every cascade's tail, including those extended to their settling time.
        replace(
            settings,
            tail_s=settings.tail_s * 2,
            settling_multiple=settings.settling_multiple * 2,
        ),
    ]
    names = ["standard", "double duration", "double tail"]
    filtered = [
        c
        for c in manifest["cases"]
        if c["status"] == "planned" and c["name"] != "identity"
    ]
    levels = manifest["levels_dbfs"]
    total = len(levels) * len(variants) * (1 + len(filtered))
    seconds = len(levels) * sum(
        case_seconds(variant, case)
        for variant in variants
        for case in [identity, *filtered]
    )
    swept = [0]

    def counter(index: int) -> str:
        swept[0] += 1
        return f"[{swept[0]}/{total}] {names[index]}"

    logger.info(
        "convergence: identity and %d cascade(s) x %d sweep variants at %s dBFS"
        " = %d sweeps, about %.1f min",
        len(filtered),
        len(variants),
        ", ".join(f"{level:g}" for level in levels),
        total,
        seconds / 60,
    )
    record = {
        "schema_version": 1,
        "stage": "convergence",
        "bench_hash": bench_hash(config),
        "manifest_hash": manifest["hash"],
        "settings": asdict(settings),
        "accuracy_db": accuracy_db,
        "engine": engine.identify(),
        "results": [],
        "reference_files": {},
        # Which cascades this record proves converged, so another manifest can reuse it.
        "covers": sorted(case["id"] for case in filtered),
        "identity_case": identity["id"],
        "qualified": False,
        "scope": "independent duration and retained-tail doubling on every planned cascade; magnitude convergence only",
    }
    with run_lock(directory):
        snapshot = engine.snapshot()
        atomic_json(directory / "bench.json", config)
        atomic_json(directory / "manifest.json", manifest)
        try:
            for level in manifest["levels_dbfs"]:
                references = []
                for index, variant in enumerate(variants):
                    result = measure(
                        directory,
                        identity,
                        replace(variant, level_dbfs=level),
                        engine,
                        capture,
                        reference_channel=config.get("reference_channel"),
                        progress=counter(index),
                    )
                    record["results"].append(result)
                    references.append(load_trace(directory, result["attempt"]))
                    references[-1]["attempt"] = result["attempt"]
                frequencies = references[0]["frequencies"]
                valid = references[0]["mask"].copy()
                error = np.zeros(len(frequencies))
                for case in manifest["cases"]:
                    if case["status"] != "planned":
                        continue
                    traces = []
                    for index, variant in enumerate(variants):
                        if case["name"] == "identity":
                            data = reference = references[index]
                            magnitude = 20 * np.log10(
                                np.maximum(np.abs(data["response"]), 1e-300)
                            )
                        else:
                            result = measure(
                                directory,
                                case,
                                replace(variant, level_dbfs=level),
                                engine,
                                capture,
                                reference_channel=config.get("reference_channel"),
                                progress=counter(index),
                            )
                            record["results"].append(result)
                            data = load_trace(directory, result["attempt"])
                            # A longer-settling cascade has a longer tail and a finer
                            # grid; its identity is recovered again on that grid.
                            reference = (
                                references[index]
                                if np.array_equal(
                                    data["frequencies"],
                                    references[index]["frequencies"],
                                )
                                else recompute(
                                    directory,
                                    references[index]["attempt"],
                                    config,
                                    len(data["impulse"]),
                                )
                            )
                            data["mask"] &= reference["mask"]
                            magnitude = 20 * np.log10(
                                np.maximum(
                                    np.abs(data["response"] / reference["response"]),
                                    1e-300,
                                )
                            )
                        traces.append(
                            {
                                "frequencies": data["frequencies"],
                                "delta_exact_db": magnitude,
                                "mask": data["mask"],
                                "uncertainty_db": data["inversion_bias_db"]
                                + reference["inversion_bias_db"],
                            }
                        )
                    base, base_bias, base_mask = sample_trace(traces[0], frequencies)
                    for trace in traces[1:]:
                        longer, longer_bias, longer_mask = sample_trace(
                            trace, frequencies
                        )
                        valid &= base_mask & longer_mask
                        error = np.maximum(
                            error, np.abs(longer - base) + base_bias + longer_bias
                        )
                valid &= error < accuracy_db / 3
                logger.info(
                    "%g dBFS: %d/%d bins converged within %.3g dB",
                    level,
                    int(np.count_nonzero(valid)),
                    len(valid),
                    accuracy_db / 3,
                )
                name = f"qualification-{level:g}.npz"
                atomic_arrays(
                    directory / "analysis" / name,
                    frequencies=frequencies,
                    uncertainty_db=error,
                    mask=valid,
                )
                record["reference_files"][name] = file_hash(
                    directory / "analysis" / name
                )
            record["hash"] = digest(record)
            atomic_json(directory / "qualification.json", record)
            logger.info(
                "convergence stage complete: %s", directory / "qualification.json"
            )
            return record
        finally:
            restored, errors = restore_state(engine, snapshot)
            atomic_json(
                directory / "run.json",
                {"restored": restored, "restoration_errors": errors},
            )
            register(directory)


def complete(
    directory: Path,
    supporting: list[Path],
    *,
    clock_verified: bool = False,
    direct_loopback_waiver: str | None = None,
) -> dict:
    """Assemble measured stages; never license a live run by merely toggling a flag.

    `direct_loopback_waiver` is the hashed bench's own all-digital basis: when the DUT is
    the audio interface there is no separate interface to loop back. It is recorded in
    the completed qualification, never implied.
    """
    record = json.loads((directory / "qualification.json").read_text())
    if record.get("qualified"):
        raise ValueError(
            "qualification is already complete; record new stages in new directories"
        )
    if record.get("stage", "identity") != "identity":
        raise ValueError(
            "complete the active-identity qualification, not a supporting stage"
        )
    path = directory / "manifest.json"
    identity_case = (
        next(
            c["id"]
            for c in json.loads(path.read_text())["cases"]
            if c["name"] == "identity"
        )
        if path.is_file()
        else None
    )
    stages = {}
    covers = set()
    for source in supporting:
        stage = json.loads((source / "qualification.json").read_text())
        if stage["hash"] != digest({k: v for k, v in stage.items() if k != "hash"}):
            raise ValueError("supporting qualification hash mismatch")
        kind = stage.get("stage")
        if kind not in ("direct-loopback", "device-bypass", "convergence") or (
            kind != "convergence" and kind in stages
        ):
            raise ValueError(
                "provide one direct-loopback and device-bypass stage and convergence"
            )
        for key in ("bench_hash", "settings", "accuracy_db"):
            if stage[key] != record[key]:
                raise ValueError(f"supporting qualification is stale: {key}")
        if kind == "convergence":
            # Convergence may be split across records, each covering some cascades;
            # it must share the identity and levels, not the whole manifest.
            if stage.get("identity_case", identity_case) != identity_case:
                raise ValueError("supporting qualification is stale: identity case")
            if set(stage["reference_files"]) != set(record["reference_files"]):
                raise ValueError("supporting qualification lacks a required level")
            if "covers" in stage:
                covers |= set(stage["covers"])
            else:  # Recorded before coverage was: its own manifest's planned cascades.
                own = json.loads((source / "manifest.json").read_text())
                covers |= {
                    c["id"]
                    for c in own["cases"]
                    if c["status"] == "planned" and c["name"] != "identity"
                }
            label = f"convergence-{stage['hash'][:12]}"
        else:
            if stage["manifest_hash"] != record["manifest_hash"]:
                raise ValueError("supporting qualification is stale: manifest_hash")
            label = kind
        if kind != "direct-loopback" and stage["engine"] != record["engine"]:
            raise ValueError("supporting qualification engine identity differs")
        for name, expected in stage["reference_files"].items():
            if (
                Path(name).name != name
                or file_hash(source / "analysis" / name) != expected
            ):
                raise ValueError("supporting qualification evidence changed")
        stages[label] = (source, stage)
    kinds = {stage["stage"] for _, stage in stages.values()}
    required = {"direct-loopback", "device-bypass", "convergence"}
    if direct_loopback_waiver:
        required.discard("direct-loopback")
    if not required <= kinds:
        raise ValueError(
            "direct-loopback, device-bypass and convergence evidence are required"
            if "direct-loopback" in required
            else "device-bypass and convergence evidence are required"
        )
    if not clock_verified:
        raise ValueError(
            "record a common-clock basis or use an independent timing reference"
        )
    if record["hash"] != digest({k: v for k, v in record.items() if k != "hash"}):
        raise ValueError("identity qualification hash mismatch")
    if identity_case is None:
        raise ValueError("identity qualification manifest is missing")
    # Validate everything before publishing the combined qualification.
    combined = {}
    for name, expected in record["reference_files"].items():
        target = directory / "analysis" / name
        if Path(name).name != name or file_hash(target) != expected:
            raise ValueError("identity qualification evidence changed")
        with np.load(target, allow_pickle=False) as arrays:
            data = {key: arrays[key].copy() for key in arrays.files}
        converged = None
        for source, stage in stages.values():
            if name not in stage["reference_files"]:
                raise ValueError("supporting qualification lacks a required level")
            with np.load(source / "analysis" / name, allow_pickle=False) as arrays:
                if not np.array_equal(data["frequencies"], arrays["frequencies"]):
                    raise ValueError("supporting qualification frequency axes differ")
                data["mask"] &= arrays["mask"]
                if stage["stage"] == "convergence":
                    # One convergence budget: the worst cascade's, wherever it was.
                    converged = (
                        arrays["uncertainty_db"].copy()
                        if converged is None
                        else np.maximum(converged, arrays["uncertainty_db"])
                    )
                else:
                    data["uncertainty_db"] += arrays["uncertainty_db"]
        data["uncertainty_db"] += converged
        data["mask"] &= data["uncertainty_db"] < record["accuracy_db"] / 3
        if not np.any(data["mask"]):
            raise ValueError(
                "no common qualified bins at a required level; improve the bench/settings"
            )
        combined[name] = data
    with run_lock(directory):
        supporting_files = {}
        for kind, (source, stage) in stages.items():
            # Retain raw supporting evidence, including stimuli and transport logs.
            registry = json.loads((source / "files.json").read_text())
            for relative, expected in registry.items():
                if relative.split("/")[0] not in (
                    "captures",
                    "stimuli",
                    "transport",
                    "analysis",
                ):
                    continue
                if (
                    not evidence_name(relative)
                    or file_hash(source / relative) != expected
                ):
                    raise ValueError("invalid supporting evidence registry")
                destination = directory / relative
                if Path(relative).name.startswith("qualification-"):
                    destination = (
                        directory / "analysis" / f"{kind}-{Path(relative).name}"
                    )
                if destination.exists() and file_hash(destination) != expected:
                    raise ValueError(
                        "supporting evidence collides with existing evidence"
                    )
                atomic_bytes(destination, (source / relative).read_bytes())
                supporting_files[destination.relative_to(directory).as_posix()] = (
                    expected
                )
            stage_path = directory / "analysis" / f"stage-{kind}.json"
            atomic_json(stage_path, stage)
            supporting_files[stage_path.relative_to(directory).as_posix()] = file_hash(
                stage_path
            )
        for name, data in combined.items():
            atomic_arrays(directory / "analysis" / name, **data)
        record["reference_files"] = {
            name: file_hash(directory / "analysis" / name) for name in combined
        }
        record["supporting_stages"] = {
            kind: stage["hash"] for kind, (_, stage) in stages.items()
        }
        record["supporting_files"] = supporting_files
        # What a run may measure under this qualification (see `transactions.run`).
        record["identity_case"] = identity_case
        record["convergence_covers"] = sorted(covers)
        record["qualified"] = True
        record["scope"] = (
            "active identity, direct interface loopback, selected PEQ-bank bypass, duration/tail convergence; qualified magnitude bins only"
        )
        if "direct-loopback" not in stages:
            record["waived_stages"] = {"direct-loopback": direct_loopback_waiver}
            record["scope"] = (
                "active identity, selected PEQ-bank bypass, duration/tail convergence;"
                " direct interface loopback waived (all-digital bench: the DUT is the"
                " audio interface); qualified magnitude bins only"
            )
        record["hash"] = digest({k: v for k, v in record.items() if k != "hash"})
        atomic_json(directory / "qualification.json", record)
        register(directory)
    return record
