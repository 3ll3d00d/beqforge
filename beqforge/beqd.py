"""Export a run to a beqdesigner project, so a person can look at it in their own tool.

A different job from `record.py`, and deliberately a different file. The record has to be
complete and exact for our own re-analysis; this has to be *idiomatic beqdesigner*, and it is
allowed to drop anything that tool has nowhere to put. Bending either into the other would
make our cache hostage to a schema we do not own, and would fill someone else's project file
with fields their UI cannot show.

Format, read off beqdesigner at `src/main/python` (it is not importable — `[tool.uv]
package = false`, and it would drag PyQt6 behind it — so the schema is reproduced, not called):

* a `.beq` is **gzipped JSON**, top level a list of signals (`app.py:exportProject`)
* a signal is `{_type, name, fs, data: {avg, peak}, offset, filter?, metadata?}`
  (`model/codec.py:signaldata_to_json`)
* a curve is `{_type, name, description, x[], y[], colour, linestyle}` (`xydata_to_json`)
* a filter is a `CompleteFilter` of `{_type, fs, fc, q, gain, count}` sections
  (`model/iir.py:Shelf.to_json`); `PeakingEQ` takes no `count`

What goes in: one signal per contributing channel carrying that channel's own measured curves,
so the underlying signal is there to look at, and one signal per candidate carrying the mono
mix with that candidate's cascade attached. The rejected candidates are included on purpose —
on the fourth title every candidate was rejected, and those five cascades are exactly what a
person would want to put on screen together.
"""

import gzip
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from beqanalyser.design import BiquadSpec

logger = logging.getLogger(__name__)

PUBLISH_FS = 96000
"""Rate the exported filters are defined at, matching what the pipeline publishes."""

_TYPES = {
    "low_shelf": "LowShelf",
    "high_shelf": "HighShelf",
    "peaking_eq": "PeakingEQ",
}
"""Ours to beqdesigner's class names, which are what its decoder dispatches on."""


def _curve(name: str, description: str, freqs, values, colour=None) -> dict[str, Any]:
    return {
        "_type": "MagnitudeData",
        "name": name,
        "description": description,
        "x": [round(float(v), 6) for v in np.asarray(freqs)],
        "y": [round(float(v), 6) for v in np.asarray(values)],
        "colour": colour,
        "linestyle": "-",
    }


def _section(spec: BiquadSpec, fs: int) -> dict[str, Any]:
    kind = _TYPES.get(spec.type)
    if kind is None:
        raise ValueError(f"no beqdesigner filter type for {spec.type!r}")
    out: dict[str, Any] = {
        "_type": kind,
        "fs": fs,
        "fc": round(float(spec.freq_hz), 2),
        "q": round(float(spec.q), 4),
        "gain": round(float(spec.gain_db), 3),
    }
    # `fc` for every type: PeakingEQ overrides its parent's `freq` and writes `fc`, and
    # `filter_from_json` reads `fc` in all three branches. Only the shelves take a `count`.
    if kind != "PeakingEQ":
        out["count"] = 1
    return out


def _cascade(specs: list[BiquadSpec], fs: int) -> dict[str, Any]:
    return {
        "_type": "CompleteFilter",
        "fs": fs,
        "description": "BEQ",
        "preset_idx": -1,
        "filters": [_section(s, fs) for s in specs],
    }


def _signal(
    name: str,
    fs: int,
    freqs,
    average,
    peak,
    specs: list[BiquadSpec] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signal: dict[str, Any] = {
        "_type": "SignalData",
        "name": name,
        "fs": fs,
        "data": {
            "avg": _curve(name, "avg", freqs, average),
            "peak": _curve(name, "peak", freqs, peak),
        },
        "offset": "0",
    }
    if specs:
        signal["filter"] = _cascade(specs, PUBLISH_FS)
    if metadata:
        signal["metadata"] = metadata
    return signal


def export(path: Path | str, record: dict[str, Any]) -> Path:
    """Write a `.beq` from a run record. Returns where it went.

    Driven from the record rather than from a live `Report` so an export can be produced for
    a run that happened days ago, which is the case that motivated caching at all.
    """
    curves = record.get("curves")
    if not curves:
        raise ValueError("the record carries no curves; nothing to export")
    freqs = curves["freqs"]
    fs = int(record["material"]["fs"])
    title = record["material"]["name"]
    accepted = record.get("accepted")

    signals: list[dict[str, Any]] = []
    for name, measured in curves["unfiltered"].items():
        if name == "mono":
            continue
        signals.append(
            _signal(f"{title} {name}", fs, freqs, measured["average"], measured["peak"])
        )

    mono = curves["unfiltered"]["mono"]
    for candidate in record["candidates"]:
        label = candidate["label"]
        verdict = candidate["verdict"]
        signals.append(
            _signal(
                f"{title} {label}" + ("" if label != accepted else " (accepted)"),
                fs,
                freqs,
                mono["average"],
                mono["peak"],
                specs=[
                    BiquadSpec(f["type"], f["freq_hz"], f["gain_db"], f["q"])
                    for f in candidate["filters"]
                ],
                # our verdict has nowhere to live in beqdesigner's model, so it rides here
                # rather than being silently dropped or forced into a typed field
                metadata={
                    # their loader reads `metadata['src']` and calls os.path.isfile on it
                    # before anything else; an empty string fails that cleanly, where a
                    # missing key raises and is logged as an exception on every load
                    "src": "",
                    "beqanalyser": {
                        "accepted": bool(verdict["passed"]),
                        "failures": verdict["failures"],
                        "notes": verdict["notes"] + candidate["target_notes"],
                        "mv_adjust_db": candidate["mv_adjust_db"],
                    },
                },
            )
        )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        handle.write(json.dumps(signals).encode("utf-8"))
    logger.info(f"  beqdesigner project: {path} ({len(signals)} signals)")
    return path
