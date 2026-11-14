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

A selection or judging change need not refit at all. `snapshot --state DIR` keeps each title's
analysis, proposals and fits, and `rejudge` judges and chooses again from them with the current
code, writing the same snapshot format. The judgements are kept in the state too, so a change
to selection alone rejudges a title in about a second; set REFIT_REJUDGE_FRESH=1 when the
judge itself changed. A change to analysis, to a strategy or to the fitter needs a snapshot.

    uv run python tools/experiments/refit_probe.py snapshot ... --state DIR --out before.json.gz
    ... change selection or the judge ...
    uv run python tools/experiments/refit_probe.py rejudge ... --state DIR --out after.json.gz

REFIT_PERTURB_DB=0.004 (say) offsets every fit target by that much before it is quantised:
another machine's arithmetic, in effect, so the winners' spread across a few such snapshots is
the design's stability (TODO 32). A perturbation run, its zero included, bypasses the stage
cache, whose key cannot see the offset. The titles whose winner has ever moved under it are
few and steep; listing them slowest first keeps the last worker from setting the wall time.

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
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from beqforge import (
    filters,
    pipeline,
    record,
)
from beqforge.material import load
from beqforge.pipeline import (
    Headroom,
    PipelineParams,
    Report,
    _choose_fit,
    _fit_all,
    _judge,
    _lifts_beyond_goal,
    analyse,
    contrast_ceiling_db,
    overlift_allowance,
    propose,
)

MODES = {"default": False, "content_edge": True}
_QUANTISED = filters._quantised


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


def _perturbed(perturb: float) -> None:
    if perturb:
        # another machine's arithmetic, in effect: every target a few thousandths of a dB off
        # before it is quantised, so the spread under it is the fit's stability (TODO 32);
        # wrap the original, not the last title's wrapper: a worker runs several titles
        filters._quantised = lambda values: _QUANTISED(np.asarray(values) + perturb)
    else:
        filters._quantised = _QUANTISED


def _worker_setup() -> None:
    logging.disable(logging.WARNING)
    filters.PARALLEL_FITS = False
    pipeline.measure_headroom = _no_headroom


def snapshot_title(path: str, state_dir: str | None) -> dict:
    started = time.perf_counter()
    try:
        _worker_setup()
        material_path = Path(path)
        state = _fit_state(material_path)
        result = _judge_state(load(material_path), state)
        if state_dir is not None:
            _save_state(Path(state_dir), material_path, state)
        return result
    finally:
        print(f"  {Path(path).stem}: {time.perf_counter() - started:.1f} s", flush=True)


def rejudge_title(path: str, state_dir: str) -> dict:
    started = time.perf_counter()
    try:
        _worker_setup()
        material_path = Path(path)
        state = _load_state(Path(state_dir), material_path)
        known = len(state.get("judged", {}))
        result = _judge_state(load(material_path), state)
        if len(state.get("judged", {})) != known:
            # keep the judgements made here, so the next rejudge reuses them
            _save_state(Path(state_dir), material_path, state)
        return result
    finally:
        print(f"  {Path(path).stem}: {time.perf_counter() - started:.1f} s", flush=True)


def _state_path(state_dir: Path, material_path: Path) -> Path:
    return state_dir / f"{material_path.stem}.pickle.gz"


def _save_state(state_dir: Path, material_path: Path, state: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(_state_path(state_dir, material_path), "wb") as handle:
        pickle.dump(state, handle)


def _load_state(state_dir: Path, material_path: Path) -> dict:
    with gzip.open(_state_path(state_dir, material_path), "rb") as handle:
        return pickle.load(handle)


def _fit_state(material_path: Path) -> dict:
    """Everything a title's judging needs that costs a fit: analysis, proposals, first fits."""
    perturb = float(os.environ.get("REFIT_PERTURB_DB", "0"))
    _perturbed(perturb)
    material = load(material_path)
    # the stage cache's key does not see the perturbation: a cached proposal is whichever run
    # wrote it last, so a perturbation study (its zero included) reads and writes nothing
    cache_path = (
        None
        if "REFIT_PERTURB_DB" in os.environ
        else material_path.with_suffix(".cache.json.gz")
    )
    analysed = {
        mode: analyse(
            material, PipelineParams(judge_from_content_edge=edge), cache_path
        )
        for mode, edge in MODES.items()
    }
    base = analysed["default"]
    state = {"perturb": perturb, "analysed": analysed}
    if base.blockers:
        return state
    proposals = propose(material, base, cache_path)
    needs_fitting = [p for p in proposals if p.filters is None]
    allowance = overlift_allowance(material, base.params, base.judged_band_hz)
    state |= {
        "proposals": proposals,
        "fitted": dict(
            zip(
                [p.label for p in needs_fitting],
                _fit_all(needs_fitting, base.params, allowance)
                if needs_fitting
                else [],
                strict=True,
            )
        ),
    }
    return state


def _judge_state(material, state: dict) -> dict:
    """Judge each fit and choose among them with the current code; no fitting."""
    analysed = state["analysed"]
    base = analysed["default"]
    if base.blockers:
        return {"blockers": list(base.blockers), "candidates": [], "accepted": {}}
    proposals, fitted = state["proposals"], state["fitted"]
    # a selection change reuses every judgement; REFIT_REJUDGE_FRESH=1 when the judge changed
    if os.environ.get("REFIT_REJUDGE_FRESH") or "judged" not in state:
        state["judged"] = {}
    judged: dict[tuple, object] = state["judged"]
    chosen: dict[str, list] = {}
    for mode in MODES:
        run = analysed[mode]

        def finish(proposal, answer, options, run=run):
            def judge(cascade, error, measured):
                key = (
                    run.params.judge_from_content_edge,
                    proposal.label,
                    tuple(tuple(_spec(s)) for s in cascade),
                    float(error),
                    bool(measured),
                )
                if key not in judged:
                    judged[key] = judged_afresh(cascade, error, measured)
                return judged[key]

            def judged_afresh(cascade, error, measured):
                return _judge(
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
                    measured=measured,
                )

            # the pipeline's choice among near-equal fits, which the judging mode can change
            return _choose_fit(
                answer,
                options,
                judge,
                lambda c: _lifts_beyond_goal(c, run.params),
            )

        chosen[mode] = [
            finish(
                proposal, answer := (proposal.filters, proposal.residual_db), [answer]
            )
            if proposal.filters is not None
            else finish(proposal, *fitted[proposal.label])
            for proposal in proposals
        ]

    candidates = []
    for index, proposal in enumerate(proposals):
        entry = {"label": proposal.label}
        for mode in MODES:
            run = analysed[mode]
            candidate = chosen[mode][index]
            if mode == "default":
                entry["filters"] = [_spec(s) for s in candidate.filters]
                entry["fit_error_db"] = candidate.fit_error_db
            entry[mode] = {
                "passed": bool(candidate.verdict.passed),
                "failures": list(candidate.verdict.failures),
                "margins": dict(candidate.verdict.margins),
                "departure_db": candidate.correction.departure_db(
                    run.params.accept.target_tilt_db_per_octave
                ),
            }
            if mode == "default":
                # the curves are the default mode's, kept once, for `records`
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


def _run(paths: list[str], work, extra, workers: int | None, out: str) -> int:
    workers = workers or min(len(paths), max(1, (os.cpu_count() or 2) - 2))
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = dict(
            zip(
                (Path(p).stem for p in paths),
                pool.map(work, paths, [extra] * len(paths)),
            )
        )
    with gzip.open(out, "wt", encoding="utf-8") as handle:
        json.dump(results, handle)
    print(
        f"wrote {out} ({len(results)} titles, {workers} workers, "
        f"{time.perf_counter() - started:.0f} s)"
    )
    return 0


def snapshot(args: argparse.Namespace) -> int:
    return _run(
        [str(p) for p in args.material],
        snapshot_title,
        None if args.state is None else str(args.state),
        args.workers,
        args.out,
    )


def rejudge(args: argparse.Namespace) -> int:
    return _run(
        [str(p) for p in args.material],
        rejudge_title,
        str(args.state),
        args.workers,
        args.out,
    )


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
    snap.add_argument(
        "--state",
        type=Path,
        default=None,
        help="keep each title's fits here for rejudge",
    )
    again = sub.add_parser(
        "rejudge", help="judge and choose again from a snapshot's kept fits; no refit"
    )
    again.add_argument("material", nargs="+", type=Path)
    again.add_argument("--state", type=Path, required=True)
    again.add_argument("--out", required=True)
    again.add_argument(
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
    return {
        "snapshot": snapshot,
        "rejudge": rejudge,
        "compare": compare,
        "records": records,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
