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


def cascade_convergence(
    directory: Path, stage: dict, config: dict, identity_case: str
) -> dict:
    """Each cascade's own duration/tail convergence, per level, from a stage's traces.

    A cascade that has not settled within the sweep is that cascade's problem, not the
    bench's: its disagreement between sweep variants widens its own budget only. The
    identity's disagreement is the bench's, and is the only part every cascade carries.

    Returns {reference file name: arrays}: `uncertainty_db`/`mask` the identity's
    convergence (mask thresholded at a third of the requirement), and one row of
    `case_uncertainty_db`/`case_mask` per cascade in `cases` (mask: bins measured
    validly in every variant, not thresholded; judging applies the requirement).
    Works on any directory holding the stage's attempts, including a run's copy.
    """
    attempts: dict[float, dict[str, list[str]]] = {}
    for result in stage["results"]:
        attempts.setdefault(result["level_dbfs"], {}).setdefault(
            result["case"], []
        ).append(result["attempt"])
    recomputed: dict[tuple[str, int], dict] = {}

    def reference_on(attempt: str, trace: dict, grid: dict) -> dict:
        # A long-settling cascade has a longer tail and a finer grid; its identity is
        # recovered again on that grid.
        if np.array_equal(grid["frequencies"], trace["frequencies"]):
            return trace
        key = (attempt, len(grid["impulse"]))
        if key not in recomputed:
            recomputed[key] = recompute(directory, attempt, config, key[1])
        return recomputed[key]

    budgets = {}
    for level, cases in attempts.items():
        identities = cases[identity_case]
        references = [load_trace(directory, attempt) for attempt in identities]
        frequencies = references[0]["frequencies"]

        def disagreement(
            traces: list[dict], references=references, frequencies=frequencies
        ) -> tuple[np.ndarray, np.ndarray]:
            valid = references[0]["mask"].copy()
            error = np.zeros(len(frequencies))
            base, base_bias, base_mask = sample_trace(traces[0], frequencies)
            for trace in traces[1:]:
                longer, longer_bias, longer_mask = sample_trace(trace, frequencies)
                valid &= base_mask & longer_mask
                error = np.maximum(
                    error, np.abs(longer - base) + base_bias + longer_bias
                )
            return error, valid

        def magnitude(data: dict, reference: dict | None) -> dict:
            response = data["response"]
            bias = 2 * data["inversion_bias_db"]
            mask = data["mask"]
            if reference is not None:
                response = response / reference["response"]
                bias = data["inversion_bias_db"] + reference["inversion_bias_db"]
                mask = mask & reference["mask"]
            return {
                "frequencies": data["frequencies"],
                "delta_exact_db": 20 * np.log10(np.maximum(np.abs(response), 1e-300)),
                "mask": mask,
                "uncertainty_db": bias,
            }

        error, valid = disagreement([magnitude(r, None) for r in references])
        ids, rows, masks = [], [], []
        for case, variants in cases.items():
            if case == identity_case:
                continue
            traces = []
            for index, attempt in enumerate(variants):
                data = load_trace(directory, attempt)
                traces.append(
                    magnitude(
                        data,
                        reference_on(identities[index], references[index], data),
                    )
                )
            case_error, case_valid = disagreement(traces)
            ids.append(case)
            rows.append(case_error)
            masks.append(case_valid)
        budgets[f"qualification-{level:g}.npz"] = {
            "frequencies": frequencies,
            "uncertainty_db": error,
            "mask": valid & (error < stage["accuracy_db"] / 3),
            "cases": np.asarray(ids, dtype=str),
            "case_uncertainty_db": np.asarray(rows, dtype=float).reshape(
                len(ids), len(frequencies)
            ),
            "case_mask": np.asarray(masks, dtype=bool).reshape(
                len(ids), len(frequencies)
            ),
        }
    return budgets


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
        "scope": "independent duration and retained-tail doubling on every planned cascade; magnitude convergence only, budgeted per cascade",
    }
    with run_lock(directory):
        snapshot = engine.snapshot()
        atomic_json(directory / "bench.json", config)
        atomic_json(directory / "manifest.json", manifest)
        try:
            for level in manifest["levels_dbfs"]:
                for case in [identity, *filtered]:
                    for index, variant in enumerate(variants):
                        record["results"].append(
                            measure(
                                directory,
                                case,
                                replace(variant, level_dbfs=level),
                                engine,
                                capture,
                                reference_channel=config.get("reference_channel"),
                                progress=counter(index),
                            )
                        )
            names_by_id = {case["id"]: case["name"] for case in filtered}
            for name, budget in cascade_convergence(
                directory, record, config, identity["id"]
            ).items():
                limit = accuracy_db / 3
                unsettled = [
                    names_by_id[case]
                    for case, error, valid in zip(
                        budget["cases"],
                        budget["case_uncertainty_db"],
                        budget["case_mask"],
                        strict=True,
                    )
                    if np.any(valid & (error >= limit))
                ]
                logger.info(
                    "%s: identity converged on %d/%d bins; %d/%d cascade(s) converged"
                    " within %.3g dB on every bin%s",
                    name,
                    int(np.count_nonzero(budget["mask"])),
                    len(budget["mask"]),
                    len(budget["cases"]) - len(unsettled),
                    len(budget["cases"]),
                    limit,
                    f"; not settled: {', '.join(unsettled)}" if unsettled else "",
                )
                atomic_arrays(directory / "analysis" / name, **budget)
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
        per_case: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for source, stage in stages.values():
            if name not in stage["reference_files"]:
                raise ValueError("supporting qualification lacks a required level")
            with np.load(source / "analysis" / name, allow_pickle=False) as stored:
                arrays = {key: stored[key].copy() for key in stored.files}
            if not np.array_equal(data["frequencies"], arrays["frequencies"]):
                raise ValueError("supporting qualification frequency axes differ")
            if stage["stage"] != "convergence":
                data["mask"] &= arrays["mask"]
                data["uncertainty_db"] += arrays["uncertainty_db"]
                continue
            if "cases" not in arrays:
                # Recorded before convergence was budgeted per cascade: derive it again
                # from the stage's own hashed traces rather than pool its worst case.
                bench = json.loads((source / "bench.json").read_text())
                arrays = cascade_convergence(source, stage, bench, identity_case)[name]
            # The identity's own convergence is the bench's; every cascade carries it.
            data["mask"] &= arrays["mask"]
            converged = (
                arrays["uncertainty_db"]
                if converged is None
                else np.maximum(converged, arrays["uncertainty_db"])
            )
            for case, error, valid in zip(
                arrays["cases"].tolist(),
                arrays["case_uncertainty_db"],
                arrays["case_mask"],
                strict=True,
            ):
                if case in per_case:
                    error = np.maximum(per_case[case][0], error)
                    valid = per_case[case][1] & valid
                per_case[case] = (error, valid)
        data["uncertainty_db"] += converged
        data["mask"] &= data["uncertainty_db"] < record["accuracy_db"] / 3
        # A cascade that has not settled widens only its own budget (see `analyse`).
        cases = sorted(per_case)
        data["cases"] = np.asarray(cases, dtype=str)
        data["case_uncertainty_db"] = np.asarray(
            [per_case[case][0] for case in cases], dtype=float
        ).reshape(len(cases), len(data["frequencies"]))
        data["case_mask"] = np.asarray(
            [per_case[case][1] for case in cases], dtype=bool
        ).reshape(len(cases), len(data["frequencies"]))
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
