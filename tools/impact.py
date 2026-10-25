"""Which designs a designer upgrade may move, and whether a commit range declares what it changed.

    uv run python tools/impact.py rank RECORD... [--design-settings DIGEST]
    uv run python tools/impact.py check BASE [HEAD]

`rank` scores run records as `POST /impact` does (designer-interface.md 1.6 §7.1), against this
checkout's design version and the default settings (or `--design-settings`), and prints them by
tier, highest score first, with each reason.

`check` is part of the regression check (beqforge/AGENTS.md): every function, class field and
module constant under `beqforge/` and `beq_common/` that changed between BASE and HEAD (the
working tree when HEAD is left out) must belong to a feature in `beqforge.impact.FEATURES`, and
when the design version moved, every answer-reaching feature among them must be declared by a
change in HEAD's `impact.toml` after BASE's version. Docstrings and comments don't count as
changes. It exits 1 on any failure.
"""

import argparse
import gzip
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from beqforge import impact  # noqa: E402

PACKAGES = ("beqforge", "beq_common")
_TIERS = ("will_move", "unknown", "likely", "possible", "unaffected")


def module_name(path: str) -> str:
    """`beqforge/pipeline.py` to `pipeline`, `beq_common/biquad.py` to `beq_common.biquad`; a
    package's `__init__.py` is `__init__` in beqforge and the package name in beq_common."""
    package, _, file = path.partition("/")
    stem = file.removesuffix(".py")
    if package == "beqforge":
        return stem
    return package if stem == "__init__" else f"{package}.{stem}"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def _show(revision: str | None, path: str) -> str | None:
    if revision is None:
        file = ROOT / path
        return file.read_text(encoding="utf-8") if file.exists() else None
    try:
        return _git("show", f"{revision}:{path}")
    except subprocess.CalledProcessError:
        return None


def _design_version(revision: str | None) -> int:
    source = _show(revision, "beqforge/designer.py") or ""
    found = re.search(r"^DESIGN_VERSION = (\d+)", source, re.MULTILINE)
    if found is None:
        raise SystemExit(
            f"no DESIGN_VERSION in beqforge/designer.py at {revision or 'the working tree'}"
        )
    return int(found.group(1))


def check(base: str, head: str | None) -> int:
    span = [base] if head is None else [base, head]
    listed = _git("diff", "--name-only", *span, "--", *PACKAGES).split()
    if head is None:
        # a module not yet added is a change too
        listed += _git(
            "ls-files", "--others", "--exclude-standard", "--", *PACKAGES
        ).split()
    paths = sorted({p for p in listed if p.endswith(".py") and p.count("/") == 1})
    failures: list[str] = []
    touched: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        module = module_name(path)
        for qualname in sorted(impact.changed(_show(base, path), _show(head, path))):
            qualified = f"{module}:{qualname}"
            owning = impact.owners(qualified)
            if not owning:
                failures.append(f"{qualified} changed and no feature owns it")
            for f in owning:
                touched[f.id].append(qualified)
    try:
        data = impact.parse(_show(head, "beqforge/impact.toml") or "")
    except (ValueError, KeyError) as bad:
        failures.append(f"impact.toml does not parse: {bad}")
        data = None
    old, new = _design_version(base), _design_version(head)
    answering = {f for f in touched if impact.feature(f).answers}
    print(f"design version {old} -> {new}")
    for f in sorted(touched):
        mark = "" if impact.feature(f).answers else " (changes no answer)"
        print(f"  {f}{mark}: {', '.join(touched[f])}")
    if data is not None and new > old:
        changes = data.after(old, new)
        if not any(c.design_version == new for c in changes):
            failures.append(f"impact.toml has no change at design version {new}")
        declared = {t.feature for c in changes for t in c.touches}
        for f in sorted(answering - declared):
            failures.append(
                f"{f} changed ({', '.join(touched[f])}) and no change after version {old} declares it"
            )
    elif data is not None and answering:
        print(
            "warning: answer-reaching code changed with no design version bump; the regression "
            "check must show every answer unchanged"
        )
    for failure in failures:
        print(f"FAIL: {failure}")
    if not failures:
        print("ok")
    return 1 if failures else 0


def rank(paths: list[str], settings: str | None) -> int:
    from beqforge.designer import DESIGN_VERSION, design_settings_digest
    from beqforge.pipeline import PipelineParams

    data = impact.load()
    current = (DESIGN_VERSION, settings or design_settings_digest(PipelineParams()))
    found = []
    for path in paths:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                record = json.load(f)
            result = impact.assess(record, current, data)
        except (OSError, EOFError, json.JSONDecodeError) as unreadable:
            result = impact.Assessment(
                "unknown",
                None,
                None,
                (impact.Reason(None, None, f"unreadable: {unreadable}"),),
            )
        found.append((path, result))
    found.sort(key=lambda p: (_TIERS.index(p[1].tier), -(p[1].score or 0.0), p[0]))
    counts = defaultdict(int)
    for path, result in found:
        counts[result.tier] += 1
        if result.tier == "unaffected":
            continue
        score = "-" if result.score is None else f"{result.score:.2f}"
        print(f"{result.tier:10s} {score:>5s}  v{result.from_design_version}  {path}")
        for reason in result.reasons:
            print(
                f"    [{reason.change or '-'} / {reason.feature or '-'}] {reason.detail}"
            )
    print(", ".join(f"{t} {counts[t]}" for t in _TIERS if counts[t]))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ranking = sub.add_parser("rank", help="score run records against this checkout")
    ranking.add_argument("records", nargs="+")
    ranking.add_argument(
        "--design-settings",
        help="the settings digest to score against (default: the default settings')",
    )
    checking = sub.add_parser(
        "check", help="check a commit range declares what it changed"
    )
    checking.add_argument("base")
    checking.add_argument("head", nargs="?")
    args = parser.parse_args()
    if args.command == "rank":
        return rank(args.records, args.design_settings)
    return check(args.base, args.head)


if __name__ == "__main__":
    sys.exit(main())
