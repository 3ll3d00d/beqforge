"""Bounded external engines; command arguments never pass through a shell."""

import copy
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from beqforge_device_check.coefficients import rounded, stable
from beqforge_device_check.evidence import file_hash
from beqforge_device_check.profiles import DeviceProfile


class Helper:
    def __init__(
        self,
        executable: Path,
        expected_version: str,
        *,
        timeout_s: float = 10,
        runner=subprocess.run,
    ):
        self.executable = executable.resolve(strict=True)
        self.timeout_s = timeout_s
        self.runner = runner
        self.version = self.command("--version").strip()
        if expected_version not in self.version:
            raise ValueError(
                f"helper version differs: wanted {expected_version}, got {self.version}"
            )
        self.hash = file_hash(self.executable)

    def command(self, *arguments: str, timeout_s: float | None = None) -> str:
        result = self.runner(
            [str(self.executable), *arguments],
            capture_output=True,
            text=True,
            timeout=timeout_s or self.timeout_s,
            check=True,
        )
        return result.stdout


class Minidsp:
    live = True

    def __init__(
        self,
        helper: Helper,
        profile: DeviceProfile,
        *,
        serial: str,
        restore_commands: list[list[str]],
    ):
        if profile.engine != "minidsp" or not serial or not restore_commands:
            raise ValueError(
                "miniDSP needs an explicit serial and complete restoration commands"
            )
        self.helper, self.profile, self.serial = helper, profile, serial
        self.restore_commands = restore_commands
        for command in restore_commands:
            if not command or command[0] not in (
                "input",
                "output",
                "source",
                "gain",
                "config",
                "dirac",
                "mute",
            ):
                raise ValueError(
                    "restore commands must be explicit miniDSP setting argument arrays"
                )
        probe = helper.command("probe")
        matches = re.findall(
            r"(?m)^\s*(\d+):.*?serial\s+" + re.escape(serial) + r"(?:\s|$)", probe
        )
        if len(matches) != 1:
            raise ValueError("selected miniDSP serial is missing or ambiguous")
        self.index = matches[0]
        self.probe = probe

    def command(self, *arguments: str) -> str:
        probe = self.helper.command("probe")
        matches = re.findall(
            r"(?m)^\s*(\d+):.*?serial\s+" + re.escape(self.serial) + r"(?:\s|$)", probe
        )
        if matches != [self.index]:
            raise ValueError(
                "selected miniDSP changed/disconnected; stop rather than use discovery order"
            )
        return self.helper.command("-d", self.index, *arguments)

    def identify(self) -> dict:
        return {
            "engine": "minidsp",
            "profile": self.profile.id,
            "serial": self.serial,
            "helper_version": self.helper.version,
            "helper_sha256": self.helper.hash,
            "scope": "electrical route through explicitly selected miniDSP unit",
            "storage_readback": "unavailable; sent coefficients do not verify storage",
        }

    def snapshot(self) -> dict:
        return {
            "master_status": self.command("-o", "json", "status"),
            "restore_commands": self.restore_commands,
            "scope": "master status plus user-supplied complete configuration; no coefficient readback",
        }

    def mute(self, value: bool) -> None:
        self.command("mute", "on" if value else "off")

    def load(self, case: dict) -> dict:
        route = self.profile.route(case["route"], case["channel"], case["rate"])
        exact = np.asarray(
            case.get("transport_sos", case["exact_sos"]), dtype=float
        ).reshape(-1, 6)
        if len(exact) > route.sections:
            raise ValueError("cascade exceeds selected route capacity")
        # Transport is round-trip binary64 decimal; the float32 storage model is
        # a stated hypothesis until checked by readback or independent evidence.
        sent = np.array([[float(f"{x:.17g}") for x in row] for row in exact]).reshape(
            -1, 6
        )
        predicted = rounded(sent, self.profile.coefficient_format)
        if not stable(sent) or not stable(predicted):
            raise ValueError("unstable sent/stored-model cascade; refusing load")
        prefix = (case["route"], str(case["channel"]), "peq")
        self.command(*prefix, "all", "clear")
        commands = [[*prefix, "all", "clear"]]
        for index, (b0, b1, b2, _, a1, a2) in enumerate(sent):
            command = [
                *prefix,
                str(index),
                "set",
                "--",
                *(f"{value:.17g}" for value in (b0, b1, b2, -a1, -a2)),
            ]
            self.command(*command)
            commands.append(command)
            command = [*prefix, str(index), "bypass", "off"]
            self.command(*command)
            commands.append(command)
        return {
            "commands": commands,
            "sent_sos": sent.tolist(),
            "candidate_stored_sos": predicted.tolist(),
            "storage_verified": False,
            "model": self.profile.coefficient_format,
            "readback_sos": None,
        }

    def restore(self, snapshot: dict) -> bool:
        self.mute(True)
        for command in snapshot["restore_commands"]:
            if command[0] == "mute":
                continue  # without readback, restoration cannot justify unmuting
            self.command(*command)
        return False


def camilla_filters(sos: np.ndarray) -> tuple[dict, list[str]]:
    filters = {}
    for index, (b0, b1, b2, _, a1, a2) in enumerate(sos):
        filters[f"section-{index}"] = {
            "type": "Biquad",
            "parameters": {
                "type": "Free",
                "b0": b0,
                "b1": b1,
                "b2": b2,
                "a1": a1,
                "a2": a2,
            },
        }
    return filters, list(filters)


class CamillaFile:
    """Real CamillaDSP executable with raw file I/O; does not touch live routing."""

    live = False

    def __init__(self, helper: Helper, rate: int, directory: Path):
        self.helper, self.rate, self.directory = helper, rate, directory
        directory.mkdir(parents=True, exist_ok=True)
        self.sos = np.empty((0, 6))
        self.muted = True

    def identify(self) -> dict:
        return {
            "engine": "camilladsp",
            "version": self.helper.version,
            "helper_sha256": self.helper.hash,
            "internal_rate": self.rate,
            "arithmetic": "float64 default build; verify build provenance",
            "scope": "raw file-in/file-out reference; no live audio path",
        }

    def snapshot(self) -> dict:
        return {"sos": self.sos.tolist(), "muted": self.muted}

    def mute(self, value: bool) -> None:
        self.muted = value

    def load(self, case: dict) -> dict:
        if case["rate"] != self.rate:
            raise ValueError("CamillaDSP internal rate mismatch")
        self.sos = np.asarray(
            case.get("transport_sos", case["exact_sos"]), dtype=float
        ).reshape(-1, 6)
        if not stable(self.sos):
            raise ValueError("unstable CamillaDSP cascade")
        filters, names = camilla_filters(self.sos)
        return {
            "sent_sos": self.sos.tolist(),
            "filters": filters,
            "order": names,
            "storage_verified": False,
            "model": "float64",
            "readback_sos": None,
            "scope": "explicit file config; not coefficient bit readback",
        }

    def capture(self, stimulus: np.ndarray, rate: int) -> tuple[np.ndarray, dict]:
        if self.muted or rate != self.rate:
            raise ValueError("CamillaDSP reference is muted or rate differs")
        with tempfile.TemporaryDirectory(dir=self.directory, prefix="camilla-") as name:
            root = Path(name)
            source, target = root / "input.raw", root / "output.raw"
            source.write_bytes(np.asarray(stimulus, dtype="<f8").tobytes())
            filters, names = camilla_filters(self.sos)
            config = {
                "devices": {
                    "samplerate": rate,
                    "chunksize": 1024,
                    "silence_threshold": 0,
                    "silence_timeout": 0,
                    "capture": {
                        "type": "RawFile",
                        "channels": 1,
                        "filename": str(source),
                        "format": "F64_LE",
                    },
                    "playback": {
                        "type": "File",
                        "channels": 1,
                        "filename": str(target),
                        "format": "F64_LE",
                    },
                },
                "filters": filters,
                "pipeline": [{"type": "Filter", "channels": [0], "names": names}]
                if names
                else [],
            }
            path = root / "config.json"
            path.write_text(json.dumps(config, allow_nan=False), encoding="utf-8")
            self.helper.command("--check", str(path))
            log = self.helper.command(
                str(path), timeout_s=max(30, len(stimulus) / rate * 2)
            )
            output = np.frombuffer(target.read_bytes(), dtype="<f8").copy()
            # The final chunk is zero padded by CamillaDSP; only discard verified
            # trailing padding, never truncate missing samples or filter decay.
            if len(output) < len(stimulus) or len(output) - len(stimulus) >= 1024:
                raise ValueError("CamillaDSP output sample count differs")
            if np.any(np.abs(output[len(stimulus) :]) > 1e-12):
                raise ValueError("CamillaDSP non-zero tail exceeds retained capture")
            config["devices"]["capture"]["filename"] = "input.raw"
            config["devices"]["playback"]["filename"] = "output.raw"
            return output[: len(stimulus), None], {
                "config": config,
                "log": log,
                "format": "float64 raw file transport",
                "statuses": [],
                "trailing_padding_samples": len(output) - len(stimulus),
                "scope": self.identify()["scope"],
            }

    def restore(self, snapshot: dict) -> bool:
        self.sos = np.asarray(snapshot["sos"]).reshape(-1, 6)
        self.muted = snapshot["muted"]
        return True


class CamillaLive:
    live = True

    def __init__(
        self,
        endpoint: str,
        expected_version: str,
        template: dict,
        rate: int,
        *,
        timeout_s: float = 10,
        connection=None,
    ):
        if connection is None:
            import websocket

            connection = websocket.create_connection(endpoint, timeout=timeout_s)
        self.connection, self.timeout_s, self.rate = connection, timeout_s, rate
        self.template = copy.deepcopy(template)
        self.version = self.command("GetVersion")
        if self.version != expected_version:
            raise ValueError("CamillaDSP version differs from pinned configuration")
        if template["devices"]["samplerate"] != rate:
            raise ValueError("CamillaDSP bench template rate differs")
        for side in ("capture", "playback"):
            if template["devices"][side].get("channels") != 1:
                raise ValueError(
                    "initial live CamillaDSP bench requires explicit mono routing"
                )
        if template["devices"].get("resampler"):
            raise ValueError("bench template must disable resampling")

    def command(self, name: str, value=None):
        self.connection.send(json.dumps(name if value is None else {name: value}))
        deadline = time.monotonic() + self.timeout_s
        for _ in range(100):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"CamillaDSP {name} timed out; no automatic retry")
            reply = json.loads(self.connection.recv())
            if name not in reply:
                continue
            result = reply[name]
            if result.get("result") != "Ok":
                raise ValueError(f"CamillaDSP {name}: {result}")
            return result.get("value")
        raise TimeoutError("CamillaDSP response limit exceeded")

    def identify(self) -> dict:
        return {
            "engine": "camilladsp",
            "version": self.version,
            "internal_rate": self.rate,
            "arithmetic": "float64 claim; pin and verify build separately",
            "scope": "live virtual/electrical route",
        }

    def snapshot(self) -> dict:
        return {
            "config": json.loads(self.command("GetConfigJson")),
            "mute": self.command("GetMute"),
            "volume": self.command("GetVolume"),
        }

    def mute(self, value: bool) -> None:
        self.command("SetMute", value)
        if self.command("GetMute") != value:
            raise ValueError("CamillaDSP mute readback disagrees")

    def set_config(self, config: dict) -> dict:
        serialised = json.dumps(config, allow_nan=False)
        validated = self.command("ValidateConfigJson", serialised)
        canonical = json.loads(validated) if isinstance(validated, str) else validated
        self.command("SetConfigJson", serialised)
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            active = json.loads(self.command("GetConfigJson"))
            if active == canonical:
                state = self.command("GetState")
                if state in ("Running", "Paused"):
                    return active
                if state not in ("Starting",):
                    raise ValueError(f"CamillaDSP processing state {state}")
            time.sleep(0.1)
        raise TimeoutError("CamillaDSP config did not become active")

    def load(self, case: dict) -> dict:
        if case["rate"] != self.rate:
            raise ValueError("CamillaDSP rate mismatch")
        sos = np.asarray(case.get("transport_sos", case["exact_sos"])).reshape(-1, 6)
        if not stable(sos):
            raise ValueError("unstable cascade")
        config = copy.deepcopy(self.template)
        filters, names = camilla_filters(sos)
        filters["bench-mute"] = {"type": "Volume", "parameters": {"fader": "Main"}}
        config["filters"] = filters
        config["mixers"] = None
        config["processors"] = None
        config["pipeline"] = [
            {"type": "Filter", "channels": [0], "names": names + ["bench-mute"]}
        ]
        active = self.set_config(config)
        self.command("SetVolume", 0.0)
        return {
            "sent_sos": sos.tolist(),
            "active_config": active,
            "storage_verified": False,
            "model": "float64",
            "readback_sos": None,
            "readback_limitation": "active parameter configuration is not coefficient bit readback",
        }

    def restore(self, snapshot: dict) -> bool:
        self.mute(True)
        active = self.set_config(snapshot["config"])
        self.command("SetVolume", snapshot["volume"])
        verified = (
            active == snapshot["config"]
            and self.command("GetVolume") == snapshot["volume"]
        )
        if verified:
            self.mute(snapshot["mute"])
        return verified
