#!/usr/bin/env python3
"""Run the negative corpus and report false acceptances with an interval (IMPROVEMENT_PLAN E2).

    uv run python tools/negative_corpus.py --seeds 1-9 --output negative_corpus.json

Every case is `harness.corpus_case(shape, seed)`: a two-channel synthetic title whose truth is
known by construction. A **false acceptance** is any selected filter on a negative, however
carefully it qualifies itself — scored by `harness.score_evidence_case`, the same scorer as the
frozen protocol in `tools/validate_evidence.py`, which this does not replace.

The report gives, per shape, the false-acceptance rate with a two-sided 95% Clopper-Pearson
interval, and for `filtered` the true-positive rate and recovery. **The gate** is the interval's
upper bound over `harness.CORPUS_GATED` — every negative shape a correct pipeline can tell
from a filter. `natural_droop` is reported but not gated: a source recorded rolled off is
observationally a filtered one (E6), so its rate is a property of the problem, not a defect.
`--gate` is a stated preference, not a calibrated value; the exit status is 1 when the upper
bound exceeds it.

One process per case, with the fitter's own pool switched off inside each (nested pools would
oversubscribe the machine). A case takes 5-250 s with the fitter serial — abstentions before
the fit are quick — so 9 seeds (63 cases) take roughly 15-20 minutes on 16 cores.
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scipy.stats import beta  # noqa: E402

from beqforge import record  # noqa: E402
from beqforge.harness import CORPUS_GATED, CORPUS_SHAPES, corpus_case  # noqa: E402
from beqforge.pipeline import PipelineParams  # noqa: E402


def clopper_pearson(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Exact two-sided binomial interval: never narrower than the data allow, even at 0 of n."""
    if n == 0:
        return 0.0, 1.0
    alpha = 1.0 - confidence
    low = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    high = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return low, high


def _run_case(job: tuple[str, int, float]) -> dict:
    shape, seed, duration_s = job
    logging.disable(logging.WARNING)
    from beqforge import filters
    from beqforge.harness import score_evidence_case
    from beqforge.pipeline import run

    filters.PARALLEL_FITS = False
    case = corpus_case(shape, seed, duration_s)
    params = PipelineParams()
    started = time.perf_counter()
    report = run(case.material(), params)
    scored = score_evidence_case(case.evidence_case(), report, params)
    scored.pop("notes", None)
    chosen = report.accepted
    excess = None if chosen is None else chosen.evidence_excess
    scored.update(
        peak_boost_db=None if chosen is None else round(chosen.mv_adjust_db, 2),
        # IMPROVEMENT_PLAN E9: how far the selected cascade boosts past the ceiling
        evidence_excess_db=None if excess is None else round(excess.max_db, 2),
        evidence_excess_width_octaves=(
            None if excess is None else round(excess.width_octaves, 3)
        ),
        sections=None if chosen is None else len(chosen.filters),
        shape=shape,
        seed=seed,
        injected=None if case.injected is None else str(case.injected),
        seconds=round(time.perf_counter() - started, 1),
    )
    print(
        f"  {case.name:24s} {'selected ' + scored['selected'] if scored['selected'] else 'abstained'}"
        f" ({scored['seconds']:.0f} s)",
        flush=True,
    )
    return scored


def summarise(cases: list[dict]) -> dict:
    summary: dict = {}
    for shape in CORPUS_SHAPES:
        rows = [c for c in cases if c["shape"] == shape]
        if not rows:
            continue
        if shape == "filtered":
            accepted = [c for c in rows if c["selected"]]
            recovery = [c["recovery_rms_db"] for c in accepted]
            summary[shape] = {
                "n": len(rows),
                "true_positives": len(accepted),
                "rate": len(accepted) / len(rows),
                "interval": clopper_pearson(len(accepted), len(rows)),
                "median_recovery_rms_db": (
                    sorted(recovery)[len(recovery) // 2] if recovery else None
                ),
            }
        else:
            k = sum(c["false_acceptance"] for c in rows)
            summary[shape] = {
                "n": len(rows),
                "false_acceptances": k,
                "rate": k / len(rows),
                "interval": clopper_pearson(k, len(rows)),
            }
    gated = [c for c in cases if c["shape"] in CORPUS_GATED]
    k = sum(c["false_acceptance"] for c in gated)
    summary["gated_negatives"] = {
        "shapes": list(CORPUS_GATED),
        "n": len(gated),
        "false_acceptances": k,
        "rate": k / len(gated) if gated else None,
        "interval": clopper_pearson(k, len(gated)),
    }
    return summary


def _seeds(text: str) -> list[int]:
    out: list[int] = []
    for part in text.split(","):
        low, _, high = part.partition("-")
        out.extend(range(int(low), int(high or low) + 1))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", default="1-9", help="e.g. 1-9 or 1,4,7-12")
    parser.add_argument("--shapes", default=",".join(CORPUS_SHAPES))
    parser.add_argument("--duration", type=float, default=240.0, metavar="S")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2)
    )
    parser.add_argument(
        "--gate",
        type=float,
        default=0.10,
        help="max upper 95%% bound on gated false acceptances (stated preference)",
    )
    args = parser.parse_args()
    shapes = [s for s in args.shapes.split(",") if s]
    jobs = [
        (shape, seed, args.duration) for seed in _seeds(args.seeds) for shape in shapes
    ]
    print(f"{len(jobs)} cases on {args.workers} workers")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        cases = list(pool.map(_run_case, jobs))

    summary = summarise(cases)
    document = {
        "protocol": "negative-corpus-v1",
        "revision": record.revision(),
        "params": repr(PipelineParams()),
        "seeds": args.seeds,
        "duration_s": args.duration,
        "gate": args.gate,
        "summary": summary,
        "cases": cases,
    }
    args.output.write_text(json.dumps(document, indent=1, allow_nan=False) + "\n")

    print()
    for shape, row in summary.items():
        low, high = row["interval"]
        if shape == "filtered":
            print(
                f"  {shape:18s} true positives {row['true_positives']}/{row['n']} "
                f"[{low:.2f}, {high:.2f}]  median recovery {row['median_recovery_rms_db']} dB RMS"
            )
        else:
            print(
                f"  {shape:18s} false acceptances {row['false_acceptances']}/{row['n']} "
                f"[{low:.2f}, {high:.2f}]"
            )
    upper = summary["gated_negatives"]["interval"][1]
    verdict = "PASS" if upper <= args.gate else "FAIL"
    print(f"\n  gate: upper bound {upper:.3f} against {args.gate:.3f} -> {verdict}")
    return 0 if upper <= args.gate else 1


if __name__ == "__main__":
    sys.exit(main())
