"""Import trusted historical report evaluations into the library and bundled caches."""

import argparse
import gzip
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from beqoptimiser import Float32, Result, ResultCache, Settings
from beqoptimiser.cache import CACHE_SCHEMA, _envelope, implementation_identity
from beqoptimiser.cli import prepare_entry
from tools.optimiser_catalogue_report import RATES, job_key


def archived_source(revision: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"], check=True, capture_output=True
    ).stdout


def seed(
    catalogue: Path,
    legacy: Path,
    statistics: Path,
    *,
    revision: str,
    cache_dir: Path,
    bundle: Path,
) -> dict:
    """Verify provenance and migrate results without repeating any numerical search."""
    raw = catalogue.read_bytes()
    provenance = json.loads(statistics.read_text())["provenance"]
    if hashlib.sha256(raw).hexdigest() != provenance["catalogue_sha256"]:
        raise ValueError("catalogue does not match the completed report")
    if provenance["settings"] != json.loads(json.dumps(asdict(Settings()))):
        raise ValueError("legacy settings are incompatible")
    identity = implementation_identity()
    for dependency in ("numpy", "scipy"):
        if provenance[dependency] != identity[dependency]:
            raise ValueError(f"legacy {dependency} version is incompatible")
    root = Path(__file__).resolve().parents[1]
    paths = sorted(
        [
            "beqoptimiser/__init__.py",
            "beqoptimiser/cli.py",
            "beqoptimiser/core.py",
            "beq_common/__init__.py",
            "beq_common/biquad.py",
            "beq_common/provenance.py",
            "beq_common/publication.py",
            "beq_common/types.py",
            "tools/optimiser_catalogue_report.py",
        ]
    )
    archived = {path: archived_source(revision, path) for path in paths}
    if (
        hashlib.sha256(b"".join(archived[path] for path in paths)).hexdigest()
        != provenance["code_sha256"]
    ):
        raise ValueError("archived implementation does not match the completed report")
    for path in (
        "beqoptimiser/core.py",
        "beq_common/biquad.py",
        "beq_common/__init__.py",
    ):
        if archived[path] != (root / path).read_bytes():
            raise ValueError(f"numerical implementation changed: {path}")
    # The old report did not record architecture; its x86_64/Linux run used an
    # 80-bit long double. Do not relabel that seed as another execution environment.
    if (
        identity["system"] != "Linux"
        or identity["machine"] != "x86_64"
        or identity["longdouble_mantissa_bits"] != 63
    ):
        raise ValueError("legacy numerical architecture is incompatible")
    cache = ResultCache(cache_dir, use_seed=False)
    envelopes = {}
    imported, unsupported = 0, 0
    for entry in json.loads(raw):
        for rate in RATES:
            old_key = job_key(entry, rate, provenance["code_sha256"])
            report = json.loads((legacy / f"{old_key}.json").read_text())
            if report["result"]["outcome"] == "unsupported":
                try:
                    prepare_entry(entry, rate=rate)
                except (ValueError, KeyError, TypeError, OverflowError):
                    unsupported += 1
                    continue
                raise ValueError(
                    "legacy unsupported entry is supported by the current parser"
                )
            reference, sent, _, _ = prepare_entry(entry, rate=rate)
            body = dict(report["result"])
            body["original_error_db"] = (
                float("inf")
                if body["original_error_db"] is None
                else body["original_error_db"]
            )
            if body["evaluations"]:
                for field in ("candidate_error_db", "guard_error_db"):
                    if body[field] is None:
                        body[field] = float("inf")
            body["band_hz"] = tuple(body["band_hz"])
            variant = report["variant"]
            body["replacement"] = (
                tuple(
                    (*map(float, row["b"]), 1.0, *(-float(v) for v in row["a"]))
                    for row in variant["biquads"]
                )
                if variant
                else None
            )
            result = Result(**body)
            key = cache.seed(
                reference,
                result,
                rate=rate,
                precision=Float32(),
                transport=Float32(),
                sent=sent,
            )
            envelope = _envelope(key, result)
            if key in envelopes and envelopes[key] != envelope:
                raise ValueError("conflicting results for identical numerical requests")
            envelopes[key] = envelope
            imported += 1
            if imported % 2000 == 0:
                print(f"{imported:,} supported entry/rate results migrated", flush=True)
    document = {
        "schema": CACHE_SCHEMA,
        "implementation": identity,
        "provenance": {
            **provenance,
            "report_revision": revision,
            "entry_rate_results": imported,
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
        f"Seeded {len(envelopes):,} numerical results; {unsupported} unsupported entry/rate cases skipped",
        flush=True,
    )
    return {key: value for key, value in document.items() if key != "entries"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--legacy-cache", type=Path, required=True)
    parser.add_argument(
        "--statistics", type=Path, default=Path("docs/optimiser-report/statistics.json")
    )
    parser.add_argument("--report-revision", required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument(
        "--bundle", type=Path, default=Path("beqoptimiser/data/seed.json.gz")
    )
    args = parser.parse_args()
    seed(
        args.catalogue,
        args.legacy_cache,
        args.statistics,
        revision=args.report_revision,
        cache_dir=args.cache_dir,
        bundle=args.bundle,
    )


if __name__ == "__main__":
    main()
