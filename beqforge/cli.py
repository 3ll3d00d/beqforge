"""`beqforge <subcommand> ...` — one installed command, dispatching to the entry-point scripts.

Each subcommand keeps its own argparse and its own `main()` in `tools/`; this only strips the
subcommand token off argv and hands the rest through unchanged, so `beqforge design --help`
shows exactly what `python tools/design_beq.py --help` always has.
"""

import importlib
import sys

_SUBCOMMANDS = {
    "extract": "tools.extract",
    "design": "tools.design_beq",
    "replay": "tools.replay",
    "summarise": "tools.summarise",
    "ledger": "tools.render_ledger",
    "validate": "tools.validate_evidence",
}


def _usage() -> str:
    names = ", ".join(sorted(_SUBCOMMANDS))
    return f"usage: beqforge {{{names}}} ...\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.stderr.write(_usage())
        return 2
    if argv[0] in ("-h", "--help"):
        sys.stdout.write(_usage())
        return 0
    subcommand, rest = argv[0], argv[1:]
    module_name = _SUBCOMMANDS.get(subcommand)
    if module_name is None:
        sys.stderr.write(_usage())
        sys.stderr.write(f"beqforge: unknown subcommand {subcommand!r}\n")
        return 2
    module = importlib.import_module(module_name)
    sys.argv = [f"beqforge {subcommand}", *rest]
    return module.main()


if __name__ == "__main__":
    sys.exit(main())
