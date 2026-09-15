"""The run record — everything a run produced, written once so it need not be run again.

A run is a few minutes of fitting over a 138 MB extraction. Regenerating a chart, re-reading a
verdict or comparing two titles should cost none of that, and until this existed it cost all of
it: charts were redrawn from cascades typed back in by hand, and went silently stale across two
behaviour changes because nothing recorded what had produced them.

So the record carries a **fingerprint** — the material's hash, the parameters that were not
defaults, and the working tree's revision — and `stale_against` compares it to the code asking
to read it. A cache that cannot tell you it is out of date is worse than no cache, because the
picture it draws still looks current.

This is deliberately *our* format and not beqdesigner's. The two jobs are different: this one
has to be complete and exact for re-analysis, where an export has to be idiomatic in someone
else's UI and is allowed to be lossy. Bending one into the other makes the cache hostage to a
schema we do not own. `beqd.py` does the export.

Curves are stored to three decimals. They are dB and the material's own roughness is several
of them, so more is storage without information.
"""

import gzip
import hashlib
import json
import logging
import math
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from beqanalyser.design import BiquadSpec
from beqanalyser.design.material import Material

logger = logging.getLogger(__name__)

SCHEMA = 1
"""Bumped when a field changes meaning; mismatches require explicit stale replay.

Evidence notes, publication details and strategy metadata are additive. Legacy documents are
read verbatim, never upgraded into claims they did not make; changed source fingerprints mark
them stale even when their schema remains readable.
"""

DECIMALS = 3
"""Curve precision. dB, against material that wobbles by several of them."""


def _arr(values: np.ndarray | None) -> list[float] | None:
    if values is None:
        return None
    return [round(float(v), DECIMALS) for v in np.asarray(values)]


def _num(value: float) -> float | None:
    """NaN is not JSON. It is also meaningful here, so it round-trips as null."""
    return None if value is None or math.isnan(value) else float(value)


def _back(value: float | None) -> float:
    return math.nan if value is None else float(value)


RECORD_SOURCE_FILES = (
    "beqanalyser/__init__.py",
    "tools/extract.py",
    "tools/design_beq.py",
    "tools/replay.py",
    "tools/render_ledger.py",
    "tools/ledger_template.html",
)
"""Record/replay dependencies outside design/, relative to the repository root.

The root package owns the RBJ arithmetic. The entry points extract material, configure runs,
replay/export records and select/render ledger results; the template controls their display.
All design modules are included separately, including newly added ones. This deliberately
invalidates records on presentation edits too; a record claims what this code would produce.

Docs, tests, clustering-only modules, experiments and the standalone summariser are excluded
from the content hash. Git revision/dirty status remains a conservative additional check, so
an unrelated commit or the first dirty edit can still mark a record stale. Successive unrelated
edits in an already-dirty tree do not change the content hash. Extracted data is fingerprinted
separately by material_digest. This is a source fingerprint, not an installed-environment hash.
Stage caches retain their narrower dependency lists in cache.py.
"""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_paths(root: Path) -> tuple[Path, ...]:
    declared = {root / name for name in RECORD_SOURCE_FILES}
    design_modules = set((root / "beqanalyser" / "design").rglob("*.py"))
    return tuple(sorted(declared | design_modules))


def _source_digest() -> str:
    """SHA-256 over record/replay source identities and contents, first 12 hex.

    git describe --dirty cannot distinguish successive edits in an already-dirty tree.
    Include paths and delimited content digests so changes, additions and removals all count.
    Missing explicitly declared sources raise rather than silently weakening the fingerprint.
    """
    root = _repository_root()
    digest = hashlib.sha256(b"record-sources-v2\0")
    for path in _source_paths(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:12]


def _git_revision() -> str:
    """`git describe`, plus record/replay source contents to distinguish dirty edits."""
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--abbrev=12"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=_repository_root(),
        )
        described = out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        described = "unknown"
    return f"{described}+src:{_source_digest()}"


def material_digest(path: Path | str) -> str:
    """SHA-256 of the extraction, so a record cannot be read against different material."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """What produced a record. The whole point of the cache having one."""

    schema: int
    material_sha256: str
    material_path: str
    params: str
    """`repr` of the `PipelineParams` used. `DefaultAwareRepr` prints only what was changed,
    so this stays short and says exactly what was non-standard about the run."""

    revision: str
    written_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "material_sha256": self.material_sha256,
            "material_path": self.material_path,
            "params": self.params,
            "revision": self.revision,
            "written_at": self.written_at,
        }

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "Fingerprint":
        return Fingerprint(
            schema=int(raw["schema"]),
            material_sha256=str(raw["material_sha256"]),
            material_path=str(raw["material_path"]),
            params=str(raw["params"]),
            revision=str(raw["revision"]),
            written_at=str(raw["written_at"]),
        )


def stale_against(
    fingerprint: Fingerprint,
    params: object,
    material_sha256: str | None = None,
) -> list[str]:
    """Why this record cannot be trusted for the run being asked for, or an empty list.

    Returned rather than raised, because "the code moved on" is a thing the caller may
    legitimately choose to look at anyway, while "different material" almost never is. The
    caller decides; what is not allowed is not being told.
    """
    reasons: list[str] = []
    if fingerprint.schema != SCHEMA:
        reasons.append(f"written against schema {fingerprint.schema}, this is {SCHEMA}")
    if material_sha256 is not None and fingerprint.material_sha256 != material_sha256:
        reasons.append("the material has changed since it was written")
    if fingerprint.params != repr(params):
        reasons.append(f"parameters differ: recorded {fingerprint.params}")
    current = _git_revision()
    if fingerprint.revision != current:
        reasons.append(f"code was {fingerprint.revision}, now {current}")
    return reasons


def _spec(section: BiquadSpec) -> dict[str, Any]:
    return {
        "type": section.type,
        "freq_hz": float(section.freq_hz),
        "gain_db": float(section.gain_db),
        "q": float(section.q),
    }


def _spec_back(raw: dict[str, Any]) -> BiquadSpec:
    return BiquadSpec(
        str(raw["type"]),
        float(raw["freq_hz"]),
        float(raw["gain_db"]),
        float(raw["q"]),
    )


def _channel(channel) -> dict[str, Any]:
    return {
        "name": channel.name,
        "response_db": _arr(channel.response_db),
        "share": _arr(channel.share),
        "max_slope_db_per_octave": _num(channel.max_slope_db_per_octave),
        "max_slope_hz": _num(channel.max_slope_hz),
        "passband_share": _num(channel.passband_share),
        "is_filtered": bool(channel.is_filtered),
        "plateau_hz": [_num(channel.plateau_hz[0]), _num(channel.plateau_hz[1])],
    }


def _diagnosis(diagnosis) -> dict[str, Any]:
    return {
        "freqs": _arr(diagnosis.freqs),
        "mix_db": _arr(diagnosis.mix_db),
        "channels": [_channel(c) for c in diagnosis.channels.values()],
        "stratified": {k: _arr(v) for k, v in diagnosis.stratified.items()},
        "level_spread_db": _arr(diagnosis.level_spread_db),
        "filter_floor_hz": _num(diagnosis.filter_floor_hz),
        "noise_floor_hz": _num(diagnosis.noise_floor_hz),
    }


def _verdict(verdict) -> dict[str, Any]:
    return {
        "passed": bool(verdict.passed),
        "failures": list(verdict.failures),
        "notes": list(verdict.notes),
        "extent_hz": _num(verdict.extent_hz),
        "worst_gradient_before": _num(verdict.worst_gradient_before),
        "worst_gradient_after": _num(verdict.worst_gradient_after),
        "required_offset_db": _num(verdict.required_offset_db),
        "device_error_db": _num(verdict.device_error_db),
        "dc_margin_steps": _num(verdict.dc_margin_steps),
        "turnover_before": _num(verdict.turnover_before),
        "turnover_after": _num(verdict.turnover_after),
        "roughness_db": _num(verdict.roughness_db),
        "wobble_db": _num(verdict.wobble_db),
        "drift_db": _num(verdict.drift_db),
        "recovered_fraction": _num(verdict.recovered_fraction),
        "shaping_fraction": _num(verdict.shaping_fraction),
    }


def _candidate(candidate) -> dict[str, Any]:
    correction = candidate.correction
    return {
        "label": candidate.label,
        "method": candidate.method,
        "effective_params": candidate.effective_params,
        "filters": [_spec(f) for f in candidate.filters],
        "optimiser_filters": [_spec(f) for f in candidate.optimiser_filters],
        "fit_error_db": _num(candidate.fit_error_db),
        "target_db": _arr(candidate.target_db),
        "unpriced_target_db": _arr(candidate.unpriced_target_db),
        "target_notes": list(candidate.target_notes),
        "mv_adjust_db": _num(candidate.mv_adjust_db),
        "confidence": _num(candidate.confidence),
        "correction": {
            "freqs": _arr(correction.freqs),
            "before_db": _arr(correction.before_db),
            "after_db": _arr(correction.after_db),
            "spread_db": _num(correction.spread_db),
            "tilt_db_per_octave": _num(correction.tilt_db_per_octave),
            "level_db": _num(correction.level_db),
            "band_hz": list(correction.band_hz),
        },
        "verdict": _verdict(candidate.verdict),
    }


def write(
    path: Path | str,
    report,
    params: object,
    material_path: Path | str,
    curves: dict[str, Any] | None = None,
) -> Path:
    """Write the run record, gzipped, and return where it went.

    `curves` is the chart data from `charts.programme_levels_db`, stored so a chart can be
    redrawn without the extraction. It is optional only so a caller that genuinely wants the
    numbers and not the pictures can skip the cost.
    """
    path = Path(path)
    accepted = report.accepted
    document = {
        "fingerprint": Fingerprint(
            schema=SCHEMA,
            material_sha256=material_digest(material_path),
            material_path=str(material_path),
            params=repr(params),
            revision=_git_revision(),
            written_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ).to_json(),
        "material": {
            "name": report.material.name,
            "fs": int(report.material.fs),
            "coverage": str(report.material.coverage),
            "channels": list(report.material.channels),
            "duration_s": round(report.material.duration_s, 3),
        },
        "diagnosis": _diagnosis(report.diagnosis),
        "identification": (
            None if report.identification is None else str(report.identification)
        ),
        "publication": {
            "parameter_decimals": {"freq_hz": 2, "gain_db": 3, "q": 4},
            "realisation": asdict(params.realisation),
        },
        "evidence_notes": list(report.evidence_notes),
        "candidates": [_candidate(c) for c in report.candidates],
        "accepted": None if accepted is None else accepted.label,
        "curves": curves,
        "timings": {
            "total_s": round(report.timings.total_s, 3),
            "stages": [[n, round(s, 3)] for n, s in report.timings.stages],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(document, handle)
    logger.info(f"  record: {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return path


def read(path: Path | str) -> dict[str, Any]:
    """The record as written. Arrays come back as lists; callers wrap what they need."""
    with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
        return json.load(handle)


def curves_from(
    material: Material, filters_by_label: dict[str, list[BiquadSpec]], names
):
    """Chart curves for every signal, unfiltered once and filtered per candidate.

    The unfiltered curves do not depend on the candidate, so they are stored once; the
    filtered ones are the cross product and are what make a redraw exact rather than an
    approximation of what a magnitude model would have shown.
    """
    from scipy import signal as scipy_signal

    from beqanalyser.design.charts import programme_levels_db
    from beqanalyser.design.filters import biquad_sos

    fs = float(material.fs)
    signals = {"mono": material.mono_mix}
    signals.update({n: material.channels[n] for n in names if n in material.channels})

    unfiltered: dict[str, Any] = {}
    freqs: list[float] | None = None
    for name, samples in signals.items():
        levels = programme_levels_db(samples, fs)
        freqs = freqs or _arr(levels.freqs)
        unfiltered[name] = {
            "peak": _arr(levels.peak),
            "average": _arr(levels.average),
            "loudest_second": _arr(levels.loudest_second),
            "loudest_index": int(levels.loudest_index),
        }

    filtered: dict[str, dict[str, Any]] = {}
    for label, specs in filters_by_label.items():
        sos = biquad_sos(specs, fs)
        filtered[label] = {}
        for name, samples in signals.items():
            levels = programme_levels_db(
                scipy_signal.sosfilt(sos, samples),
                fs,
                frame_index=unfiltered[name]["loudest_index"],
            )
            filtered[label][name] = {
                "peak": _arr(levels.peak),
                "average": _arr(levels.average),
                "loudest_second": _arr(levels.loudest_second),
            }
    return {"freqs": freqs, "unfiltered": unfiltered, "filtered": filtered}
