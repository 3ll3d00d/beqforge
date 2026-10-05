import json
import os
import shlex
import subprocess
from pathlib import Path

import numpy as np
import pytest

from beqforge_device_check.coefficients import response
from beqforge_device_check.engines import (
    MINIDSP_VERSION,
    CamillaFile,
    CamillaLive,
    Helper,
    Minidsp,
    usb_loopback_route,
)
from beqforge_device_check.manifest import generate
from beqforge_device_check.measurement import SweepSettings, recover, sweep
from beqforge_device_check.profiles import PROFILES
from beqforge_device_check.transactions import restore_state


def test_minidsp_signs_capacity_clear_and_unverified_restore(tmp_path):
    commands = []
    binary = tmp_path / "helper with spaces"
    binary.write_bytes(b"mock helper")

    processes = []
    batches = []

    def runner(args, **kwargs):
        assert kwargs["timeout"] == 10 and kwargs["check"]
        processes.append(args)
        if "-f" in args:
            assert args[1:3] == ["-d", "0"]
            lines = Path(args[args.index("-f") + 1]).read_text().splitlines()
            batches.append([shlex.split(line) for line in lines])
            commands.extend(batches[-1])
        else:
            commands.append(args)
        stdout = (
            f"minidsp {MINIDSP_VERSION}"
            if args[-1] == "--version"
            else "0: Found 2x4HD with serial 123456 at usb:0"
            if args[-1] == "probe"
            else "{}"
        )
        return subprocess.CompletedProcess(args, 0, stdout, "")

    helper = Helper(binary, MINIDSP_VERSION, runner=runner)
    engine = Minidsp(
        helper,
        PROFILES["minidsp-2x4hd"],
        serial="123456",
        restore_commands=[["config", "0"], ["mute", "off"]],
    )
    case = generate(PROFILES["minidsp-2x4hd"])["cases"][1]
    before = len(processes)
    payload = engine.load(case)
    # One selection check and one batched helper process for the whole cascade.
    assert len(processes) - before == 2
    assert batches[-1] == payload["commands"]
    assert payload["commands"][0][-2:] == ["all", "clear"]
    values = [float(x) for x in payload["commands"][1][-5:]]
    assert values[-2] == -float(np.float32(case["exact_sos"][0][4]))
    assert np.array_equal(
        payload["sent_sos"],
        np.asarray(case["exact_sos"], dtype=np.float32).astype(float),
    )
    assert not np.array_equal(payload["requested_sos"], payload["sent_sos"])
    assert payload["transport_format"] == "float32"
    assert not payload["storage_verified"]
    assert not engine.restore(engine.snapshot())
    # Muted first, never unmuted by restoration, in one batch.
    assert batches[-1] == [["mute", "on"], ["config", "0"]]


def test_helper_timeout_and_version_fail_without_retry(tmp_path):
    binary = tmp_path / "helper"
    binary.write_bytes(b"mock")
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(args, 10)

    with pytest.raises(subprocess.TimeoutExpired):
        Helper(binary, MINIDSP_VERSION, runner=runner)
    assert len(calls) == 1


def test_restoration_failure_is_recorded_and_mute_retried():
    class BrokenRestore:
        def mute(self, value):
            assert value

        def restore(self, snapshot):
            raise TimeoutError("disconnected")

    restored, errors = restore_state(BrokenRestore(), {})
    assert not restored and "disconnected" in errors[0]


def test_camilla_websocket_matches_commands_and_reports_error():
    class Connection:
        def send(self, message):
            self.message = json.loads(message)

        def recv(self):
            return json.dumps({"GetVersion": {"result": "Ok", "value": "4.1.3"}})

    template = {
        "devices": {
            "samplerate": 96000,
            "capture": {"channels": 1},
            "playback": {"channels": 1},
        }
    }
    engine = CamillaLive("unused", "4.1.3", template, 96000, connection=Connection())
    assert engine.version == "4.1.3"
    with pytest.raises(TimeoutError, match="response limit"):
        engine.command("GetMute")


@pytest.mark.skipif(
    not os.environ.get("F2_CAMILLADSP"), reason="explicit reference binary not supplied"
)
def test_real_camilladsp_file_reference(tmp_path):
    pytest.importorskip("pyfar")
    engine = CamillaFile(
        Helper(Path(os.environ["F2_CAMILLADSP"]), "4.1.3"), 96000, tmp_path
    )
    x, metadata = sweep(SweepSettings(duration_s=2, tail_s=20))
    for case in generate(PROFILES["camilladsp-float64"])["cases"]:
        engine.load(case)
        engine.mute(False)
        y, _ = engine.capture(x, 96000)
        result = recover(x, y[:, 0], metadata)
        expected = response(
            np.asarray(case["exact_sos"]).reshape(-1, 6), result["frequencies"], 96000
        )
        mask = result["mask"]
        assert (
            np.max(
                np.abs(20 * np.log10(abs(result["response"][mask] / expected[mask])))
            )
            < 1e-6
        )


def test_minidsp_route_is_opt_in_and_applied_in_one_batch(tmp_path):
    binary = tmp_path / "helper"
    binary.write_bytes(b"mock")
    processes, batches = [], []

    def runner(args, **kwargs):
        processes.append(args)
        if "-f" in args:
            lines = Path(args[args.index("-f") + 1]).read_text().splitlines()
            batches.append([shlex.split(line) for line in lines])
        stdout = (
            f"minidsp {MINIDSP_VERSION}"
            if args[-1] == "--version"
            else "0: Found 2x4HD with serial 123456 at usb:0"
            if args[-1] == "probe"
            else "{}"
        )
        return subprocess.CompletedProcess(args, 0, stdout, "")

    profile = PROFILES["minidsp-2x4hd"]
    helper = Helper(binary, MINIDSP_VERSION, runner=runner)
    # Without the opt-in, starting a stage sends nothing but a status read.
    plain = Minidsp(
        helper, profile, serial="123456", restore_commands=[["config", "0"]]
    )
    assert plain.snapshot()["route_commands_applied"] == []
    assert batches == []

    route = usb_loopback_route(profile)
    # The DUT input feeds only output 0; the reference only output 1.
    enabled = {
        (c[1], c[3])
        for c in route
        if c[2:3] == ["routing"] and c[4:] == ["enable", "true"]
    }
    assert enabled == {("0", "0"), ("1", "1")}
    disabled = [c for c in route if c[2:3] == ["routing"] and c[-1] == "false"]
    assert len(disabled) == 2 * 3
    assert ["input", "1", "peq", "all", "clear"] not in route
    assert ["output", "2", "mute", "on"] in route
    assert ["output", "3", "mute", "on"] in route
    assert route[0] == ["source", "usb"]
    engine = Minidsp(helper, profile, serial="123456", route_commands=route)
    before = len(processes)
    snapshot = engine.snapshot()
    # Status, then one selection check and one helper process for the whole route.
    assert len(processes) - before == 4
    assert batches[-1] == route == snapshot["route_commands_applied"]
    # Restoration defaults to the route, muted first and never unmuting the master.
    assert not engine.restore(snapshot)
    assert batches[-1] == [["mute", "on"], *route]

    with pytest.raises(ValueError, match="own input and output"):
        usb_loopback_route(profile, reference_input=0)
    with pytest.raises(ValueError, match="setting argument arrays"):
        Minidsp(helper, profile, serial="123456", route_commands=[["debug", "x"]])
