#!/usr/bin/env python3
"""Redraw charts and export to beqdesigner from a run record — no rerun, no extraction.

    uv run python tools/replay.py data/FILM.run.json.gz --charts charts
    uv run python tools/replay.py data/FILM.run.json.gz --beq out/FILM.beq

A run is a few minutes of fitting over a 138 MB extraction. Everything a chart needs was
already computed during that run, so redrawing one should cost nothing — and until the record
existed it cost a full rerun, or worse, a set of cascades typed back in by hand that went
silently stale across two behaviour changes.

**Staleness is reported, never assumed away.** The record carries the material's hash, the
non-default parameters and the working tree's revision. If any has moved, this says so before
it draws anything, and `--force` is required to go ahead. A picture redrawn from a stale record
looks exactly as current as one that is not, which is the whole reason for the check.
"""

import argparse
import logging
import sys
from pathlib import Path

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqanalyser.design import beqd, record  # noqa: E402
from beqanalyser.design.charts import render_cached  # noqa: E402
from beqanalyser.design.pipeline import PipelineParams  # noqa: E402

logger = logging.getLogger("replay")


def describe(document: dict) -> None:
    material = document["material"]
    print(
        f"{material['name']}: {material['duration_s'] / 60:.1f} min at {material['fs']} Hz"
    )
    written = document["fingerprint"]["written_at"]
    print(f"  recorded {written} at {document['fingerprint']['revision']}")
    accepted = document.get("accepted")
    print(
        f"  {len(document['candidates'])} candidate(s), accepted: {accepted or 'none'}"
    )
    for candidate in document["candidates"]:
        verdict = candidate["verdict"]
        mark = "accept" if verdict["passed"] else "REJECT"
        detail = (
            "; ".join(verdict["failures"]) if verdict["failures"] else "no objections"
        )
        print(f"    {candidate['label']:<22s} {mark}: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument(
        "--charts", type=Path, metavar="DIR", help="redraw charts into DIR"
    )
    parser.add_argument(
        "--beq", type=Path, metavar="PATH", help="write a beqdesigner project"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="proceed even though the record no longer matches this code",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    document = record.read(args.record)
    fingerprint = record.Fingerprint.from_json(document["fingerprint"])
    describe(document)

    material_path = Path(fingerprint.material_path)
    digest = record.material_digest(material_path) if material_path.is_file() else None
    reasons = record.stale_against(fingerprint, PipelineParams(), digest)
    if reasons:
        print(
            "\n  STALE — this record no longer describes what this code would produce:"
        )
        for reason in reasons:
            print(f"    - {reason}")
        if not args.force:
            print(
                "\n  Refusing to draw. Rerun the pipeline, or pass --force to use it anyway."
            )
            return 2
        print("\n  --force given; using it anyway.\n")

    if args.charts:
        written = render_cached(document, args.charts / document["material"]["name"])
        print(
            f"\n  {len(written)} chart(s) redrawn into {args.charts / document['material']['name']}/"
        )
    if args.beq:
        beqd.export(args.beq, document)
        print(f"  beqdesigner project written to {args.beq}")
    if not args.charts and not args.beq:
        print("\n  Nothing asked for; pass --charts and/or --beq.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
