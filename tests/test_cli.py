"""`beqforge <subcommand>` dispatch."""

import io
import sys
import types

from beqforge import cli

TEXT = " ▁▂▃▄▅▆▇█ → −"


def test_dispatch_forces_utf8_stdout_and_stderr(monkeypatch):
    """The installed command bypasses each script's `__main__` guard, where the scripts force
    UTF-8; on Windows a piped stdout/stderr is otherwise cp1252 and a non-ASCII print or log
    line crashes or garbles."""
    out, err = io.BytesIO(), io.BytesIO()
    for name, raw in (("stdout", out), ("stderr", err)):
        monkeypatch.setattr(
            sys, name, io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
        )
    fake = types.ModuleType("tools.fake")

    def main() -> int:
        print(TEXT)
        print(TEXT, file=sys.stderr)
        return 0

    fake.main = main
    monkeypatch.setitem(sys.modules, "tools.fake", fake)
    monkeypatch.setitem(cli._SUBCOMMANDS, "fake", "tools.fake")
    monkeypatch.setattr(sys, "argv", ["beqforge"])

    assert cli.main(["fake"]) == 0
    sys.stdout.flush()
    sys.stderr.flush()
    assert out.getvalue().decode("utf-8") == TEXT + "\n"
    assert err.getvalue().decode("utf-8") == TEXT + "\n"
