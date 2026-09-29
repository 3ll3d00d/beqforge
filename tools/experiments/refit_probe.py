#!/usr/bin/env python3
"""Fit-only regression probe: refit every title's proposals, judge them in both modes.

For a change to the fitter or to fit selection, which `probe.py` cannot see (it rejudges the
*recorded* filters). A real `design_beq.py` run per title per mode costs 60-100 s; this refits
each title once, from the cached analysis, and judges every cascade with and without
`--content-edge` — the fits do not depend on that option, only the judging does. Headroom is
skipped, as in `probe.py`: it is never gated and is most of a judge's cost. Titles run in
parallel, one process each with serial fitting, which uses the cores better than one title at
a time with a fitting pool.

    uv run python tools/experiments/refit_probe.py snapshot data/*.npz data/variants/*.npz \\
        --out before.json.gz
    ... change the fitter ...
    uv run python tools/experiments/refit_probe.py snapshot ... --out after.json.gz
    uv run python tools/experiments/refit_probe.py compare before.json.gz after.json.gz
    uv run python tools/experiments/refit_probe.py records after.json.gz DIR [--content-edge]

`compare` lists, per title, every candidate whose published cascade moved, every verdict that
flipped in either mode, and every change of winner, and exits 1 when anything moved. `records`
writes minimal run records (the accepted label and each candidate's correction and verdict) so
`score_injected.py --records DIR` can score a changed winner against an injection's truth.

Snapshots are only comparable with snapshots: fitting serially rather than in a pool, and
without headroom, they are not byte-for-byte a `design_beq.py` record. A snapshot of committed
code is reusable for every change made on top of it until something that decides anything
lands.
"""

import argparse
import gzip
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from beqforge import filters  # noqa: E402
from beqforge import pipeline, record  # noqa: E402
from beqforge.filters import publication_filters  # noqa: E402
from beqforge.material import load  # noqa: E402
from beqforge.pipeline import (  # noqa: E402
    Headroom,
    PipelineParams,
    Report,
    _fit_all,
    _judge,
    analyse,
    contrast_ceiling_db,
    propose,
)

MODES = {"default": False, "content_edge": True}


def _no_headroom(material, filters, params, **_) -> Headroom:
    return Headroom(
        0.0,
        None,
        params.playback,
        params.realisation,
        float(material.fs),
        "not measured by the refit probe",
    )


def _spec(section) -> list:
    return [section.type, section.freq_hz, section.gain_db, section.q]


def _accepted(candidates: list[dict], mode: str, accept) -> str | None:
    """`Report.accepted` itself, over the stored verdicts, so selection cannot drift from it."""
    stand_ins = [
        SimpleNamespace(
            label=c["label"],
            filters=c["filters"],
            verdict=SimpleNamespace(passed=c[mode]["passed"]),
            correction=SimpleNamespace(
                departure_db=lambda _tilt, d=c[mode]["departure_db"]: d
            ),
        )
        for c in candidates
    ]
    report = SimpleNamespace(
        candidates=stand_ins,
        accept=accept,
        ranking_tie_db=Report.__dataclass_fields__["ranking_tie_db"].default,
    )
    chosen = Report.accepted.fget(report)
    return None if chosen is None else chosen.label


def snapshot_title(path: str) -> dict:
    started = time.perf_counter()
    try:
        return _snapshot_title(Path(path))
    finally:
        print(f"  {Path(path).stem}: {time.perf_counter() - started:.1f} s", flush=True)


def _snapshot_title(material_path: Path) -> dict:
    logging.disable(logging.WARNING)
    filters.PARALLEL_FITS = False
    pipeline.measure_headroom = _no_headroom
    material = load(material_path)
    cache_path = material_path.with_suffix(".cache.json.gz")
    analysed = {
        mode: analyse(
            material, PipelineParams(judge_from_content_edge=edge), cache_path
        )
        for mode, edge in MODES.items()
    }
    base = analysed["default"]
    if base.blockers:
        return {"blockers": list(base.blockers), "candidates": [], "accepted": {}}
    proposals = propose(material, base, cache_path)
    needs_fitting = [p for p in proposals if p.filters is None]
    fitted = dict(
        zip(
            [p.label for p in needs_fitting],
            _fit_all(needs_fitting, base.params) if needs_fitting else [],
            strict=True,
        )
    )
    candidates = []
    for proposal in proposals:
        if proposal.filters is not None:
            cascade, error = proposal.filters, proposal.residual_db
        else:
            cascade, error = fitted[proposal.label]
        entry = {
            "label": proposal.label,
            "filters": [_spec(s) for s in publication_filters(cascade)],
            "fit_error_db": error,
        }
        for mode in MODES:
            run = analysed[mode]
            candidate = _judge(
                proposal.label,
                cascade,
                proposal.target_db,
                error,
                material,
                run.diagnosis,
                run.params,
                proposal.notes,
                unpriced_target=proposal.unpriced_target_db,
                method=proposal.method,
                judged_band=run.judged_band_hz,
                ceiling_db=(
                    contrast_ceiling_db(run.envelopes, run.params)
                    if run.params.judge_from_content_edge
                    else None
                ),
            )
            entry[mode] = {
                "passed": bool(candidate.verdict.passed),
                "failures": list(candidate.verdict.failures),
                "departure_db": candidate.correction.departure_db(
                    run.params.accept.target_tilt_db_per_octave
                ),
            }
            if mode == "default":
                # the curves do not depend on the mode; kept once, for `records`
                entry["record"] = record._candidate(candidate)
        candidates.append(entry)
    return {
        "blockers": [],
        "candidates": candidates,
        "accepted": {
            mode: _accepted(candidates, mode, analysed[mode].params.accept)
            for mode in MODES
        },
    }


def snapshot(args: argparse.Namespace) -> int:
    paths = [str(p) for p in args.material]
    workers = args.workers or min(len(paths), max(1, (os.cpu_count() or 2) - 2))
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = dict(
            zip((Path(p).stem for p in paths), pool.map(snapshot_title, paths))
        )
    with gzip.open(args.out, "wt", encoding="utf-8") as handle:
        json.dump(results, handle)
    print(
        f"wrote {args.out} ({len(results)} titles, {workers} workers, "
        f"{time.perf_counter() - started:.0f} s)"
    )
    return 0


def _load(path: str) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def compare(args: argparse.Namespace) -> int:
    old, new = _load(args.old), _load(args.new)
    moved = 0
    for title in sorted(set(old) | set(new)):
        if title not in old or title not in new:
            print(f"{title}: only in {'new' if title in new else 'old'}")
            moved += 1
            continue
        a, b = old[title], new[title]
        lines = []
        if a["blockers"] != b["blockers"]:
            lines.append(f"blockers {a['blockers']} -> {b['blockers']}")
        before = {c["label"]: c for c in a["candidates"]}
        after = {c["label"]: c for c in b["candidates"]}
        for label in sorted(set(before) | set(after)):
            if label not in before or label not in after:
                lines.append(f"{label}: only in {'new' if label in after else 'old'}")
                continue
            x, y = before[label], after[label]
            if x["filters"] != y["filters"]:
                lines.append(
                    f"{label}: cascade {len(x['filters'])} -> {len(y['filters'])} "
                    f"section(s), fit {x['fit_error_db']:.3f} -> {y['fit_error_db']:.3f} dB"
                )
            for mode in MODES:
                if x[mode]["passed"] != y[mode]["passed"]:
                    why = (
                        y[mode]["failures"]
                        if x[mode]["passed"]
                        else x[mode]["failures"]
                    )
                    lines.append(
                        f"{label} [{mode}]: "
                        f"{'passes -> fails' if x[mode]['passed'] else 'fails -> passes'}"
                        f"  ({'; '.join(why)[:160]})"
                    )
        for mode in MODES:
            if a["accepted"].get(mode) != b["accepted"].get(mode):
                lines.append(
                    f"WINNER [{mode}]: {a['accepted'].get(mode)} -> "
                    f"{b['accepted'].get(mode)}"
                )
        if lines:
            moved += 1
            print(title)
            for line in lines:
                print(f"    {line}")
    print(f"{moved} of {len(set(old) | set(new))} titles moved")
    return 1 if moved else 0


def records(args: argparse.Namespace) -> int:
    snap = _load(args.snapshot)
    mode = "content_edge" if args.content_edge else "default"
    out = Path(args.directory)
    out.mkdir(parents=True, exist_ok=True)
    for title, result in snap.items():
        written = []
        for c in result["candidates"]:
            entry = dict(c["record"])
            entry["verdict"] = {**entry["verdict"], **c[mode]}
            written.append(entry)
        with gzip.open(out / f"{title}.run.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(
                {"accepted": result["accepted"].get(mode), "candidates": written},
                handle,
            )
    print(f"wrote {len(snap)} minimal records ({mode}) to {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="refit and judge each title; one JSON file")
    snap.add_argument("material", nargs="+", type=Path)
    snap.add_argument("--out", required=True)
    snap.add_argument(
        "--workers", type=int, default=None, help="titles at once (default: cores - 2)"
    )
    comp = sub.add_parser("compare", help="list what moved between two snapshots")
    comp.add_argument("old")
    comp.add_argument("new")
    rec = sub.add_parser("records", help="minimal run records for score_injected.py")
    rec.add_argument("snapshot")
    rec.add_argument("directory")
    rec.add_argument("--content-edge", action="store_true")
    args = parser.parse_args()
    return {"snapshot": snapshot, "compare": compare, "records": records}[args.command](
        args
    )


if __name__ == "__main__":
    sys.exit(main())
