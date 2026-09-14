#!/usr/bin/env python3
"""Design a BEQ filter from extracted material, and show the working.

    uv run python tools/design_beq.py data/FILM.npz

Runs the process of AUTOMATED_DESIGN.md §6.4 end to end — per-channel decomposition, target
derivation, candidate designs, acceptance — and prints the evidence alongside the answer. The
commentary is the point: a residual says a cascade matched the target it was handed, never
that the target was right, so a result without its reasoning is not a result.

Writes nothing. Add `--exclude LOW HIGH` for an authored feature that should not be treated
as shape (still manual; §3.1).
"""

import argparse
import logging
import math
import sys
from pathlib import Path

import numpy as np

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqanalyser.design.material import load  # noqa: E402
from beqanalyser.design.pipeline import (  # noqa: E402
    STRATEGIES,
    PipelineParams,
    Report,
    run,
)

RULE = "=" * 78
DECADES = (5, 8, 10, 13, 16, 20, 25, 31, 40, 50, 63)


def _row(label: str, values: list[str]) -> str:
    return f"  {label:<14s}" + "".join(f"{v:>8s}" for v in values)


def _at(freqs: np.ndarray, values: np.ndarray, points=DECADES) -> list[str]:
    return [f"{np.interp(p, freqs, values):.1f}" for p in points]


def show_channels(report: Report) -> None:
    d = report.diagnosis
    print(RULE)
    print("PER-CHANNEL DECOMPOSITION")
    print(
        "\n  Plateau each channel's response is referenced to — derived per channel per"
    )
    print(
        "  title, never a fixed band (§2.1). Width is what to watch: a reference resting"
    )
    print("  on well under an octave is resting on very little.")
    for name, channel in d.channels.items():
        low, high = channel.plateau_hz
        octaves = math.log2(high / low) if low > 0.0 else math.nan
        flag = "  <- narrow" if octaves < 1.0 else ""
        print(
            f"    {name:<5s}{low:7.1f} - {high:6.1f} Hz  ({octaves:4.2f} octaves, "
            f"knee {channel.max_slope_hz:5.1f} Hz){flag}"
        )
    print("\n  Response in dB relative to each channel's own plateau:")
    print(_row("Hz", [str(p) for p in DECADES]))
    for name, channel in d.channels.items():
        print(_row(name, _at(d.freqs, channel.response_db)))
    print("\n  Share of summed-mix power, %:")
    print(_row("Hz", [str(p) for p in DECADES]))
    for name, channel in d.channels.items():
        print(_row(name, _at(d.freqs, channel.share * 100.0)))
    print()
    for channel in d.channels.values():
        print(f"  {channel}")
    if not d.filtered_channels:
        print("\n  No channel shows a knee — the sum is the only available evidence.")
        return
    print(f"\n  Filtered: {', '.join(d.filtered_channels)}")


def show_floors(report: Report) -> None:
    d = report.diagnosis
    if not d.stratified:
        return
    print(RULE)
    print("LEVEL INDEPENDENCE  (R2 — a filter's relative shape cannot vary with level)")
    print(_row("Hz", [str(p) for p in DECADES]))
    for label, response in d.stratified.items():
        print(_row(label, _at(d.freqs, response)))
    if d.level_spread_db is not None:
        print(_row("spread", _at(d.freqs, d.level_spread_db)))
    subject = max(d.channels, key=lambda n: d.channels[n].passband_share)
    low, high = d.channels[subject].plateau_hz
    print(
        f"\n  Measured on {subject}, referenced to its {low:.1f}-{high:.1f} Hz plateau."
    )
    print(
        f"  Level-independent down to {d.filter_floor_hz:.1f} Hz — below that the "
        "attenuation\n  is not a fixed filter, so inverting it is shaping, not identification."
    )
    floor = d.noise_floor_hz
    print(
        "  Programme-correlated content continues to "
        + ("the bottom of the band." if np.isnan(floor) else f"{floor:.1f} Hz.")
        + "  (R1's terminus)"
    )


def show_identification(report: Report) -> None:
    print(RULE)
    print("IDENTIFICATION")
    if report.identification is None:
        print("  Sum-based: unavailable.")
    else:
        print(f"  Sum-based: {report.identification}")
    if report.diagnosis.filtered_channels:
        print(
            "\n  A channel carries the rolloff, so the sum-based figure is reported for\n"
            "  comparison only — where the two disagree the sum is the one that cannot\n"
            "  see the filter (§3.1)."
        )


def _headroom(offset_db: float) -> str:
    if math.isnan(offset_db):
        return "gain reduction unavailable (no channel decomposition)"
    if offset_db >= 0.0:
        return "no gain reduction needed"
    return f"needs {-offset_db:.1f} dB of gain reduction"


def show_candidates(report: Report) -> None:
    print(RULE)
    print("CANDIDATES  (one per target strategy; all judged the same way)")
    if not report.candidates:
        print("  None generated.")
        return
    for candidate in report.candidates:
        c = candidate.correction
        v = candidate.verdict
        print(
            f"\n  {candidate.label}  ({len(candidate.filters)} sections, "
            f"fit error {candidate.fit_error_db:.2f} dB)"
        )
        for section in candidate.filters:
            print(
                f"      {section.type:<11s} {section.freq_hz:7.2f} Hz "
                f"{section.gain_db:+7.2f} dB  Q {section.q:.3f}"
            )
        print(
            f"      corrected: spread {c.spread_db:5.2f}  tilt {c.tilt_db_per_octave:+5.2f}"
            f"  level {c.level_db:+5.2f}  extent {v.extent_hz:.1f} Hz"
        )
        print(
            f"      cliff: {v.worst_gradient_before:.1f} -> {v.worst_gradient_after:.1f} "
            f"dB/oct   turnover: {v.turnover_before:.1f} -> {v.turnover_after:.1f} dB/oct"
            f"   wobble {v.wobble_db:.2f} vs {v.roughness_db:.2f}"
        )
        print(
            f"      device: {v.device_error_db:.2f} dB of rounding error, tightest section has "
            f"{v.dc_margin_steps:.1f} steps of DC headroom (drift p90 {v.drift_db:.2f} dB)"
            f"   clipping: {_headroom(v.required_offset_db)}"
        )
        recovered = (
            "n/a"
            if math.isnan(v.recovered_fraction)
            else f"{v.recovered_fraction * 100:.0f}%"
        )
        print(
            f"      recovered {recovered} of the measured deficit "
            f"(§14.1)   confidence {candidate.confidence:.2f} (§14.3)"
        )
        print(f"      {v}")
        for note in (*candidate.target_notes, *v.notes):
            print(f"      note: {note}")


def show_result(report: Report) -> None:
    print(RULE)
    print("RESULT")
    accepted = report.accepted
    for note in report.evidence_notes:
        print(f"  {note}")
    if accepted is None:
        print("\n  No candidate passed. Abstaining is the correct output here (§2.5);")
        print("  the failures above say what would have to change.\n")
        return
    offset = accepted.verdict.required_offset_db
    recovered_fraction = accepted.verdict.recovered_fraction
    recovered = (
        "n/a" if math.isnan(recovered_fraction) else f"{recovered_fraction * 100:.0f}%"
    )
    print(
        f"\n  {accepted.label}    peak boost {accepted.mv_adjust_db:+.1f} dB, "
        + _headroom(offset)
        + f"\n  recovered {recovered} of the measured deficit, "
        f"confidence {accepted.confidence:.2f}\n"
    )
    for section in accepted.filters:
        print(
            f"      {section.type:<11s} {section.freq_hz:7.2f} Hz "
            f"{section.gain_db:+7.2f} dB  Q {section.q:.3f}"
        )
    c = accepted.correction
    print(f"\n  Corrected low end over {c.band_hz[0]:g}-{c.band_hz[1]:g} Hz:")
    print(_row("Hz", [str(p) for p in DECADES]))
    print(_row("before", _at(c.freqs, c.before_db)))
    print(_row("after", _at(c.freqs, c.after_db)))
    print()


def show_cost(report: Report) -> None:
    print(RULE)
    print("COST")
    total = report.timings.total_s
    print(f"\n  {report.timings.total_s:.1f} s total\n")
    for label, seconds in report.timings.stages:
        share = 100.0 * seconds / total if total else 0.0
        bar = "#" * int(round(share / 2.0))
        print(f"  {label:<18s}{seconds:8.1f} s {share:5.1f}%  {bar}")
    print(f"\n  fitting: {report.fit_stats}")
    print(
        "\n  Optimiser runs are seeds * M * (M + 1) / 2 per candidate, for M sections —\n"
        "  raising max_sections by one is not a linear cost."
    )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("material", type=Path)
    parser.add_argument(
        "--exclude",
        nargs=2,
        type=float,
        action="append",
        metavar=("LOW", "HIGH"),
        help="authored feature to drop, in Hz; repeatable",
    )
    parser.add_argument(
        "--strategy",
        action="append",
        metavar="NAME",
        help=(
            "target-derivation strategy to run; repeatable. "
            f"One of {', '.join(sorted(STRATEGIES))}, or 'all'. Default: all"
        ),
    )
    parser.add_argument(
        "--charts",
        type=Path,
        metavar="DIR",
        help="write peak-vs-average charts per candidate into DIR",
    )
    parser.add_argument(
        "--record",
        type=Path,
        metavar="PATH",
        help="where to write the run record (default: alongside the material)",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="skip the run record; charts then need a rerun to redraw",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        metavar="PATH",
        help="where to keep the stage cache (default: alongside the material)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="recompute every cached stage and overwrite what is stored",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="neither read nor write the stage cache",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="report only, no progress log"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s"
    )
    chosen = args.strategy or ["all"]
    if "all" in chosen:
        strategies = tuple(STRATEGIES)
    else:
        unknown = [s for s in chosen if s not in STRATEGIES]
        if unknown:
            parser.error(
                f"unknown strategy {', '.join(unknown)}; "
                f"have {', '.join(sorted(STRATEGIES))}"
            )
        strategies = tuple(chosen)
    params = PipelineParams(
        strategies=strategies,
        exclude_bands_hz=tuple(tuple(b) for b in (args.exclude or ())),  # type: ignore[misc]
    )
    material = load(args.material)
    cache_path = (
        None
        if args.no_cache
        else (args.cache or args.material.with_suffix(".cache.json.gz"))
    )
    report = run(material, params, cache_path=cache_path, fresh=args.fresh)

    relevant = [
        name
        for name, channel in report.diagnosis.channels.items()
        if channel.passband_share >= params.diagnose.min_passband_share
    ]
    if args.charts:
        from beqanalyser.design.charts import render

        out = args.charts / material.name
        for candidate in report.candidates:
            render(candidate.label, candidate.filters, material, relevant, out)
        print(f"\n  charts written to {out}/")

    if not args.no_record:
        from beqanalyser.design import record

        curves = record.curves_from(
            material,
            {c.label: c.filters for c in report.candidates},
            relevant,
        )
        destination = args.record or args.material.with_suffix(".run.json.gz")
        record.write(destination, report, params, args.material, curves)
        print(f"  run record written to {destination}")

    print()
    show_channels(report)
    show_floors(report)
    show_identification(report)
    show_candidates(report)
    show_result(report)
    show_cost(report)
    return 0 if report.accepted is not None else 1


if __name__ == "__main__":
    sys.exit(main())
