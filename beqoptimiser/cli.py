"""JSON catalogue adapter and CLI; originals are never modified."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import Float32, Section, Settings, optimise


def optimise_entry(entry: dict, *, rate: int, settings: Settings | None = None) -> dict:
    """Produce an optional variant, preserving the complete authored entry separately.

    Only common shelf/PEQ cascades are supported. Cached coefficients, when complete,
    define the sent baseline; authored parameters always define the ideal reference.
    """
    if any(k in entry for k in ("channel_cascades", "channelFilters", "channel_scope")):
        raise ValueError("channel-specific filters are unsupported")
    offset = float(entry.get("mv", 0))
    if not np.isfinite(offset):
        raise ValueError("invalid volume offset")
    filters = entry["filters"]
    if isinstance(filters, str):
        filters = json.loads(filters)
    if not isinstance(filters, list) or not filters:
        raise ValueError("missing filters")
    exact, cached = [], []
    complete = True
    for f in filters:
        if any(k in f for k in ("channels", "channel", "slope")):
            raise ValueError("unsupported channel/slope field")
        count = f.get("count", 1)
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= 10
        ):
            raise ValueError("invalid section count")
        row = Section(f["type"], f["freq"], f["q"], f["gain"]).sos(rate)
        exact.extend([row] * count)
        bq = f.get("biquads", {}).get(str(rate))
        if bq is None:
            complete = False
        else:
            if len(bq["b"]) != 3 or len(bq["a"]) != 2:
                raise ValueError("invalid cached coefficients")
            cached.extend(
                [[*map(float, bq["b"]), 1.0, *(-float(v) for v in bq["a"])]] * count
            )
    if len(exact) > 10:
        raise ValueError("cascade exceeds initial 10-section capacity")
    if cached and not complete:
        raise ValueError(
            "incomplete cached coefficient set; loading policy must be explicit"
        )
    result = optimise(
        exact,
        rate=rate,
        precision=Float32(),
        transport=Float32(),
        sent=np.asarray(cached) if complete else None,
        settings=settings,
    )
    source_digest = hashlib.sha256(
        json.dumps(
            entry, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    report = asdict(result)
    report.pop("replacement")
    variant = None
    if result.replacement is not None:
        variant = {
            "volume_offset_db": offset,
            "schema_version": 1,
            "profile": "float32-custom-biquads",
            "rate": rate,
            "storage": "float32",
            "transport": "float32",
            "loading_model": "additive-feedback-decimal17-v1",
            "source_digest": source_digest,
            "optimiser_version": result.version,
            "settings": asdict(settings or Settings()),
            "metrics": report,
            "biquads": [
                {
                    "b": [format(v, ".17g") for v in row[:3]],
                    "a": [format(-v, ".17g") for v in row[4:]],
                }
                for row in result.replacement
            ],
        }
    return {
        "source_digest": source_digest,
        "baseline_source": "published" if complete else "RBJ",
        "result": report,
        "variant": variant,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Predict and optimise published BEQ coefficients"
    )
    parser.add_argument("input", type=Path, help="JSON entry or catalogue array")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--rate",
        type=int,
        choices=(48000, 96000),
        action="append",
        help="repeat for both rates; defaults to both",
    )
    parser.add_argument("--margin-db", type=float, default=0.5)
    parser.add_argument("--passes", type=int, default=6)
    args = parser.parse_args(argv)
    if args.out.resolve() == args.input.resolve() or (
        args.out.exists() and args.input.exists() and args.out.samefile(args.input)
    ):
        parser.error("output must differ from the source catalogue")
    settings = Settings(margin_db=args.margin_db, passes=args.passes)
    raw = args.input.read_bytes()
    entries = json.loads(raw)
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        parser.error("input must be an entry or catalogue array")
    reports = []
    for ordinal, entry in enumerate(entries):
        for rate in dict.fromkeys(args.rate or (48000, 96000)):
            try:
                report = optimise_entry(entry, rate=rate, settings=settings)
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                report = {
                    "result": {"outcome": "unsupported"},
                    "variant": None,
                    "reason": str(error),
                }
            reports.append({"ordinal": ordinal, "rate": rate, **report})

    # Nonfinite diagnostics are encoded explicitly rather than emitting invalid JSON.
    def clean(value):
        if isinstance(value, float) and not np.isfinite(value):
            return None
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value

    document = {
        "schema_version": 1,
        "scope": "predicted coefficient response; not hardware validation",
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "entries": reports,
    }
    args.out.write_text(json.dumps(clean(document), indent=2, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
