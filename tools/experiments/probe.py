#!/usr/bin/env python3
"""Regression probe: the decisions a change can move, without paying for a fit.

A full design run is 70-175 s a title, most of it the fitter. Most changes to decision logic
move something *before* the fit (plateau, floors, judged band, evidence ceiling, the priced
target) or *after* it (the verdict on a given cascade). This probe measures both halves
directly, so a nine-title regression pass costs seconds per title rather than minutes:

* **analysis** — the mix plateau, each channel's plateau and filtered flag, the level-invariance
  and tracking floors, the judged band, blockers, and the evidence ceiling's footprint. Read from
  the stage cache when it is valid, so a change outside `cache.ANALYSIS_MODULES` costs nothing
  here; a change inside it recomputes the analysis once and leaves it cached for a later run.
* **targets** — every strategy's priced target, summarised (peak, where, extent, a rounded
  digest). A digest that moves means the fitter would be handed something different, so the
  title needs a real run (`tools/design_beq.py`) before its verdict can be trusted.
* **rejudge** — every candidate in the title's existing run record, its *published* filters put
  back through the current `_judge`. Isolates changes to verification and acceptance from the
  fitter entirely. Judged against the recorded target, which is only meaningful while the
  target digest has not moved — the comparison says so when it has.

    uv run python tools/experiments/probe.py snapshot data/*.npz --out base.json
    ... change something ...
    uv run python tools/experiments/probe.py snapshot data/*.npz --out new.json
    uv run python tools/experiments/probe.py compare base.json new.json

`compare` exits 1 when anything moved, listing each change, and names the titles whose targets
moved and so need a full run. Titles run in parallel, one process each by default; none of this
fits, so the fitter's own pool is never started. About a minute for nine titles with a warm
analysis cache (the counterfactual target and each rejudge are several seconds apiece), plus
the analysis itself — 20-40 s a title — when a change invalidates it.
"""

import argparse
import gzip
import hashlib
import json
import logging
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from beqforge import DESIGN_GRID, BiquadSpec  # noqa: E402
from beqforge.diagnose import mean_spectrum, plateau_reference  # noqa: E402
from beqforge.filters import correction_band_hz  # noqa: E402
from beqforge.material import load  # noqa: E402
from beqforge import pipeline  # noqa: E402
from beqforge.pipeline import (  # noqa: E402
    Headroom,
    PipelineParams,
    _judge,
    analyse,
    judged_band_hz,
    propose,
)


def _num(value) -> float | None:
    value = float(value)
    return round(value, 6) if math.isfinite(value) else None


def _digest(values: np.ndarray) -> str:
    """Stable to the fourth decimal of a dB — below anything a verdict can turn on."""
    rounded = np.round(np.nan_to_num(np.asarray(values, dtype=float), nan=-999.0), 4)
    return hashlib.sha256(rounded.tobytes()).hexdigest()[:16]


def _target(target: np.ndarray | None, lowest_hz: float) -> dict | None:
    if target is None:
        return None
    target = np.asarray(target, dtype=float)
    peak = int(np.argmax(target))
    band = correction_band_hz(target, DESIGN_GRID, lowest_hz)
    return {
        "peak_db": _num(target[peak]),
        "peak_hz": _num(DESIGN_GRID[peak]),
        "band_hz": None if band is None else [_num(b) for b in band],
        "digest": _digest(target),
    }


def _no_headroom(material, filters, params, **_) -> Headroom:
    """Headroom is reported and never gated (`assess` only passes it through), and measuring
    it is ~80% of a judge — the 16x-interpolated peak over the whole programme."""
    return Headroom(
        0.0,
        None,
        params.playback,
        params.realisation,
        float(material.fs),
        "not measured by the regression probe",
    )


def snapshot_title(path: str, rejudge: bool = True) -> dict:
    started = time.perf_counter()
    try:
        out = _snapshot_title(path, rejudge)
    finally:
        print(f"  {Path(path).stem}: {time.perf_counter() - started:.1f} s", flush=True)
    return out


def _snapshot_title(path: str, rejudge: bool) -> dict:
    logging.disable(logging.WARNING)
    pipeline.measure_headroom = _no_headroom
    material_path = Path(path)
    material = load(material_path)
    params = PipelineParams()
    cache_path = material_path.with_suffix(".cache.json.gz")
    analysed = analyse(material, params, cache_path)
    params = analysed.params
    diagnosis = analysed.diagnosis
    envelopes = analysed.envelopes
    ceiling = envelopes.boost_ceiling(params.confidence_z)

    freqs, response = mean_spectrum(material.mono_mix, material.fs)
    level, region = plateau_reference(
        response, freqs, params.diagnose, params.exclude_bands_hz
    )
    out: dict = {
        "analysis": {
            "mix_plateau_hz": [_num(r) for r in region],
            "mix_plateau_db": _num(level),
            "filter_floor_hz": _num(diagnosis.filter_floor_hz),
            "noise_floor_hz": _num(diagnosis.noise_floor_hz),
            "judged_band_hz": (
                [_num(b) for b in judged_band_hz(material, diagnosis, params)]
                if math.isfinite(level)
                else None
            ),
            "blockers": list(analysed.blockers),
            "loud_frames": envelopes.loud_frames,
            "quiet_frames": envelopes.quiet_frames,
            "ceiling_bins_positive": int(np.sum(ceiling > 0)),
            "ceiling_max_db": _num(np.nanmax(ceiling)) if ceiling.size else None,
            "ceiling_digest": _digest(ceiling),
            "channels": {
                name: {
                    "plateau_hz": [_num(p) for p in channel.plateau_hz],
                    "is_filtered": bool(channel.is_filtered),
                    "max_slope": _num(channel.max_slope_db_per_octave),
                    "contrast_median_db": _num(np.nanmedian(channel.contrast_db)),
                }
                for name, channel in diagnosis.channels.items()
            },
        },
        "targets": {},
        "rejudge": {},
    }
    if analysed.blockers:
        return out

    for proposal in propose(material, analysed, cache_path):
        out["targets"][proposal.label] = _target(
            proposal.target_db, params.lowest_frequency_hz
        )

    record_path = material_path.with_name(material_path.stem + ".run.json.gz")
    if not rejudge or not record_path.exists():
        return out
    with gzip.open(record_path, "rt", encoding="utf-8") as handle:
        record = json.load(handle)
    for recorded in record["candidates"]:
        filters = [BiquadSpec(**f) for f in recorded["filters"]]
        target = np.asarray(recorded["target_db"], dtype=float)
        candidate = _judge(
            recorded["label"],
            filters,
            target,
            float(recorded["fit_error_db"]),
            material,
            diagnosis,
            params,
        )
        verdict = candidate.verdict
        out["rejudge"][recorded["label"]] = {
            "recorded_target_digest": _digest(target),
            "passed": bool(verdict.passed),
            "failures": list(verdict.failures),
            "band_hz": [_num(b) for b in candidate.correction.band_hz],
            "spread_db": _num(candidate.correction.spread_db),
            "tilt": _num(candidate.correction.tilt_db_per_octave),
            "recovered": None
            if verdict.recovered_fraction is None
            else _num(verdict.recovered_fraction),
            "shaping": None
            if verdict.shaping_fraction is None
            else _num(verdict.shaping_fraction),
        }
    return out


def snapshot(args: argparse.Namespace) -> int:
    paths = [str(p) for p in args.material]
    workers = args.workers or min(len(paths), max(1, (os.cpu_count() or 2) - 2))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        probed = pool.map(snapshot_title, paths, [not args.no_rejudge] * len(paths))
        results = dict(zip((Path(p).stem for p in paths), probed))
    Path(args.out).write_text(json.dumps(results, indent=1, sort_keys=True))
    print(f"wrote {args.out} ({len(results)} titles)")
    return 0


def _walk(a, b, path: str, out: list[str]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: added {b[key]!r}")
            elif key not in b:
                out.append(f"{path}.{key}: removed (was {a[key]!r})")
            else:
                _walk(a[key], b[key], f"{path}.{key}", out)
    elif a != b:
        out.append(f"{path}: {a!r} -> {b!r}")


def compare(args: argparse.Namespace) -> int:
    old = json.loads(Path(args.old).read_text())
    new = json.loads(Path(args.new).read_text())
    moved = False
    needs_run: list[str] = []
    for title in sorted(set(old) | set(new)):
        changes: list[str] = []
        _walk(old.get(title, {}), new.get(title, {}), "", changes)
        if not changes:
            print(f"{title}: unchanged")
            continue
        moved = True
        print(f"{title}: {len(changes)} change(s)")
        for change in changes:
            print(f"    {change}")
        targets_old = old.get(title, {}).get("targets", {})
        targets_new = new.get(title, {}).get("targets", {})
        if targets_old != targets_new:
            needs_run.append(title)
    if needs_run:
        print(
            "\ntargets moved — rejudge used the recorded target, so these need a real run: "
            + ", ".join(needs_run)
        )
    return 1 if moved else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="probe each title and write one JSON file")
    snap.add_argument("material", nargs="+", type=Path)
    snap.add_argument("--out", required=True)
    snap.add_argument(
        "--workers",
        type=int,
        default=None,
        help="default: one per title, cores permitting",
    )
    snap.add_argument(
        "--no-rejudge",
        action="store_true",
        help="analysis and targets only — for a change that cannot reach acceptance",
    )
    comp = sub.add_parser("compare", help="list what moved between two snapshots")
    comp.add_argument("old")
    comp.add_argument("new")
    args = parser.parse_args()
    return snapshot(args) if args.command == "snapshot" else compare(args)


if __name__ == "__main__":
    sys.exit(main())
