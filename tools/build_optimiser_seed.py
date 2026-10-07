"""Bundle a completed catalogue report's library-cache results as the shipped optimiser seed.

The report (tools/optimiser_catalogue_report.py) writes every entry/rate result to the library
cache. This verifies the report's provenance against the catalogue, settings, dependencies and
committed source, then copies the validated cache envelope for every supported entry/rate into
the bundled seed without repeating any numerical search. A missing result is an error.
"""

import argparse
import gzip
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from beqoptimiser import Float32, ResultCache, Settings
from beqoptimiser.cache import (
    CACHE_SCHEMA,
    _envelope,
    _request,
    implementation_identity,
)
from beqoptimiser.cli import prepare_entry
from tools.optimiser_catalogue_report import RATES

UNSUPPORTED = (ValueError, KeyError, TypeError, OverflowError)


def report_sources(root: Path) -> list[str]:
    """The files tools/optimiser_catalogue_report.py digests as its code_sha256."""
    return sorted(
        str(path.relative_to(root))
        for path in [
            *root.joinpath("beqoptimiser").glob("*.py"),
            *root.joinpath("beq_common").glob("*.py"),
            root / "tools" / "optimiser_catalogue_report.py",
        ]
    )


def archived_source(revision: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"], check=True, capture_output=True
    ).stdout


def build(
    catalogue: Path,
    statistics: Path,
    *,
    revision: str,
    cache_dir: Path,
    bundle: Path,
) -> dict:
    raw = catalogue.read_bytes()
    provenance = json.loads(statistics.read_text())["provenance"]
    if hashlib.sha256(raw).hexdigest() != provenance["catalogue_sha256"]:
        raise ValueError("catalogue does not match the completed report")
    if provenance["settings"] != json.loads(json.dumps(asdict(Settings()))):
        raise ValueError("report settings are not the current defaults")
    identity = implementation_identity()
    for dependency in ("numpy", "scipy"):
        if provenance[dependency] != identity[dependency]:
            raise ValueError(f"report {dependency} version is incompatible")
    root = Path(__file__).resolve().parents[1]
    paths = report_sources(root)
    current = hashlib.sha256(
        b"".join((root / path).read_bytes() for path in paths)
    ).hexdigest()
    archived = hashlib.sha256(
        b"".join(archived_source(revision, path) for path in paths)
    ).hexdigest()
    if not current == archived == provenance["code_sha256"]:
        raise ValueError(
            "report, committed revision and working tree source digests differ"
        )
    store = ResultCache(cache_dir, use_seed=False)
    envelopes = {}
    supported, unsupported = 0, 0
    for entry in json.loads(raw):
        for rate in RATES:
            try:
                reference, sent, _, _ = prepare_entry(entry, rate=rate)
            except UNSUPPORTED:
                unsupported += 1
                continue
            request = _request(
                reference,
                rate=rate,
                precision=Float32(),
                transport=Float32(),
                sent=sent,
            )
            if request is None:
                raise ValueError(f"uncacheable request for {entry.get('title')}")
            result = store.get(request)
            if result is None:
                raise ValueError(
                    f"no cached result for {entry.get('title')} at {rate}, rerun the report"
                )
            envelope = _envelope(request[0], result)
            if request[0] in envelopes and envelopes[request[0]] != envelope:
                raise ValueError("conflicting results for identical numerical requests")
            envelopes[request[0]] = envelope
            supported += 1
    document = {
        "schema": CACHE_SCHEMA,
        "implementation": identity,
        "provenance": {
            **provenance,
            "report_revision": revision,
            "entry_rate_results": supported,
            "unsupported_entry_rate_results": unsupported,
            "unique_numerical_results": len(envelopes),
        },
        "entries": envelopes,
    }
    bundle.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic compression, without an embedded local filename or timestamp.
    with (
        bundle.open("wb") as output,
        gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as stream,
    ):
        stream.write(
            json.dumps(
                document, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        )
    manifest = {key: value for key, value in document.items() if key != "entries"}
    manifest["seed_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
    bundle.with_name("seed-manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n"
    )
    print(
        f"Seeded {len(envelopes):,} numerical results from {supported:,} entry/rate results; "
        f"{unsupported} unsupported entry/rate cases skipped",
        flush=True,
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument(
        "--statistics", type=Path, default=Path("docs/optimiser-report/statistics.json")
    )
    parser.add_argument(
        "--report-revision",
        required=True,
        help="the commit holding the report and the source it was generated from",
    )
    parser.add_argument(
        "--bundle", type=Path, default=Path("beqoptimiser/data/seed.json.gz")
    )
    args = parser.parse_args()
    build(
        args.catalogue,
        args.statistics,
        revision=args.report_revision,
        cache_dir=args.cache_dir,
        bundle=args.bundle,
    )


if __name__ == "__main__":
    main()
