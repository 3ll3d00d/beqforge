#!/usr/bin/env python3
"""Run E10's synthetic families and score them (plans/E10-validation-protocol.md, TODO 3).

    uv run python tools/e10_run.py --partition development --seeds 1-6 --output e10_dev.json

One process per case, each case designed at every goal (the analysis is shared through a
scratch stage cache), with the fitter's own pool off inside it, as `tools/negative_corpus.py`
runs. The output carries the protocol version, the build, every row and the summary; it is
scratch evidence, never committed.

`--partition held-out` takes the first `HELD_OUT_PER_FAMILY` seeds of the held-out block and
refuses to run on a working tree with uncommitted changes: a held-out run judges a frozen
change, and its result names the commit it judged.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqforge import e10, record  # noqa: E402


def _seeds(text: str) -> list[int]:
    seeds: list[int] = []
    for part in text.split(","):
        low, _, high = part.partition("-")
        seeds.extend(range(int(low), int(high or low) + 1))
    return seeds


def _run_case(job: tuple[str, int, tuple[str, ...], float]) -> list[dict]:
    family, seed, goals, duration_s = job
    logging.disable(logging.WARNING)
    from beqforge import filters
    from beqforge.accept import AcceptParams
    from beqforge.cache import DirStore
    from beqforge.pipeline import PipelineParams, run

    filters.PARALLEL_FITS = False
    case = e10.e10_case(family, seed, duration_s)
    material = case.material()
    rows = []
    with tempfile.TemporaryDirectory(prefix="e10-") as scratch:
        store = DirStore(Path(scratch))
        for goal in goals:
            tilt, tolerance = e10.GOALS[goal]
            params = PipelineParams(
                accept=AcceptParams(
                    target_tilt_db_per_octave=tilt, goal_tolerance_db=tolerance
                )
            )
            started = time.perf_counter()
            report = run(material, params, cache_path=store)
            row = e10.score(case, goal, report, params)
            row["seconds"] = round(time.perf_counter() - started, 1)
            rows.append(row)
    flagged = [f"{r['goal']}:{name}" for r in rows for name in e10.CLASSES if r[name]]
    print(
        f"  {case.name:26s} "
        + " ".join(f"{r['goal']}={r['selected'] or '-'}" for r in rows)
        + (f"  [{', '.join(flagged)}]" if flagged else ""),
        flush=True,
    )
    return rows


def _clean_tree() -> bool:
    root = Path(__file__).resolve().parent.parent
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return status.returncode == 0 and not status.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--partition", choices=("development", "held-out"), default="development"
    )
    parser.add_argument(
        "--seeds",
        help="development seeds, e.g. 1-6 or 1,4,7-12 (held-out takes its own block)",
        default="1-3",
    )
    parser.add_argument("--families", help="comma-separated; default all")
    parser.add_argument("--goals", default=",".join(e10.GOALS))
    parser.add_argument("--duration", type=float, default=e10.DURATION_S, metavar="S")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2)
    )
    args = parser.parse_args()

    families = tuple(args.families.split(",")) if args.families else e10.FAMILIES
    goals = tuple(args.goals.split(","))
    for name in families:
        if name not in e10.FAMILIES:
            parser.error(f"unknown family {name}; have {', '.join(e10.FAMILIES)}")
    for goal in goals:
        if goal not in e10.GOALS:
            parser.error(f"unknown goal {goal}; have {', '.join(e10.GOALS)}")
    if args.partition == "held-out":
        if not _clean_tree():
            parser.error("a held-out run judges a committed change: commit first")
        seeds = list(e10.HELD_OUT_SEEDS)[: e10.HELD_OUT_PER_FAMILY]
    else:
        seeds = _seeds(args.seeds)
        stray = [s for s in seeds if s not in e10.DEVELOPMENT_SEEDS]
        if stray:
            parser.error(f"seeds outside the development block: {stray}")

    jobs = [(f, s, goals, args.duration) for f in families for s in seeds]
    print(
        f"E10 {e10.PROTOCOL_VERSION}, {args.partition}: {len(jobs)} cases x "
        f"{len(goals)} goals on {args.workers} workers, build {record.revision()}",
        flush=True,
    )
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for case_rows in pool.map(_run_case, jobs):
            rows.extend(case_rows)
    document = {
        "protocol": e10.PROTOCOL_VERSION,
        "partition": args.partition,
        "build": record.revision(),
        "goals": {g: e10.GOALS[g] for g in goals},
        "seeds": seeds,
        "summary": e10.summarise(rows),
        "cases": rows,
    }
    args.output.write_text(json.dumps(document, indent=2) + "\n")
    for goal, summary in document["summary"].items():
        pooled = summary["pooled"]
        print(
            f"{goal}: "
            + ", ".join(
                f"{name} {pooled[name]['k']}/{pooled[name]['n']} "
                f"(<= {pooled[name]['upper']:.1%})"
                for name in e10.CLASSES
            )
            + f"; median shortfall {pooled['shortfall_median_db']} dB",
            flush=True,
        )
    print("E10-DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
