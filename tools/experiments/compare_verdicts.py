#!/usr/bin/env python3
"""Compare two record sets on the decisions only — what accept said, and about which filter.

Curves and parameters may move in their last digits when an optimiser takes a different path.
The question a change has to answer is whether the *verdict* moved: which candidates passed,
why the others failed, which was accepted, and how many sections it published.
"""

import gzip
import json
import sys
from pathlib import Path


def load(p):
    with gzip.open(p, "rt", encoding="utf-8") as h:
        return json.load(h)


def decisions(d):
    out = {"accepted": d.get("accepted")}
    for c in d["candidates"]:
        v = c["verdict"]
        out[c["label"]] = {
            "passed": v["passed"],
            "failures": v["failures"],
            "sections": len(c["filters"]),
            "types": [f["type"] for f in c["filters"]],
        }
    return out


old, new = Path(sys.argv[1]), Path(sys.argv[2])
bad = 0
for name in sorted(p.name for p in old.glob("*.run.json.gz")):
    a, b = decisions(load(old / name)), decisions(load(new / name))
    if a == b:
        print(f"{name}: verdicts identical (accepted: {a['accepted']})")
        continue
    bad += 1
    print(f"{name}: VERDICTS DIFFER")
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            print(f"    {k}:\n      old {a.get(k)}\n      new {b.get(k)}")
sys.exit(1 if bad else 0)
