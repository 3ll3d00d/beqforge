#!/usr/bin/env python3
"""Run the predeclared final-selection protocol; see AGENTS.md's "Evidence and confidence"
notes and evidence_validation.json for the results this produced."""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqforge.harness import evidence_cases, score_evidence_case  # noqa: E402
from beqforge.pipeline import PipelineParams, run  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, choices=(101, 947), default=947)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    params = PipelineParams()
    rows = []
    for case in evidence_cases(args.seed):
        report = run(case.material(), params)
        rows.append(score_evidence_case(case, report, params))
        document = {"seed": args.seed, "params": repr(params), "cases": rows}
        args.output.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n")
        logging.info(f"SCORED {rows[-1]}")
    logging.info("EVIDENCE_VALIDATION_DONE")


if __name__ == "__main__":
    # Windows defaults a redirected/piped stdout to the system codepage rather than
    # UTF-8, which crashes on this module's non-ASCII output; force UTF-8 so a print
    # never dies on the encoding rather than the content.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
