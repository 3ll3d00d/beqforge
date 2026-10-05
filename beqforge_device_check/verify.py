"""One command: reuse every stage already proven for this bench, measure only what is missing.

Identity, device bypass and direct loopback never involve the cascades under test, so they
are keyed on what they do depend on (bench, engine, sweep settings, accuracy requirement,
identity case and levels) and kept in a store beside the bench, reusable by any manifest.
Convergence is kept per cascade: a new manifest converges only the cascades no stored record
covers. Every stored stage is a complete, hashed stage directory, assembled and checked by
`qualification.complete` exactly as if the stages had been run by hand.
"""

import json
import logging
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from beqforge_device_check.analyse import analyse
from beqforge_device_check.manifest import digest, validate
from beqforge_device_check.measurement import SweepSettings
from beqforge_device_check.qualification import BypassReference, complete, convergence
from beqforge_device_check.report import MARKS, grouped, label
from beqforge_device_check.transactions import bench_hash, qualify, run

logger = logging.getLogger(__name__)

# Manifest fields a derived (identity-plus-cascades) manifest keeps from the measured one.
CARRIED = ("schema_version", "profile", "levels_dbfs", "identity_repeats", "protocol")


def identity_of(manifest: dict) -> dict:
    return next(case for case in manifest["cases"] if case["name"] == "identity")


def planned(manifest: dict) -> list[dict]:
    return [
        case
        for case in manifest["cases"]
        if case["status"] == "planned" and case["name"] != "identity"
    ]


def derived(manifest: dict, cases: list[dict]) -> dict:
    """The identity plus `cases`, at the measured manifest's levels and repeats."""
    result = {key: manifest[key] for key in CARRIED if key in manifest}
    result.update(
        {"cases": [identity_of(manifest), *cases], "order": [], "derived": "verify"}
    )
    result["hash"] = digest(result)
    return result


def stored(store: Path, prefix: str) -> list[Path]:
    """Completed stage directories under `prefix`; an interrupted attempt has no record."""
    found = []
    for path in sorted(store.glob(f"{prefix}*")):
        record = path / "qualification.json"
        if not record.is_file():
            continue
        data = json.loads(record.read_text())
        if data.get("hash") == digest({k: v for k, v in data.items() if k != "hash"}):
            found.append(path)
    return found


def fresh(store: Path, prefix: str) -> Path:
    attempt = 1
    while (store / f"{prefix}{attempt}").exists():
        attempt += 1
    return store / f"{prefix}{attempt}"


def verify(
    config: dict,
    manifest: dict,
    store: Path,
    out: Path,
    engine,
    capture,
    settings: SweepSettings,
    *,
    accuracy_db: float,
    direct_path: str | None = None,
) -> dict:
    validate(manifest)
    if out.exists():
        raise ValueError(f"{out} already exists; verification results never overwrite")
    store.mkdir(parents=True, exist_ok=True)
    base = derived(manifest, [])
    key = digest(
        [
            bench_hash(config),
            engine.identify(),
            asdict(settings),
            accuracy_db,
            base["hash"],
        ]
    )[:16]
    reused, measured = [], []

    def stage(kind: str, operation) -> Path:
        prefix = f"{kind}-{key}-"
        found = stored(store, prefix)
        if found:
            logger.info("%s: reusing %s", kind, found[0])
            reused.append(kind)
            return found[0]
        directory = fresh(store, prefix)
        logger.info("%s: not yet proven for this bench and settings; measuring", kind)
        operation(directory)
        measured.append(kind)
        return directory

    identity = stage(
        "identity",
        lambda d: qualify(
            config, base, d, engine, capture, settings, accuracy_db=accuracy_db
        ),
    )
    bypassed = BypassReference(engine) if hasattr(engine, "bypass") else engine
    bypass = stage(
        "device-bypass",
        lambda d: qualify(
            config,
            base,
            d,
            bypassed,
            capture,
            settings,
            accuracy_db=accuracy_db,
            stage="device-bypass",
            path_description="selected PEQ bank bypassed on the bench route"
            if bypassed is not engine
            else "numerical control: no PEQ bank to bypass",
        ),
    )
    supporting = [bypass]
    waiver = config.get("all_digital_basis") if config.get("all_digital") else None
    if not waiver:
        found = stored(store, f"direct-loopback-{key}-")
        if not found and direct_path is None:
            raise ValueError(
                "this bench needs a direct-loopback stage: wire the interface output"
                " straight to its input, rerun with --direct-loopback 'how it is wired',"
                " then restore the DUT wiring and run verify again"
            )
        if not found:
            from beqforge_device_check.qualification import DirectReference

            directory = fresh(store, f"direct-loopback-{key}-")
            qualify(
                config,
                base,
                directory,
                DirectReference(),
                capture,
                settings,
                accuracy_db=accuracy_db,
                stage="direct-loopback",
                path_description=direct_path,
            )
            raise ValueError(
                f"direct loopback recorded in {directory}; restore the DUT wiring and"
                " run verify again"
            )
        reused.append("direct-loopback")
        supporting.append(found[0])
    wanted = {case["id"]: case for case in planned(manifest)}
    records = []
    for path in stored(store, f"convergence-{key}-"):
        covered = set(json.loads((path / "qualification.json").read_text())["covers"])
        if covered & set(wanted):
            records.append(path)
            wanted = {k: v for k, v in wanted.items() if k not in covered}
    if records:
        reused.append(f"convergence ({len(records)} stored record(s))")
    if wanted:
        directory = fresh(store, f"convergence-{key}-")
        logger.info(
            "convergence: %d cascade(s) not yet proven for this bench; measuring",
            len(wanted),
        )
        convergence(
            config,
            derived(manifest, list(wanted.values())),
            directory,
            engine,
            capture,
            settings,
            accuracy_db=accuracy_db,
        )
        measured.append(f"convergence ({len(wanted)} cascade(s))")
        records.append(directory)
    supporting += records
    qualification = out / "qualification"
    shutil.copytree(identity, qualification)
    clock_verified = config.get("reference_channel") is not None or bool(
        config.get("common_clock") and config.get("clock_basis")
    )
    complete(
        qualification,
        supporting,
        clock_verified=clock_verified,
        direct_loopback_waiver=waiver,
    )
    logger.info("Qualification assembled in %s", qualification)
    summary = run(config, manifest, qualification, out / "run", engine, capture)
    report = analyse(out / "run", out / "report")
    # One line per filter and level, with the report's two separate verdicts.
    results = []
    for row in grouped(report["results"]):
        rep = row["representation"]
        result = {
            "filter": label(row),
            "level_dbfs": row["level_dbfs"],
            "loads": len(row["loads"]),
            "device": MARKS[row["device"]],
            "device_worst_db": row["device_worst_db"],
            "coefficients": "OK" if rep["outcome"] == "ok" else "DEGRADED",
            "coefficients_worst_db": rep["worst_db"],
            "coefficients_worst_hz": rep["worst_hz"],
        }
        results.append(result)
        logger.info(
            "%s @ %.1f dBFS: device %s%s; coefficients %s (%.3f dB at %.1f Hz)",
            result["filter"],
            result["level_dbfs"],
            result["device"],
            ""
            if result["device_worst_db"] is None
            else f" (worst {result['device_worst_db']:.4f} dB)",
            result["coefficients"],
            rep["worst_db"],
            rep["worst_hz"],
        )
    logger.info("Report: %s", out / "report" / "report.html")
    return {
        "out": str(out),
        "report": str(out / "report" / "report.html"),
        "reused": reused,
        "measured": measured,
        "complete": summary.get("complete", False),
        "restored": summary.get("restored"),
        "results": results,
    }


def default_out(config_path: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return config_path.resolve().parent / "results" / stamp
