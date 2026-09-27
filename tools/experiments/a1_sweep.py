#!/usr/bin/env python3
"""IMPROVEMENT_PLAN A1: which acceptance tolerances actually decide anything.

Acceptance runs after the fit and changes nothing upstream of it, so a tolerance sweep does not
need a single refit: collect every candidate once, then re-assess the same candidates under each
variant and re-run selection.

    uv run python tools/experiments/a1_sweep.py collect --out a1.pkl        # ~25 min, once
    uv run python tools/experiments/a1_sweep.py sweep a1.pkl                 # seconds

`collect` runs the negative corpus (every shape, seeds 1-9) with the texture blocker switched
*off*, recording separately whether it would have blocked each case, and re-judges the nine
real titles from their run records. Every candidate is kept whole, verified correction
included. `sweep` reports, for each tolerance at each multiple of its default, two views:
**as shipped** (a case the texture blocker stops is not accepted, whatever acceptance says)
and **acceptance alone** (the blocker ignored — what the tolerances contribute on their own).
Per view: gated false acceptances, natural-droop acceptances, injected filters recovered and
their median recovery error, and real titles whose accepted answer changes.
"""

import argparse
import dataclasses
import glob
import gzip
import json
import logging
import math
import os
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from beqforge import BiquadSpec  # noqa: E402
from beqforge.harness import CORPUS_GATED, CORPUS_SHAPES, corpus_case  # noqa: E402
from beqforge.pipeline import PipelineParams  # noqa: E402

OFF = 1e6
"""A multiple that switches a clause off. Finite, because `assess` rounds tolerances to its
decision quantum and infinity cannot be rounded."""

SWEPT = {
    # name: multiples of the default to try; OFF switches the clause off
    "level_tolerance_db": (0.5, 0.75, 1.0, 1.5, 2.0, OFF),
    "tilt_tolerance_db_per_octave": (0.5, 0.75, 1.0, 1.5, 2.0, OFF),
    "spread_margin_db": (0.25, 0.5, 1.0, 1.5, 2.0, OFF),
    "cliff_tolerance_db_per_octave": (0.25, 0.5, 1.0, 1.5, 2.0, OFF),
    "min_section_contribution_db": (0.0, 0.5, 1.0, 1.5, 2.0),
    "min_judge_octaves": (0.0, 0.5, 1.0, 1.5),
}


def _recovery_rms_db(filters, injected, params) -> float | None:
    """RMS departure of the published device from the injected filter's exact inverse."""
    from scipy import signal

    from beqforge.filters import (
        biquad_sos,
        high_pass_sos,
        magnitude_db,
        publication_filters,
    )

    if injected is None:
        return None
    freqs = np.geomspace(5, 2 * injected.corner_hz, 200)
    actual = magnitude_db(
        params.realisation.quantise(
            biquad_sos(publication_filters(filters), params.realisation.fs)
        ),
        freqs,
        params.realisation.fs,
    )
    _, transfer = signal.sosfreqz(high_pass_sos(injected, 1000), worN=freqs, fs=1000)
    inverse = -20 * np.log10(np.maximum(np.abs(transfer), 1e-30))
    return float(np.sqrt(np.mean((actual - inverse) ** 2)))


def _collect_corpus(job: tuple[str, int]) -> dict:
    shape, seed = job
    logging.disable(logging.WARNING)
    from beqforge import filters, pipeline

    filters.PARALLEL_FITS = False
    case = corpus_case(shape, seed)
    material = case.material()
    params = PipelineParams()
    texture = pipeline.passband_ripple_db(material, params)
    low_end = pipeline.low_end_deficit_db(material, params)
    texture_blocks = bool(
        texture is not None and low_end is not None and np.max(low_end) <= texture[0]
    )
    real_ripple = pipeline.passband_ripple_db
    pipeline.passband_ripple_db = lambda material, params: None
    try:
        report = pipeline.run(material, params)
    finally:
        pipeline.passband_ripple_db = real_ripple
    candidates = [
        dataclasses.replace(c, headroom=None, optimiser_filters=[])
        for c in report.candidates
    ]
    print(f"  {case.name}: {len(candidates)} candidate(s)", flush=True)
    return {
        "name": case.name,
        "shape": shape,
        "negative": case.negative,
        "texture_blocks": texture_blocks,
        "noise_floor_hz": report.diagnosis.noise_floor_hz
        if report.diagnosis
        else math.nan,
        "filter_floor_hz": report.diagnosis.filter_floor_hz
        if report.diagnosis
        else math.nan,
        "candidates": candidates,
        "recovery": {
            c.label: _recovery_rms_db(c.filters, case.injected, params)
            for c in candidates
        },
    }


def _collect_real(path: str) -> dict:
    logging.disable(logging.WARNING)
    from beqforge import pipeline
    from beqforge.material import load

    pipeline.measure_headroom = lambda material, filters, params, **_: (
        pipeline.Headroom(
            0.0, None, params.playback, params.realisation, float(material.fs), "a1"
        )
    )
    material = load(Path(path))
    params = PipelineParams()
    analysed = pipeline.analyse(
        material, params, Path(path).with_suffix(".cache.json.gz")
    )
    record_path = Path(path).with_name(Path(path).stem + ".run.json.gz")
    with gzip.open(record_path, "rt", encoding="utf-8") as handle:
        record = json.load(handle)
    candidates = []
    for recorded in record["candidates"]:
        up = recorded.get("unpriced_target_db")
        candidates.append(
            dataclasses.replace(
                pipeline._judge(
                    recorded["label"],
                    [BiquadSpec(**f) for f in recorded["filters"]],
                    np.asarray(recorded["target_db"], dtype=float),
                    float(recorded["fit_error_db"]),
                    material,
                    analysed.diagnosis,
                    analysed.params,
                    unpriced_target=None if up is None else np.asarray(up, dtype=float),
                    judged_band=analysed.judged_band_hz,
                ),
                headroom=None,
                optimiser_filters=[],
            )
        )
    print(f"  {record['material']['name']}: {len(candidates)} candidate(s)", flush=True)
    return {
        "name": record["material"]["name"],
        "shape": "real",
        "negative": None,
        "texture_blocks": bool(analysed.blockers),
        "noise_floor_hz": analysed.diagnosis.noise_floor_hz,
        "filter_floor_hz": analysed.diagnosis.filter_floor_hz,
        "candidates": candidates,
        "recovery": {},
    }


def collect(args: argparse.Namespace) -> int:
    corpus_jobs = [(shape, seed) for seed in range(1, 10) for shape in CORPUS_SHAPES]
    workers = args.workers or max(1, (os.cpu_count() or 2) - 2)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        cases = list(pool.map(_collect_corpus, corpus_jobs))
        cases += list(pool.map(_collect_real, sorted(glob.glob("data/*.npz"))))
    Path(args.out).write_bytes(pickle.dumps(cases))
    print(f"wrote {args.out}: {sum(len(c['candidates']) for c in cases)} candidates")
    return 0


def _selected(case: dict, accept) -> tuple[str | None, list]:
    """Re-assess every candidate under `accept` and re-run selection."""
    from beqforge import DESIGN_GRID
    from beqforge.accept import assess
    from beqforge.filters import correction_band_hz
    from beqforge.pipeline import FitStats, Report, Timings

    params = PipelineParams(accept=accept)
    rejudged = []
    for c in case["candidates"]:
        verdict = assess(
            c.filters,
            c.correction,
            case["noise_floor_hz"],
            accept,
            params.realisation,
            filter_floor_hz=case["filter_floor_hz"],
            required_offset_db=0.0,
            target_db=c.target_db,
            contribution_band_hz=correction_band_hz(
                c.target_db, DESIGN_GRID, params.lowest_frequency_hz
            ),
        )
        rejudged.append(dataclasses.replace(c, verdict=verdict))
    report = Report(None, None, None, rejudged, Timings(), FitStats(), accept=accept)
    chosen = report.accepted
    return (None if chosen is None else chosen.label), rejudged


def _score(cases: list[dict], accept, baseline: dict[str, str | None]) -> dict:
    out = {"shipped": {}, "alone": {}}
    for view in out:
        gated = droop = positives = found = 0
        recovery: list[float] = []
        changed: list[str] = []
        for case in cases:
            label, _ = _selected(case, accept)
            if view == "shipped" and case["texture_blocks"]:
                label = None
            if case["shape"] == "real":
                if label != baseline.get(case["name"]):
                    changed.append(
                        f"{case['name']}: {baseline.get(case['name'])} -> {label}"
                    )
                continue
            if case["shape"] in CORPUS_GATED:
                gated += label is not None
            elif case["shape"] == "natural_droop":
                droop += label is not None
            elif case["shape"] == "filtered":
                positives += 1
                if label is not None:
                    found += 1
                    recovery.append(case["recovery"][label])
        out[view] = {
            "gated_false_accepts": gated,
            "natural_droop_accepts": droop,
            "true_positives": f"{found}/{positives}",
            "median_recovery_db": round(float(np.median(recovery)), 2)
            if recovery
            else None,
            "real_changes": changed,
        }
    return out


def sweep(args: argparse.Namespace) -> int:
    from beqforge.accept import AcceptParams

    cases = pickle.loads(Path(args.collected).read_bytes())
    default = AcceptParams()
    baseline = {
        c["name"]: (None if c["texture_blocks"] else _selected(c, default)[0])
        for c in cases
        if c["shape"] == "real"
    }
    reference = _score(cases, default, baseline)
    print("default:", json.dumps(reference))
    results = {"default": reference, "sweeps": {}}
    for name, multiples in SWEPT.items():
        base = getattr(default, name)
        print(f"\n{name} (default {base:g})")
        rows = []
        for multiple in multiples:
            value = OFF if multiple == OFF else base * multiple
            scored = _score(
                cases, dataclasses.replace(default, **{name: value}), baseline
            )
            rows.append({"value": value, **scored})
            s, a = scored["shipped"], scored["alone"]
            print(
                f"  {'off' if multiple == OFF else f'{value:.3g}':>7s}  shipped: FA {s['gated_false_accepts']:2d}  droop "
                f"{s['natural_droop_accepts']}  TP {s['true_positives']}  rec "
                f"{s['median_recovery_db']}  real changes {len(s['real_changes'])}   | alone: "
                f"FA {a['gated_false_accepts']:2d}  droop {a['natural_droop_accepts']}  TP "
                f"{a['true_positives']}  rec {a['median_recovery_db']}"
                + (f"   {'; '.join(s['real_changes'])}" if s["real_changes"] else "")
            )
        results["sweeps"][name] = rows
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--out", required=True)
    c.add_argument("--workers", type=int, default=None)
    s = sub.add_parser("sweep")
    s.add_argument("collected")
    s.add_argument("--out")
    args = parser.parse_args()
    return collect(args) if args.command == "collect" else sweep(args)


if __name__ == "__main__":
    sys.exit(main())
