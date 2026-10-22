#!/usr/bin/env python3
"""E10's real-texture families: the title partition, and the cases built on it (TODO 3).

    uv run python tools/e10_cases.py freeze --library /media/beq/work --out plans/e10-titles-v1.json
    uv run python tools/e10_cases.py run --titles plans/e10-titles-v1.json --partition development \\
        --limit 3 --goals flat --output e10_real_dev.json

`freeze` lists every library title with a multichannel extraction, puts every title already
used in development (named in `plans/`, `TODO.md`, the triage ledger or findings, or the baseline
set) in the development partition, and draws the held-out titles from the rest with the
protocol's seed. Only names are written; the audio stays where it is.

`run` designs each title as it is and with each recipe (plans/E10-validation-protocol.md,
"Real-texture families"), and scores each recipe against the same title's as-is design, so
the title's own unknown mastering cancels:

* `injected_rolloff`: what the design adds over the as-is one, against the injected filter's
  inverse, where the as-is run tracked programme and the filter leaves it within 40 dB.
* `noise_replaced`: the programme below a corner removed by a 16th-order high-pass and a pink
  floor added 50 dB under the channel; any boost over 3 dB half an octave below the corner,
  where only that floor is left, is noise lift.
* `excerpt`: 20% and 50% of the programme, marked as excerpts; any selection is unnecessary.
"""

import argparse
import json
import logging
import math
import re
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqforge import Alignment, HighPass, e10, record  # noqa: E402
from beqforge.harness import apply_high_pass  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = Path("/media/beq/work")
TRIAGE = Path("/media/beq/triage")
HELD_OUT_TITLES = 60
TITLE_SEED = 10
CORNER_LIMIT_DB = 40.0
NOISE_DOWN_DB = 50.0


def _base(directory: str) -> str:
    """'Fame (1980) - audio 1' -> 'Fame'; the name prose and ledgers use."""
    name = re.sub(r" - audio \d+$", "", directory)
    return re.sub(r"\s*\(\d{4}\)$", "", name).strip()


def _library_titles(library: Path) -> list[str]:
    return sorted(
        d.name
        for d in library.iterdir()
        if (d / "multichannel.wav").is_file() and (d / "manifest.json").is_file()
    )


def _development_text() -> str:
    parts = [p.read_text(errors="replace") for p in (ROOT / "plans").glob("*.md")]
    parts.append((ROOT / "TODO.md").read_text(errors="replace"))
    for name in ("ledger.jsonl", "findings.md", "STATUS.md"):
        path = TRIAGE / name
        if path.is_file():
            parts.append(path.read_text(errors="replace"))
    parts.extend(p.stem.replace("_", " ") for p in (ROOT / "data").glob("*.npz"))
    return "\n".join(parts)


def freeze(library: Path, out: Path) -> None:
    titles = _library_titles(library)
    text = _development_text()

    def mentioned(directory: str) -> bool:
        base = _base(directory)
        return bool(re.search(rf"(?<!\w){re.escape(base)}(?!\w)", text, re.IGNORECASE))

    development = [t for t in titles if mentioned(t)]
    rest = [t for t in titles if not mentioned(t)]
    rng = np.random.default_rng(TITLE_SEED)
    held_out = sorted(
        rng.choice(rest, size=min(HELD_OUT_TITLES, len(rest)), replace=False).tolist()
    )
    document = {
        "protocol": e10.PROTOCOL_VERSION,
        "seed": TITLE_SEED,
        "library_titles": len(titles),
        "development": development,
        "held_out": held_out,
    }
    out.write_text(json.dumps(document, indent=1) + "\n")
    print(
        f"{len(titles)} titles: {len(development)} development, {len(rest)} unused, "
        f"{len(held_out)} held out -> {out}"
    )


# ---- cases -----------------------------------------------------------------------------


def load(directory: Path):
    import soundfile

    from beqforge.material import Material
    from tools.extract import LAYOUTS

    manifest = json.loads((directory / "manifest.json").read_text())
    names = LAYOUTS.get(manifest.get("channel_layout_name", ""))
    samples, fs = soundfile.read(directory / "multichannel.wav", dtype="float64")
    samples = np.atleast_2d(samples.T)
    if names is None or len(names) != samples.shape[0]:
        raise ValueError(
            f"{directory.name}: no known layout for {samples.shape[0]} channels"
        )
    channels = {name: np.ascontiguousarray(samples[i]) for i, name in enumerate(names)}
    mono, _ = soundfile.read(directory / "mono.wav", dtype="float64")
    return Material(
        _base(directory.name), int(fs), mono, channels, "complete_programme"
    )


def _with_channels(
    material, channels: dict, name: str, coverage: str = "complete_programme"
):
    from beqforge.material import LFE_GAIN, MAIN_GAIN, Material

    mono = sum(
        (LFE_GAIN if n == "LFE" else MAIN_GAIN) * samples
        for n, samples in channels.items()
    )
    return Material(name, material.fs, mono, channels, coverage)


def recipes(material, index: int) -> list[tuple[str, object, dict]]:
    """Each recipe's material and what it did, drawn from the title's place in the list."""
    rng = np.random.default_rng((TITLE_SEED, index))
    alignment = (
        Alignment.LINKWITZ_RILEY if rng.random() < 0.5 else Alignment.BUTTERWORTH
    )
    orders = (
        (2, 4, 8, 12, 16)
        if alignment == Alignment.LINKWITZ_RILEY
        else (2, 3, 4, 8, 12, 16)
    )
    hp = HighPass(
        alignment,
        int(rng.choice(orders)),
        float(np.exp(rng.uniform(np.log(15), np.log(40)))),
    )
    subset = rng.random() < 0.3
    touched = (
        ["LFE"] if subset and "LFE" in material.channels else list(material.channels)
    )
    injected = {
        n: apply_high_pass(s, hp, material.fs) if n in touched else s
        for n, s in material.channels.items()
    }
    corner = float(rng.uniform(25.0, 50.0))
    wall = HighPass(Alignment.BUTTERWORTH, 16, corner)
    replaced = {}
    for n, s in material.channels.items():
        floor = e10._shaped_noise(rng, len(s), "pink", material.fs)
        floor *= float(np.std(s)) * 10.0 ** (-NOISE_DOWN_DB / 20.0)
        replaced[n] = apply_high_pass(s, wall, material.fs) + floor
    out = [
        (
            "injected_rolloff",
            _with_channels(material, injected, f"{material.name}/injected"),
            {"injected": str(hp), "channels": touched, "hp": hp},
        ),
        (
            "noise_replaced",
            _with_channels(material, replaced, f"{material.name}/noise_replaced"),
            {"corner_hz": round(corner, 1)},
        ),
    ]
    for share in (0.2, 0.5):
        n = len(material.mono_mix)
        start = int(rng.integers(0, n - int(share * n)))
        cut = {
            k: v[start : start + int(share * n)] for k, v in material.channels.items()
        }
        out.append(
            (
                f"excerpt_{int(share * 100)}",
                _with_channels(material, cut, f"{material.name}/excerpt", "excerpt"),
                {"share": share},
            )
        )
    return out


# ---- scoring ---------------------------------------------------------------------------


AXIS = np.geomspace(e10.FLOOR_HZ, e10.REFERENCE_HZ[0], 120)


def _response(report, params) -> np.ndarray:
    if report.accepted is None:
        return np.zeros_like(AXIS)
    return e10.published_response_db(report.accepted.filters, params.realisation, AXIS)


def score(recipe: str, detail: dict, report, asis, params, tolerance: float) -> dict:
    row = {
        "recipe": recipe,
        "selected": None if report.accepted is None else report.accepted.label,
        "detail": {k: v for k, v in detail.items() if k != "hp"},
        "noise_lift": False,
        "unnecessary": False,
        "overshoot": False,
        "missed": False,
        "needs_correction": False,
        "noise_exposed": False,
        "shortfall_median_db": None,
    }
    response = _response(report, params)
    if recipe.startswith("excerpt"):
        row["unnecessary"] = report.accepted is not None
    elif recipe == "noise_replaced":
        only = AXIS <= detail["corner_hz"] * 2.0**-0.5
        row["noise_exposed"] = True
        row["noise_lift_db"] = round(float(response[only].max()), 2)
        row["noise_lift"] = bool(row["noise_lift_db"] > e10.NOISE_LIFT_DB)
    else:
        from scipy import signal

        from beqforge.filters import high_pass_sos

        hp: HighPass = detail["hp"]
        _, transfer = signal.sosfreqz(high_pass_sos(hp, 1000), worN=AXIS, fs=1000)
        inverse = -20.0 * np.log10(np.maximum(np.abs(transfer), 1e-30))
        floor = asis.diagnosis.noise_floor_hz
        floor = floor if math.isfinite(floor) else e10.FLOOR_HZ
        band = (AXIS >= max(floor, e10.FLOOR_HZ)) & (inverse <= CORNER_LIMIT_DB)
        added = response - _response(asis, params)
        row["needs_correction"] = bool(
            e10._span_octaves(AXIS, band & (inverse > tolerance)) > e10.MIN_SPAN_OCTAVES
        )
        if band.any():
            gap = np.maximum(inverse - added, 0.0)[band]
            short = band & (added < inverse - tolerance)
            row["shortfall_median_db"] = round(float(np.median(gap)), 2)
            row["overshoot"] = bool(
                report.accepted is not None
                and (band & (added > inverse + tolerance)).any()
            )
            row["missed"] = bool(
                row["needs_correction"]
                and (
                    report.accepted is None
                    or e10._span_octaves(AXIS, short) > e10.MIN_SPAN_OCTAVES
                )
            )
    return row


def run_titles(args) -> int:
    from beqforge.accept import AcceptParams
    from beqforge.cache import DirStore
    from beqforge.pipeline import PipelineParams, run

    listing = json.loads(args.titles.read_text())
    key = "held_out" if args.partition == "held-out" else "development"
    titles = listing[key][: args.limit] if args.limit else listing[key]
    goals = tuple(args.goals.split(","))
    rows = []
    for index, title in enumerate(titles):
        try:
            material = load(args.library / title)
        except (ValueError, RuntimeError) as unusable:
            print(f"  {title}: skipped ({unusable})", flush=True)
            continue
        built = recipes(material, index)
        with tempfile.TemporaryDirectory(prefix="e10-real-") as scratch:
            store = DirStore(Path(scratch))
            for goal in goals:
                tilt, tolerance = e10.GOALS[goal]
                params = PipelineParams(
                    accept=AcceptParams(
                        target_tilt_db_per_octave=tilt, goal_tolerance_db=tolerance
                    )
                )
                started = time.perf_counter()
                asis = run(material, params, cache_path=store)
                for recipe, varied, detail in built:
                    report = run(varied, params, cache_path=store)
                    row = score(recipe, detail, report, asis, params, tolerance)
                    row.update(title=title, goal=goal, family=recipe)
                    row["asis"] = None if asis.accepted is None else asis.accepted.label
                    rows.append(row)
                flagged = [
                    f"{r['recipe']}:{c}"
                    for r in rows[-len(built) :]
                    for c in ("noise_lift", "unnecessary", "overshoot", "missed")
                    if r[c]
                ]
                print(
                    f"  {title} [{goal}] as-is {rows[-1]['asis'] or '-'}"
                    f" ({time.perf_counter() - started:.0f} s)"
                    + (f"  [{', '.join(flagged)}]" if flagged else ""),
                    flush=True,
                )
    document = {
        "protocol": e10.PROTOCOL_VERSION,
        "partition": args.partition,
        "build": record.revision(),
        "titles": titles,
        "cases": rows,
    }
    args.output.write_text(json.dumps(document, indent=2) + "\n")
    print("E10-REAL-DONE", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    frozen = sub.add_parser("freeze")
    frozen.add_argument("--library", type=Path, default=LIBRARY)
    frozen.add_argument("--out", type=Path, required=True)
    runs = sub.add_parser("run")
    runs.add_argument("--titles", type=Path, required=True)
    runs.add_argument("--library", type=Path, default=LIBRARY)
    runs.add_argument(
        "--partition", choices=("development", "held-out"), default="development"
    )
    runs.add_argument("--limit", type=int)
    runs.add_argument("--goals", default=",".join(e10.GOALS))
    runs.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.command == "freeze":
        freeze(args.library, args.out)
        return 0
    if args.partition == "held-out":
        from tools.e10_run import _clean_tree

        if not _clean_tree():
            parser.error("a held-out run judges a committed change: commit first")
    return run_titles(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
