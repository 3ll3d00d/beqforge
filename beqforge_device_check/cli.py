"""Separate F2 console workflow. Offline commands never open an audio stream."""

import argparse
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from beqforge_device_check.analyse import analyse, compare
from beqforge_device_check.catalogue import import_snapshot
from beqforge_device_check.evidence import atomic_bytes, atomic_json, bundle
from beqforge_device_check.manifest import digest, generate, validate
from beqforge_device_check.measurement import SweepSettings
from beqforge_device_check.profiles import PROFILES, DeviceProfile
from beqforge_device_check.transactions import Simulation, qualify, run


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def helper_path(value: str) -> Path:
    if value != "bundled":
        return Path(value)
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    path = root / "helpers" / ("minidsp.exe" if sys.platform == "win32" else "minidsp")
    if not path.is_file():
        raise ValueError(
            "this build has no bundled miniDSP helper; supply an executable"
        )
    return path


def provenance() -> dict:
    from beqforge.record import revision

    result = {"tool": "beqforge-device-check", "beqforge_revision": revision()}
    # The frozen entry script lives at the bundle root; package data lives alongside
    # __init__, so provenance must resolve the package rather than __main__.
    import beqforge_device_check

    root = Path(beqforge_device_check.__file__).parent
    stamp = root / "BUILD_REVISION"
    result["implementation"] = (
        stamp.read_text().strip()
        if stamp.exists()
        else digest({p.name: p.read_text() for p in sorted(root.glob("*.py"))})
    )
    result["libraries"] = {}
    for name in ("numpy", "scipy", "pyfar", "sounddevice", "websocket-client"):
        try:
            result["libraries"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result["libraries"][name] = "unavailable"
    return result


def validate_config(config: dict) -> DeviceProfile:
    if config.get("schema_version") != 1:
        raise ValueError("unsupported bench schema")
    profile = DeviceProfile.from_dict(config["profile"])
    profile.route(config["route"], config["channel"], config["rate"])
    mode = config["engine_mode"]
    if mode not in ("simulation", "camilladsp-file", "camilladsp-live", "minidsp"):
        raise ValueError("unsupported engine mode")
    expected = {
        "simulation": "simulation",
        "camilladsp-file": "camilladsp",
        "camilladsp-live": "camilladsp",
        "minidsp": "minidsp",
    }
    if expected[mode] != profile.engine:
        raise ValueError("profile and engine mode disagree")
    if mode in ("minidsp", "camilladsp-live"):
        if not config.get("firmware_or_build") or not config.get("physical_route"):
            raise ValueError(
                "live bench needs firmware/build and physical-route description"
            )
        if not config.get("electrical_bench_acknowledged"):
            raise ValueError(
                "setup must record disconnected electrical-bench acknowledgement"
            )
        if not config.get("audio"):
            raise ValueError("explicit audio routes are required")
    return profile


def factory(config: dict, directory: Path):
    from beqforge_device_check.engines import CamillaFile, CamillaLive, Helper, Minidsp

    profile = validate_config(config)
    mode, rate = config["engine_mode"], config["rate"]
    if mode == "simulation":
        engine = Simulation(rate, config.get("storage_model", "float64"))
        return engine, engine
    options = config["engine"]
    if mode == "camilladsp-file":
        engine = CamillaFile(
            Helper(Path(options["executable"]), options["version"]),
            rate,
            directory / "engine-work",
        )
        return engine, engine
    if mode == "camilladsp-live":
        engine = CamillaLive(
            options["endpoint"], options["version"], options["template"], rate
        )
    else:
        engine = Minidsp(
            Helper(helper_path(options["executable"]), options["version"]),
            profile,
            serial=options["serial"],
            restore_commands=options["restore_commands"],
        )
    from beqforge_device_check.audio import StreamCapture, devices

    capture = StreamCapture(config["audio"], devices())
    return engine, capture


def setup(args) -> dict:
    profile = PROFILES[args.profile]
    mode = (
        args.engine_mode
        or {
            "minidsp": "minidsp",
            "camilladsp": "camilladsp-file",
            "simulation": "simulation",
        }[profile.engine]
    )
    offline = mode in ("simulation", "camilladsp-file")
    config = {
        "schema_version": 1,
        "profile": profile.as_dict(),
        "rate": args.rate,
        "route": profile.routes[0].name,
        "channel": 0,
        "engine_mode": mode,
        "electrical_bench_acknowledged": False,
    }
    if mode == "simulation":
        validate_config(config)
        return config
    executable = args.executable or shutil.which(
        "minidsp" if mode == "minidsp" else "camilladsp"
    )
    if mode == "minidsp" and not args.executable and getattr(sys, "frozen", False):
        executable = "bundled"
    if not executable:
        raise ValueError("supply an explicit installed engine/helper executable")
    config["engine"] = {
        "executable": executable
        if executable == "bundled"
        else str(Path(executable).resolve()),
        "version": "0.1.9" if mode == "minidsp" else "4.1.3",
    }
    if offline:
        validate_config(config)
        return config
    if not sys.stdin.isatty():
        raise ValueError(
            "live setup is guided/interactive; supply a prepared bench JSON when scripting"
        )
    print("Wire measurement output → DUT input → DUT output → interface line input.")
    print("Disconnect loudspeakers and amplifiers. USB control is not an audio return.")
    config["firmware_or_build"] = input(
        "Device firmware / verified engine build: "
    ).strip()
    config["physical_route"] = input(
        "Input/output ports, conversion/transport rates, gains and disabled processing: "
    ).strip()
    config["unit_id"] = input(
        "Unit identifier (may be pseudonymous in exports): "
    ).strip()
    if mode == "minidsp":
        config["engine"]["serial"] = input(
            "miniDSP serial (explicit selection): "
        ).strip()
        restore = Path(
            input("Complete miniDSP restoration argument-arrays JSON file: ").strip()
        )
        config["engine"]["restore_commands"] = json.loads(restore.read_text())
    else:
        config["engine"]["endpoint"] = input("CamillaDSP websocket URL: ").strip()
        config["engine"]["template"] = read(
            Path(input("Dedicated mono bench config JSON: ").strip())
        )
    config["audio"] = {}
    for side in ("input", "output"):
        config["audio"][side] = {
            "name": input(f"Exact audio {side} device name: ").strip(),
            "host_api": input(f"{side} host API: ").strip(),
            "channels": int(input(f"{side} channel count: ")),
            "channel": int(input(f"{side} channel index (zero-based): ")),
        }
    config["audio"].update({"latency": "high", "blocksize": 1024})
    config["electrical_bench_acknowledged"] = (
        input("Type DISCONNECTED to acknowledge the electrical bench: ").strip()
        == "DISCONNECTED"
    )
    validate_config(config)
    return config


def self_test(directory: Path) -> dict:
    """Run real native imports, known-transfer recovery, transactions and offline replay."""
    from scipy.signal import sosfilt

    from beqforge_device_check.coefficients import response

    # These checks exercise adapter failure behaviour inside the actual frozen process.
    from beqforge_device_check.engines import Helper, Minidsp

    bundled_helper = None
    if getattr(sys, "frozen", False):
        binary = helper_path("bundled")
        Helper(binary, "0.1.9")
        from beqforge_device_check.evidence import file_hash

        bundled_helper = read(binary.parent / "helper.json")
        if file_hash(binary) != bundled_helper["binary_sha256"]:
            raise ValueError("bundled helper hash changed")

    mock = directory / "mock-helper"
    atomic_bytes(mock, b"self-test mock, never executed")
    commands = []

    def runner(args, **kwargs):
        if kwargs.get("timeout") != 10 or not kwargs.get("check"):
            raise ValueError("helper subprocess bounds lost")
        commands.append(args)
        stdout = (
            "minidsp 0.1.9"
            if args[-1] == "--version"
            else (
                "0: Found 2x4HD with serial 123456 at usb:0"
                if args[-1] == "probe"
                else "{}"
            )
        )
        return subprocess.CompletedProcess(args, 0, stdout, "")

    adapter = Minidsp(
        Helper(mock, "0.1.9", runner=runner),
        PROFILES["minidsp-2x4hd"],
        serial="123456",
        restore_commands=[["config", "0"]],
    )
    payload = adapter.load(generate(PROFILES["minidsp-2x4hd"])["cases"][1])
    if payload["commands"][0][-2:] != ["all", "clear"]:
        raise ValueError("unused miniDSP slots were not cleared")
    calls = []

    def timeout_runner(args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    try:
        Helper(mock, "0.1.9", runner=timeout_runner)
    except subprocess.TimeoutExpired:
        if len(calls) != 1:
            raise ValueError("timed-out helper was retried") from None
    else:
        raise ValueError("helper timeout was swallowed")
    mock.unlink()

    profile = PROFILES["simulation-float64"]
    manifest = generate(profile, rate=48000)
    # Keep the executable smoke test short while retaining a sensitive independent transfer.
    config = {
        "schema_version": 1,
        "profile": profile.as_dict(),
        "rate": 48000,
        "route": "filter",
        "channel": 0,
        "engine_mode": "simulation",
    }
    engine = Simulation(48000)
    settings = SweepSettings(
        rate=48000, low_hz=5, duration_s=2, tail_s=15, preroll_s=0.5
    )
    from beqforge_device_check.measurement import recover, sweep

    x, metadata = sweep(settings)
    errors = {}
    for case in manifest["cases"]:
        sos = np.asarray(case["exact_sos"]).reshape(-1, 6)
        captured = sosfilt(sos, x.astype(float)) if len(sos) else x.astype(float)
        result = recover(x, captured, metadata)
        if not result["valid"] or not np.any(result["mask"]):
            raise ValueError("self-test recovery failed")
        expected = response(sos, result["frequencies"], 48000)
        mask = result["mask"]
        error = float(
            np.max(
                np.abs(20 * np.log10(abs(result["response"][mask] / expected[mask])))
            )
        )
        if error > 0.002:
            raise ValueError(f"self-test known-transfer error {error:g} dB")
        errors[case["name"]] = error
    manifest["order"] = [manifest["cases"][1]["id"]] * 3
    manifest["hash"] = digest({k: v for k, v in manifest.items() if k != "hash"})
    short = SweepSettings(rate=48000, duration_s=1, tail_s=2, preroll_s=0.25)
    qualify(
        config,
        manifest,
        directory / "qualification",
        engine,
        engine,
        short,
        accuracy_db=0.1,
    )
    completed = run(
        config, manifest, directory / "qualification", directory / "run", engine, engine
    )
    report = analyse(directory / "run", directory / "run")
    exported = bundle(directory / "run", directory / "results.zip")
    import sounddevice as sd

    from beqforge_device_check.audio import devices

    native_portaudio = list(sd.get_portaudio_version())

    try:
        inventory = devices(timeout_s=10)
        audio = {
            "status": "initialised",
            "devices": len(inventory["devices"]),
            "portaudio": inventory["portaudio"],
        }
    except subprocess.TimeoutExpired:
        audio = {
            "status": "discovery-timeout",
            "limitation": "live audio remains unavailable on this host",
        }
    result = {
        "passed": completed["complete"] and report["complete"],
        "known_transfer_error_db": errors,
        "adapter_checks": {"unused_slots_cleared": True, "timeout_without_retry": True},
        "bundled_helper": bundled_helper,
        "portaudio": audio,
        "native_portaudio": native_portaudio,
        "bundle_bytes": exported["bytes"],
        "provenance": provenance(),
    }
    atomic_json(directory / "self-test.json", result)
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("devices", "_audio-devices", "profiles"):
        command = sub.add_parser(name)
        command.add_argument("--out", type=Path)
    command = sub.add_parser("setup")
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--profile", choices=PROFILES, default="minidsp-2x4hd")
    command.add_argument("--rate", type=int, default=96000)
    command.add_argument(
        "--engine-mode",
        choices=("simulation", "minidsp", "camilladsp-file", "camilladsp-live"),
    )
    command.add_argument("--executable")
    command = sub.add_parser("self-test")
    command.add_argument("--out", type=Path, required=True)
    for name in ("plan", "qualify", "run", "catalogue-plan", "catalogue-entry"):
        command = sub.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        if name == "plan":
            command.add_argument(
                "--suite", choices=("pilot", "matrix"), default="pilot"
            )
        elif name == "qualify":
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--accuracy-db", type=float, required=True)
            command.add_argument("--duration", type=float, default=30)
            command.add_argument("--tail", type=float, default=15)
            command.add_argument("--low-hz", type=float, default=2)
            command.add_argument("--high-hz", type=float, default=200)
        elif name == "run":
            command.add_argument("--manifest", type=Path, required=True)
            command.add_argument("--qualification", type=Path, required=True)
            command.add_argument("--resume", action="store_true")
        else:
            command.add_argument("--catalogue", type=Path, required=True)
            command.add_argument("--revision", required=True)
            command.add_argument("--attribution", required=True)
            command.add_argument("--complete-snapshot", action="store_true")
            command.add_argument("--no-deduplicate", action="store_true")
            if name == "catalogue-entry":
                command.add_argument("--entry", required=True)
                command.add_argument("--qualification", type=Path)
    for name in ("analyse", "catalogue-analyse"):
        command = sub.add_parser(name)
        command.add_argument("directories", type=Path, nargs="+")
        command.add_argument("--out", type=Path, required=True)
    command = sub.add_parser("bundle")
    command.add_argument("directory", type=Path)
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--summary-only", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (
        ValueError,
        TypeError,
        RuntimeError,
        OSError,
        KeyError,
        subprocess.SubprocessError,
        ImportError,
    ) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "Stopped; partial evidence and restoration status are saved in the run directory.",
            file=sys.stderr,
        )
        return 130


def dispatch(args) -> dict | list:
    if args.command in ("devices", "_audio-devices"):
        from beqforge_device_check.audio import devices, native_devices

        result = native_devices() if args.command == "_audio-devices" else devices()
        if args.out:
            atomic_json(args.out, result)
        return result
    if args.command == "profiles":
        return [profile.as_dict() for profile in PROFILES.values()]
    if args.command == "setup":
        config = setup(args)
        atomic_json(args.out, config)
        return config
    if args.command == "self-test":
        return self_test(args.out)
    if args.command == "bundle":
        return bundle(args.directory, args.out, summary_only=args.summary_only)
    if args.command in ("analyse", "catalogue-analyse"):
        if len(args.directories) == 1:
            report = analyse(args.directories[0], args.out)
            return {k: v for k, v in report.items() if k != "results"}
        reports = [analyse(directory, directory) for directory in args.directories]
        result = compare(reports)
        atomic_json(args.out / "comparison.json", result)
        return {
            "matched_cases": len(result["matched_cases"]),
            "unmatched_counts": result["unmatched_counts"],
        }
    config = read(args.config)
    profile = validate_config(config)
    if args.command == "plan":
        manifest = generate(
            profile,
            rate=config["rate"],
            route=config["route"],
            channel=config["channel"],
            suite=args.suite,
        )
        manifest["provenance"] = provenance()
        manifest["hash"] = digest({k: v for k, v in manifest.items() if k != "hash"})
        atomic_json(args.out, manifest)
        return {
            "cases": len(manifest["cases"]),
            "supported": sum(c["status"] == "planned" for c in manifest["cases"]),
            "manifest_hash": manifest["hash"],
        }
    if args.command in ("catalogue-plan", "catalogue-entry"):
        manifest, inventory = import_snapshot(
            args.catalogue,
            profile,
            rate=config["rate"],
            route=config["route"],
            channel=config["channel"],
            complete=args.complete_snapshot,
            attribution=args.attribution,
            revision=args.revision,
            deduplicate=not args.no_deduplicate,
        )
        if args.command == "catalogue-entry":
            selected = [
                item for item in inventory["entries"] if item["id"] == args.entry
            ]
            if len(selected) != 1 or not selected[0].get("case"):
                raise ValueError(
                    "entry is missing/ambiguous/unsupported; inspect the inventory"
                )
            case_id = selected[0]["case"]
            manifest["cases"] = [
                case
                for case in manifest["cases"]
                if case["name"] == "identity" or case["id"] == case_id
            ]
            manifest["order"] = [case_id] * manifest["repeats"]
            manifest["source"]["subset"] = [args.entry]
            manifest["hash"] = digest(
                {k: v for k, v in manifest.items() if k != "hash"}
            )
        destination = (
            args.out if args.command == "catalogue-plan" else args.out / "cases.json"
        )
        atomic_json(destination, manifest)
        atomic_json(destination.with_suffix(".inventory.json"), inventory)
        atomic_bytes(
            destination.with_suffix(".snapshot.json"), args.catalogue.read_bytes()
        )
        if args.command == "catalogue-entry" and args.qualification:
            engine, capture = factory(config, args.out)
            atomic_json(args.out / "inventory.json", inventory)
            atomic_bytes(args.out / "source-snapshot.json", args.catalogue.read_bytes())
            return run(config, manifest, args.qualification, args.out, engine, capture)
        return {
            "manifest": str(destination),
            "entries": len(inventory["entries"]),
            "unique_cases": inventory["unique_cases"],
            "next": "qualify this frozen manifest, then run with its matching qualification",
        }
    manifest = read(args.manifest)
    validate(manifest)
    if DeviceProfile.from_dict(manifest["profile"]) != profile:
        raise ValueError("bench and manifest profiles disagree")
    engine, capture = factory(config, args.out)
    if args.command == "qualify":
        result = qualify(
            config,
            manifest,
            args.out,
            engine,
            capture,
            SweepSettings(
                rate=config["rate"],
                duration_s=args.duration,
                tail_s=args.tail,
                low_hz=args.low_hz,
                high_hz=args.high_hz,
            ),
            accuracy_db=args.accuracy_db,
        )
        return {k: v for k, v in result.items() if k != "results"}
    for suffix, name in (
        (".inventory.json", "inventory.json"),
        (".snapshot.json", "source-snapshot.json"),
    ):
        source = args.manifest.with_suffix(suffix)
        if source.exists():
            atomic_bytes(args.out / name, source.read_bytes())
    summary = run(
        config,
        manifest,
        args.qualification,
        args.out,
        engine,
        capture,
        resume=args.resume,
    )
    return {k: v for k, v in summary.items() if k not in ("completed", "snapshot")}


if __name__ == "__main__":
    raise SystemExit(main())
