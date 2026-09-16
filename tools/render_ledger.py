#!/usr/bin/env python3
"""Regenerate the Correction Ledger report from run records — no rerun, no hand-transcription.

    uv run python tools/render_ledger.py                      # every data/*.run.json.gz
    uv run python tools/render_ledger.py data/alien.run.json.gz data/tron.run.json.gz
    uv run python tools/render_ledger.py --charts-dir out/ledger --out out/ledger/index.html

For each record this redraws the featured candidate's charts via `charts.render_cached` (the
same no-rerun path `tools/replay.py --charts` uses) and extracts everything the ledger page
shows — label, filters, recovered fraction, confidence, shaping fraction, notes and failures —
directly from the record's own JSON. Nothing here is transcribed by hand, which is the point:
the page used to be built by copying numbers out of a terminal into a JS array, and that does
not survive a second run.

The featured candidate is `document['accepted']` when one exists; otherwise the candidate with
the fewest failures (ties broken by the higher recovered fraction) stands in, so an abstaining
title still gets a picture and a reason instead of being silently dropped.

Writes `--out` (the HTML) and `--files-manifest` (JSON: published filename -> path under
`--charts-dir`, ready to pass as the `files` map to the Artifact tool with `root=--charts-dir`).

Staleness is reported per title, not assumed away — same check `tools/replay.py` makes. A stale
record is skipped with a warning rather than aborting the whole ledger; pass `--force` to draw
it anyway.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqanalyser.design import record  # noqa: E402
from beqanalyser.design.charts import _slug, render_cached  # noqa: E402

logger = logging.getLogger("render_ledger")

TEMPLATE_PATH = Path(__file__).resolve().parent / "ledger_template.html"
DATA_MARKER = "__LEDGER_DATA__"
"""`_slug` is `charts.py`'s own filename sanitiser — imported rather than duplicated, so a
label with a character neither of us has seen yet doesn't drift the two apart."""


def _friendly_name(key: str) -> str:
    return key.replace("_", " ").title()


def _featured_candidate(document: dict[str, Any]) -> dict[str, Any] | None:
    """`document['accepted']`'s candidate, the least-bad of the ones tried, or `None`.

    `None` when no target ever cleared the pre-candidate blockers (§1's "no usable
    contiguous mix plateau" and its siblings) — there is nothing to fit, so `candidates`
    is empty rather than merely all-rejected.
    """
    candidates = document["candidates"]
    accepted = document.get("accepted")
    if accepted is not None:
        return next(c for c in candidates if c["label"] == accepted)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda c: (
            len(c["verdict"]["failures"]),
            -(c["verdict"]["recovered_fraction"] or -1.0),
        ),
    )


def _note_kind(text: str, source: str) -> str:
    if source == "target":
        return "construction"
    if "shaping" in text:
        return "shaping"
    return ""


def title_entry(document: dict[str, Any]) -> dict[str, Any]:
    """One `TITLES` array entry, straight from a run record's own JSON."""
    key = document["material"]["name"]
    candidate = _featured_candidate(document)
    if candidate is None:
        return {
            "headroom_summary": "unavailable — no candidate was ever constructed",
            "headroom_assumptions": "No candidate reached the point a playback model applies to.",
            "key": key,
            "name": _friendly_name(key),
            "material_path": document["fingerprint"]["material_path"],
            "duration_s": document["material"]["duration_s"],
            "status": "abstained",
            "label": "none",
            "sections": 0,
            "candidate_count": 0,
            "recovered": None,
            "shaping": None,
            "confidence": None,
            "mv_adjust_db": None,
            "offset_db": None,
            "band": [float("nan"), float("nan")],
            "filters": [],
            "notes": [
                {"text": text, "kind": "failure"}
                for text in document.get("evidence_notes", [])
            ],
            "failures": [],
            "has_channels": False,
        }
    verdict = candidate["verdict"]
    notes = [
        {"text": text, "kind": _note_kind(text, "target")}
        for text in candidate["target_notes"]
    ] + [
        {"text": text, "kind": _note_kind(text, "verdict")} for text in verdict["notes"]
    ]
    contract = candidate.get("evidence_contract")
    notes.append(
        {
            "text": (
                "Conditional temporal evidence score; not mastering probability or correction completeness."
                if contract == "conditional-temporal-v1"
                else "Legacy score: completeness times level-invariance feature; no current evidence contract was recorded."
            ),
            "kind": "",
        }
    )
    headroom = candidate.get("headroom") or {}
    offset = verdict["required_offset_db"]
    legacy_headroom = (
        "gain reduction unavailable"
        if offset is None
        else (
            "recorded no reduction"
            if offset >= 0
            else f"recorded {-offset:.1f} dB reduction"
        )
    )
    return {
        "headroom_summary": headroom.get("summary")
        or f"{legacy_headroom} (playback model unspecified)",
        "headroom_assumptions": headroom.get("assumptions")
        or "Playback assumptions were not recorded.",
        "key": key,
        "name": _friendly_name(key),
        "material_path": document["fingerprint"]["material_path"],
        "duration_s": document["material"]["duration_s"],
        "status": "accepted" if document.get("accepted") is not None else "abstained",
        "label": candidate["label"],
        "sections": len(candidate["filters"]),
        "candidate_count": len(document["candidates"]),
        "recovered": verdict["recovered_fraction"],
        "shaping": verdict["shaping_fraction"],
        "confidence": candidate.get("confidence"),
        "mv_adjust_db": candidate["mv_adjust_db"],
        "offset_db": verdict["required_offset_db"],
        "band": list(candidate["correction"]["band_hz"]),
        "filters": candidate["filters"],
        "notes": notes,
        "failures": verdict["failures"],
        "has_channels": True,
        # set by `render_title` once it knows whether a per-channel chart was actually drawn
    }


def render_title(
    path: Path, charts_dir: Path, force: bool
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """One title's ledger entry and its `{published name: source path}` chart pair.

    Returns `None` (with a logged warning) when the record is stale and `force` was not given —
    a skipped title is a smaller problem than a page silently drawn from code that has moved on.
    """
    document = record.read(path)
    fingerprint = record.Fingerprint.from_json(document["fingerprint"])
    material_path = Path(fingerprint.material_path)
    digest = record.material_digest(material_path) if material_path.is_file() else None
    reasons = record.stale_against(fingerprint, material_sha256=digest)
    key = document["material"]["name"]
    if reasons and not force:
        logger.warning(f"{key}: STALE, skipping ({'; '.join(reasons)})")
        return None
    if reasons:
        logger.warning(f"{key}: stale, drawing anyway (--force): {'; '.join(reasons)}")

    entry = title_entry(document)
    out_dir = charts_dir / key
    render_cached(document, out_dir)
    if entry["label"] == "none":
        # Nothing was ever fitted, so `curves["filtered"]` is empty and no chart exists
        # to redraw — there is no before/after to show, only the reasons in `entry["notes"]`.
        return entry, {}
    slug = _slug(entry["label"])
    files = {
        f"{key}_mono.png": f"{key}/{slug}_mono.png",
        f"{key}_channels.png": f"{key}/{slug}_channels.png",
    }
    channels_path = charts_dir / files[f"{key}_channels.png"]
    entry["has_channels"] = channels_path.is_file()
    if not entry["has_channels"]:
        # a document-wide property, not a per-label one: `record.curves_from` only stores a
        # "channels" curve at all when some channel cleared the relevance bar, and if it did
        # every label got one. Drop the file rather than publish a 404.
        logger.warning(f"{key}: no per-channel curves in this record; mono chart only")
        del files[f"{key}_channels.png"]
    return entry, files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "records", nargs="*", type=Path, help="run records; default: data/*.run.json.gz"
    )
    parser.add_argument(
        "--charts-dir",
        type=Path,
        default=Path("out/ledger"),
        help="where to redraw charts (default: out/ledger)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output HTML path (default: <charts-dir>/index.html)",
    )
    parser.add_argument(
        "--files-manifest",
        type=Path,
        default=None,
        help="output JSON manifest path (default: <charts-dir>/files.json)",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=TEMPLATE_PATH,
        help="HTML template to inject data into",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="draw stale records anyway, instead of skipping them",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    records = args.records or sorted(Path("data").glob("*.run.json.gz"))
    if not records:
        parser.error("no records given and none found under data/*.run.json.gz")

    charts_dir = args.charts_dir
    out_path = args.out or charts_dir / "index.html"
    manifest_path = args.files_manifest or charts_dir / "files.json"
    charts_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    manifest: dict[str, str] = {}
    for path in records:
        result = render_title(path, charts_dir, args.force)
        if result is None:
            continue
        entry, files = result
        entries.append(entry)
        manifest.update(files)
        logger.info(f"  {entry['key']}: {entry['status']} ({entry['label']})")

    if not entries:
        logger.error(
            "nothing to render — every record was stale (see above), or none given"
        )
        return 1

    entries.sort(key=lambda e: e["key"])
    payload = json.dumps(entries, indent=2).replace("</", "<\\/")
    template = args.template.read_text(encoding="utf-8")
    if DATA_MARKER not in template:
        parser.error(f"{args.template} has no {DATA_MARKER} marker to inject into")
    out_path.write_text(template.replace(DATA_MARKER, payload), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    logger.info(f"\n{len(entries)} title(s) rendered")
    logger.info(f"  page:     {out_path}")
    logger.info(
        f"  manifest: {manifest_path}  (root={charts_dir} for the Artifact tool)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
