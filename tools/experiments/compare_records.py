#!/usr/bin/env python3
"""Compare two directories of run records, ignoring what is allowed to move.

Fingerprint and timings change by construction on every commit; everything else is the
answer and must not move for a change claimed to be output-preserving.
"""

import gzip
import json
import sys
from pathlib import Path

IGNORE_TOP = {"fingerprint", "timings"}


def load(p):
    with gzip.open(p, "rt", encoding="utf-8") as h:
        d = json.load(h)
    return {k: v for k, v in d.items() if k not in IGNORE_TOP}


def walk(a, b, path=""):
    out = []
    if type(a) is not type(b):
        return [f"{path}: type {type(a).__name__} -> {type(b).__name__}"]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: added")
            elif k not in b:
                out.append(f"{path}.{k}: removed")
            else:
                out += walk(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} -> {len(b)}"]
        for i, (x, y) in enumerate(zip(a, b)):
            out += walk(x, y, f"{path}[{i}]")
    elif a != b:
        out.append(f"{path}: {a!r} -> {b!r}")
    return out


def main():
    old, new = Path(sys.argv[1]), Path(sys.argv[2])
    names = sorted(
        {p.name for p in old.glob("*.run.json.gz")}
        | {p.name for p in new.glob("*.run.json.gz")}
    )
    if not names:
        print("no records to compare")
        return 1
    bad = 0
    for name in names:
        a, b = old / name, new / name
        if not a.is_file() or not b.is_file():
            print(f"{name}: MISSING in {'old' if not a.is_file() else 'new'}")
            bad += 1
            continue
        diffs = walk(load(a), load(b))
        if diffs:
            bad += 1
            print(f"{name}: {len(diffs)} DIFFERENCE(S)")
            for d in diffs[:25]:
                print(f"    {d}")
            if len(diffs) > 25:
                print(f"    ... and {len(diffs) - 25} more")
        else:
            print(f"{name}: identical")
    return 1 if bad else 0


sys.exit(main())
