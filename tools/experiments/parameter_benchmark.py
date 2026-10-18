"""Parameter search against coefficient search on the catalogue report's worst float32 entries.

    uv run python -m tools.experiments.parameter_benchmark /path/to/beqcatalogue/docs/database.json

Takes the entries with the largest original error at each rate from the committed report
(`docs/optimiser-report/entry-results.json.gz`), refusing a catalogue snapshot other than the
one the report was made from, and for each runs `beqoptimiser.optimise` (coefficients, float32
storage and transport, the report's settings) and `beqoptimiser.optimise_parameters` (the same
profile, default bounds) on the entry's RBJ cascade, both uncached. Both start from the
parameters as authored: the report's baseline uses published coefficients where an entry has
them, so its original errors can differ from these.
"""

import argparse
import gzip
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from beqoptimiser import Float32, Section, optimise, optimise_parameters

REPORT = Path("docs/optimiser-report")


def _sections(entry: dict) -> list[Section]:
    filters = entry["filters"]
    if isinstance(filters, str):
        filters = json.loads(filters)
    return [
        Section(f["type"], float(f["freq"]), float(f["q"]), float(f["gain"]))
        for f in filters
        for _ in range(int(f.get("count", 1)))
    ]


def _on_grid(s: Section) -> bool:
    return (
        round(s.freq, 2) == s.freq
        and round(s.q, 4) == s.q
        and round(s.gain, 2) == s.gain
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--per-rate", type=int, default=25)
    parser.add_argument("--out", type=Path, help="write every row as JSON here")
    args = parser.parse_args()

    raw = args.catalogue.read_bytes()
    provenance = json.loads((REPORT / "statistics.json").read_text())["provenance"]
    if hashlib.sha256(raw).hexdigest() != provenance["catalogue_sha256"]:
        raise SystemExit("catalogue snapshot differs from the one the report used")
    entries = json.loads(raw)
    results = json.loads(
        gzip.decompress((REPORT / "entry-results.json.gz").read_bytes())
    )

    rows = []
    for rate in (48000, 96000):
        candidates = [
            r
            for r in results
            if r["rate"] == rate
            and r["original_max_error_db"] is not None
            and np.isfinite(r["original_max_error_db"])
            and r["outcome"] not in ("within_margin", "error", "unsupported")
        ]
        candidates.sort(key=lambda r: -r["original_max_error_db"])
        seen: set[str] = set()
        for r in candidates:
            if len([x for x in rows if x["rate"] == rate]) >= args.per_rate:
                break
            entry = entries[r["ordinal"]]
            try:
                sections = _sections(entry)
            except (KeyError, TypeError, ValueError):
                continue
            key = json.dumps([[s.type, s.freq, s.q, s.gain] for s in sections])
            if key in seen or len(sections) > 10:
                continue
            seen.add(key)
            reference = np.array([s.sos(rate) for s in sections])
            started = time.perf_counter()
            coefficients = optimise(
                reference,
                rate=rate,
                precision=Float32(),
                transport=Float32(),
                cache=False,
            )
            middle = time.perf_counter()
            parameters = optimise_parameters(
                sections, profiles=[(rate, Float32())], cache=False
            )
            ended = time.perf_counter()
            rows.append(
                {
                    "rate": rate,
                    "ordinal": r["ordinal"],
                    "title": r["title"],
                    "sections": len(sections),
                    "on_grid": all(_on_grid(s) for s in sections),
                    "coefficient_outcome": coefficients.outcome,
                    "coefficient_original_db": coefficients.original_error_db,
                    "coefficient_db": coefficients.candidate_error_db,
                    "coefficient_s": middle - started,
                    "parameter_outcome": parameters.outcome,
                    "parameter_original_db": parameters.original_error_db,
                    "parameter_db": parameters.candidate_error_db,
                    "parameter_s": ended - middle,
                }
            )
            row = rows[-1]
            print(
                f"{rate} {row['title'][:28]:28} {row['sections']:2}s "
                f"grid={'y' if row['on_grid'] else 'n'} "
                f"coef {row['coefficient_original_db']:.3f}->{row['coefficient_db'] or 0:.3f} "
                f"({row['coefficient_outcome']}, {row['coefficient_s']:.1f}s) "
                f"param {row['parameter_original_db']:.3f}->{row['parameter_db'] or 0:.3f} "
                f"({row['parameter_outcome']}, {row['parameter_s']:.1f}s)",
                flush=True,
            )
    if args.out:
        args.out.write_text(json.dumps(rows, indent=1))
    for rate in (48000, 96000):
        mine = [r for r in rows if r["rate"] == rate]
        if not mine:
            continue

        def published(outcome):
            return outcome in ("replacement", "improvement")

        print(
            f"{rate}: {len(mine)} entries; within margin coefficient "
            f"{sum(r['coefficient_outcome'] == 'replacement' for r in mine)}, parameter "
            f"{sum(r['parameter_outcome'] == 'replacement' for r in mine)}; published "
            f"coefficient {sum(published(r['coefficient_outcome']) for r in mine)}, parameter "
            f"{sum(published(r['parameter_outcome']) for r in mine)}; median error after "
            f"coefficient {np.median([r['coefficient_db'] or r['coefficient_original_db'] for r in mine]):.3f} dB, "
            f"parameter {np.median([r['parameter_db'] or r['parameter_original_db'] for r in mine]):.3f} dB; "
            f"off-grid {sum(not r['on_grid'] for r in mine)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
