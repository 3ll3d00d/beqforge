"""Configuration failures must be caught before the designer starts listening."""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools import designer_server


@pytest.fixture
def startup(monkeypatch, tmp_path):
    for name in os.environ:
        if name.startswith("BEQFORGE_"):
            monkeypatch.delenv(name)
    # records and the log default to the per-user data directory: never the real one here
    monkeypatch.setattr(designer_server, "data_dir", lambda: tmp_path / "data")
    server = Mock()
    constructor = Mock(return_value=server)
    monkeypatch.setattr(designer_server, "DesignServer", constructor)

    def run(*arguments):
        monkeypatch.setattr(sys, "argv", ["serve-designer", *arguments])
        return designer_server.main()

    return run, constructor, server


DIRECTORIES = ["--cache-dir", "--shared-root", "--record-dir", "--log-dir"]


@pytest.mark.parametrize("option", DIRECTORIES)
@pytest.mark.parametrize("existing", [False, True])
def test_directory_is_ready_before_listening(startup, tmp_path, option, existing):
    directory = tmp_path / "parent" / "directory"
    if existing:
        directory.mkdir(parents=True)
        (directory / "existing").write_text("keep me")
    run, constructor, server = startup

    def bind(*_, **__):
        assert directory.is_dir()
        expected = ["existing"] if existing else []
        if option == "--log-dir":
            expected.append(designer_server.LOG_FILE)  # opened before the server binds
        assert sorted(p.name for p in directory.iterdir()) == sorted(expected)
        return server

    constructor.side_effect = bind
    assert run(option, str(directory)) == 0
    server.serve_forever.assert_called_once()
    server.server_close.assert_called_once()


@pytest.mark.parametrize("option", DIRECTORIES)
@pytest.mark.parametrize("parent_is_file", [False, True])
def test_file_in_directory_path_fails_before_listening(
    startup, tmp_path, capsys, option, parent_is_file
):
    obstruction = tmp_path / "file"
    obstruction.write_text("keep me")
    directory = obstruction / "child" if parent_is_file else obstruction
    run, constructor, _ = startup
    with pytest.raises(SystemExit) as refused:
        run(option, str(directory))
    assert refused.value.code == 2
    error = capsys.readouterr().err
    assert option in error and str(directory) in error
    assert "cannot create or write directory" in error
    constructor.assert_not_called()
    assert obstruction.read_text() == "keep me"


@pytest.mark.parametrize("option", DIRECTORIES)
def test_failed_write_fails_before_listening(
    startup, monkeypatch, tmp_path, capsys, option
):
    # Permission bits are unreliable under root and on Windows; fail the actual write.
    probe = Mock()
    probe.write.side_effect = PermissionError("write denied")
    temporary = Mock()
    temporary.__enter__ = Mock(return_value=probe)
    temporary.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(
        designer_server.tempfile, "NamedTemporaryFile", Mock(return_value=temporary)
    )
    directory = tmp_path / "directory"
    run, constructor, _ = startup
    with pytest.raises(SystemExit) as refused:
        # with records on, their default directory would fail before the log's
        run(option, str(directory), *(["--no-record"] if option == "--log-dir" else []))
    assert refused.value.code == 2
    assert "write denied" in capsys.readouterr().err
    constructor.assert_not_called()
    assert directory.is_dir()


def test_unconfigured_directories_do_not_probe_filesystem(startup, monkeypatch):
    prepare = Mock(side_effect=AssertionError("unexpected directory check"))
    monkeypatch.setattr(designer_server, "_prepare_directory", prepare)
    run, constructor, _ = startup
    assert run("--no-record", "--no-log-file") == 0
    prepare.assert_not_called()
    (_, settings), _ = constructor.call_args
    assert settings.record_dir is None and settings.log_file is None


def test_records_and_the_log_are_kept_by_default(startup, tmp_path, caplog):
    """TODO 27: a server started with no flags keeps what a review needs."""
    caplog.set_level(logging.INFO)  # as `main`'s basicConfig sets it outside pytest
    run, constructor, _ = startup
    root = logging.getLogger()
    handlers = list(root.handlers)
    assert run() == 0
    (_, settings), _ = constructor.call_args
    assert settings.record_dir == tmp_path / "data" / "records"
    assert settings.record_dir.is_dir()
    assert settings.log_file == tmp_path / "data" / "logs" / designer_server.LOG_FILE
    assert "beqforge designer server" in settings.log_file.read_text(encoding="utf-8")
    assert root.handlers == handlers  # the file handler goes when the server does


@pytest.mark.parametrize("value", ["0", "false", "off"])
def test_records_can_be_turned_off_from_the_environment(startup, monkeypatch, value):
    """A false setting turns off a flag that defaults on, not only one that defaults off."""
    monkeypatch.setenv("BEQFORGE_RECORD", value)
    monkeypatch.setenv("BEQFORGE_LOG_FILE", value)
    run, constructor, _ = startup
    assert run() == 0
    (_, settings), _ = constructor.call_args
    assert settings.record_dir is None and settings.log_file is None


@pytest.mark.parametrize(
    ("platform", "environment", "expected"),
    [
        (
            "win32",
            {"LOCALAPPDATA": "C:/Users/u/AppData/Local"},
            "C:/Users/u/AppData/Local",
        ),
        ("linux", {"XDG_STATE_HOME": "/state"}, "/state"),
        ("linux", {}, "~/.local/state"),
        ("darwin", {}, "~/Library/Application Support"),
    ],
)
def test_the_data_directory_is_the_platforms_per_user_place(
    monkeypatch, platform, environment, expected
):
    for name in ("LOCALAPPDATA", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(designer_server.sys, "platform", platform)
    expected_root = Path(expected).expanduser() / "beqforge"
    assert designer_server.data_dir() == expected_root


def test_every_server_option_can_come_from_environment(startup, monkeypatch, tmp_path):
    settings = {
        "HOST": "127.0.0.2",
        "PORT": "9123",
        "DEVICE_RATE": "48000",
        "COEFFICIENT_BITS": "24",
        "INTEGER_BITS": "3",
        "EXCLUDE": "[[18, 22], [40, 42]]",
        "GOAL_TOLERANCE": "2.5",
        "GOAL_TILT": "-1.5",
        "CONTENT_EDGE": "yes",
        "STRATEGY": '["flatten", "counterfactual"]',
        "RECORD_DIR": str(tmp_path / "records"),
        "RECORD": "yes",
        "LOG_DIR": str(tmp_path / "logs"),
        "LOG_FILE": "true",
        "CACHE_DIR": str(tmp_path / "cache"),
        "SHARED_ROOT": str(tmp_path / "shared"),
        "WORKERS": "2",
        "CORES": "6",
        "QUIET": "1",
    }
    for name, value in settings.items():
        monkeypatch.setenv(f"BEQFORGE_{name}", value)
    # Capture the actual parsed configuration, including presentation-only quiet.
    parsed = []
    parse = designer_server._EnvironmentParser.parse_args

    def capture(parser, *args, **kwargs):
        namespace = parse(parser, *args, **kwargs)
        parsed.append(namespace)
        return namespace

    monkeypatch.setattr(designer_server._EnvironmentParser, "parse_args", capture)
    run, constructor, _ = startup
    assert run() == 0
    args = parsed[0]
    assert set(settings) == {name.upper() for name in vars(args)}
    assert args.quiet is True
    (address, settings), options = constructor.call_args
    assert address == ("127.0.0.2", 9123)
    assert options == {"log_level": logging.WARNING, "workers": 2, "cores": 6}
    params = settings.params
    assert params.realisation.fs == 48000
    assert params.realisation.coefficient_bits == 24
    assert params.realisation.integer_bits == 3
    assert params.exclude_bands_hz == ((18.0, 22.0), (40.0, 42.0))
    assert params.accept.goal_tolerance_db == 2.5
    assert params.accept.target_tilt_db_per_octave == -1.5
    assert params.judge_from_content_edge is True
    assert params.strategies == ("flatten", "counterfactual")
    assert settings.record_dir == tmp_path / "records"
    assert settings.log_file == tmp_path / "logs" / designer_server.LOG_FILE
    assert settings.cache.root == tmp_path / "cache"
    assert settings.shared_root == (tmp_path / "shared").resolve()
    assert (tmp_path / "cache").is_dir()
    assert (tmp_path / "shared").is_dir()


def test_cli_replaces_environment_values_including_repeated_and_boolean_options(
    startup, monkeypatch
):
    monkeypatch.setenv("BEQFORGE_PORT", "invalid but overridden")
    monkeypatch.setenv("BEQFORGE_STRATEGY", '["parametric"]')
    monkeypatch.setenv("BEQFORGE_EXCLUDE", "[[18, 22]]")
    monkeypatch.setenv("BEQFORGE_CONTENT_EDGE", "true")
    monkeypatch.setenv("BEQFORGE_QUIET", "true")
    run, constructor, _ = startup
    assert (
        run(
            "--po=8123",
            "--strategy",
            "flatten",
            "--strategy",
            "counterfactual",
            "--exclude",
            "30",
            "32",
            "--no-content-edge",
            "--no-quiet",
        )
        == 0
    )
    (address, settings), options = constructor.call_args
    assert address == ("127.0.0.1", 8123)
    assert options == {"log_level": logging.INFO, "workers": 1, "cores": None}
    params = settings.params
    assert params.strategies == ("flatten", "counterfactual")
    assert params.exclude_bands_hz == ((30.0, 32.0),)
    assert params.judge_from_content_edge is False


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_false_environment_boolean(startup, monkeypatch, value):
    monkeypatch.setenv("BEQFORGE_CONTENT_EDGE", value)
    run, constructor, _ = startup
    assert run() == 0
    (_, settings), _ = constructor.call_args
    assert settings.params.judge_from_content_edge is False


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PORT", "not-a-number", "invalid int value"),
        ("DEVICE_RATE", "nan", "device rate must be finite and positive"),
        ("COEFFICIENT_BITS", "3", "device format requires"),
        ("STRATEGY", "not-json", "BEQFORGE_STRATEGY must be a JSON array"),
        ("STRATEGY", '{"strategy": "flatten"}', "must be a JSON array"),
        ("STRATEGY", "[4]", "must be a JSON array of strings"),
        ("STRATEGY", '["unknown"]', "unknown strategy"),
        ("EXCLUDE", "[[18]]", "must be a JSON array of pairs"),
        ("EXCLUDE", "[18, 22]", "must be a JSON array of pairs"),
        ("EXCLUDE", '[[18, "invalid"]]', "invalid float value"),
        ("QUIET", "perhaps", "BEQFORGE_QUIET must be true/false"),
        ("WORKERS", "0", "workers must be 1-8"),
        ("WORKERS", "9", "workers must be 1-8"),
        ("CORES", "0", "cores must be at least workers (1)"),
        ("CORES", "two", "invalid int value"),
    ],
)
def test_invalid_environment_fails_before_listening(
    startup, monkeypatch, capsys, name, value, message
):
    monkeypatch.setenv(f"BEQFORGE_{name}", value)
    run, constructor, _ = startup
    with pytest.raises(SystemExit) as refused:
        run()
    assert refused.value.code == 2
    assert message in capsys.readouterr().err
    constructor.assert_not_called()


def test_help_lists_every_environment_option_even_with_invalid_environment(
    startup, monkeypatch, capsys
):
    monkeypatch.setenv("BEQFORGE_EXCLUDE", "invalid-json")
    run, constructor, _ = startup
    with pytest.raises(SystemExit) as helped:
        run("--help")
    assert helped.value.code == 0
    output = capsys.readouterr().out
    for name in (
        "HOST",
        "PORT",
        "DEVICE_RATE",
        "COEFFICIENT_BITS",
        "INTEGER_BITS",
        "EXCLUDE",
        "GOAL_TOLERANCE",
        "GOAL_TILT",
        "CONTENT_EDGE",
        "STRATEGY",
        "RECORD_DIR",
        "RECORD",
        "LOG_DIR",
        "LOG_FILE",
        "CACHE_DIR",
        "SHARED_ROOT",
        "WORKERS",
        "CORES",
        "QUIET",
    ):
        assert f"BEQFORGE_{name}" in output
    constructor.assert_not_called()


@pytest.mark.parametrize(
    ("threads", "workers", "share"),
    [
        (16, 1, None),  # one design: its usual pool
        (16, 2, 7),  # 8 cores with SMT: two designs use the threads, 7 each
        (16, 3, 5),
        (8, 2, 3),  # 8 cores without SMT: nothing extra, split the cores
        (16, 8, 1),
    ],
)
def test_concurrent_designs_share_the_logical_processors(
    monkeypatch, threads, workers, share
):
    monkeypatch.delenv("BEQ_FIT_WORKERS", raising=False)
    monkeypatch.setattr(designer_server.filters, "FIT_WORKERS", 7)
    monkeypatch.setattr(designer_server.os, "process_cpu_count", lambda: threads)
    assert designer_server.fit_share(workers) == share


def test_an_explicit_fit_pool_is_each_designs_own(monkeypatch):
    monkeypatch.setenv("BEQ_FIT_WORKERS", "4")
    assert designer_server.fit_share(2) is None


@pytest.mark.parametrize(
    ("workers", "cores", "share"),
    [
        (1, 4, 4),  # one design, held to 4
        (1, 12, 7),  # never wider than one design's usual pool
        (2, 8, 4),  # shared evenly
        (2, 5, 2),
        (3, 3, 1),
    ],
)
def test_cores_cap_what_the_designs_use_between_them(
    monkeypatch, workers, cores, share
):
    monkeypatch.setattr(designer_server.filters, "FIT_WORKERS", 7)
    monkeypatch.setattr(designer_server.os, "process_cpu_count", lambda: 16)
    assert designer_server.fit_share(workers, cores) == share
    # an explicit BEQ_FIT_WORKERS is capped by --cores too
    monkeypatch.setenv("BEQ_FIT_WORKERS", "7")
    assert designer_server.fit_share(workers, cores) == share


def test_cores_must_cover_the_workers(startup, capsys):
    run, constructor, _ = startup
    with pytest.raises(SystemExit) as refused:
        run("--workers", "3", "--cores", "2")
    assert refused.value.code == 2
    assert "cores must be at least workers (3)" in capsys.readouterr().err
    constructor.assert_not_called()
