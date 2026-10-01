import json

from beqforge_device_check.cli import main


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
