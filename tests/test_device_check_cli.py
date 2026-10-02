import json

import pytest

from beqforge_device_check.cli import main, validate_config
from beqforge_device_check.profiles import PROFILES


def live_config():
    return {
        "schema_version": 1,
        "profile": PROFILES["minidsp-2x4hd"].as_dict(),
        "route": "input",
        "channel": 0,
        "rate": 96000,
        "engine_mode": "minidsp",
        "firmware_or_build": "documented firmware",
        "physical_route": "electrical bench",
        "electrical_bench_acknowledged": True,
        "audio": {"input": {"channels": 2, "channel": 0}},
    }


@pytest.mark.parametrize("reference", [-1, 0, 2, True])
def test_timing_reference_cannot_be_the_dut_or_an_invalid_channel(reference):
    with pytest.raises(ValueError, match="separate captured input"):
        validate_config({**live_config(), "reference_channel": reference})


def test_valid_independent_timing_reference_and_explicit_clock_basis():
    config = {**live_config(), "reference_channel": 1}
    assert validate_config(config).id == "minidsp-2x4hd"
    with pytest.raises(ValueError, match="boolean"):
        validate_config({**config, "common_clock": "false"})
    with pytest.raises(ValueError, match="clock basis"):
        validate_config({**config, "common_clock": True})


def test_offline_setup_and_plan_do_not_require_audio_or_device(tmp_path, capsys):
    config, manifest = tmp_path / "bench.json", tmp_path / "cases.json"
    assert main(["setup", "--profile", "simulation-float64", "--out", str(config)]) == 0
    assert main(["plan", "--config", str(config), "--out", str(manifest)]) == 0
    value = json.loads(manifest.read_text())
    assert len(value["cases"]) == 3
    assert value["levels_dbfs"] == [-30, -50]
    assert not json.loads(config.read_text())["electrical_bench_acknowledged"]
    capsys.readouterr()


def test_planning_refuses_profile_rate_mismatch(tmp_path, capsys):
    assert (
        main(
            [
                "setup",
                "--profile",
                "minidsp-2x4hd",
                "--rate",
                "48000",
                "--out",
                str(tmp_path / "bad.json"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "bad.json").exists()
    capsys.readouterr()
