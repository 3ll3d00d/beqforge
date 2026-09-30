"""The stage cache — work that does not change kept so it need not be repeated.

The pipeline has seams. `diagnose`, `extract` and `identify` read the *material* and say what
is there; `parametric` turns that into a cascade; the remaining strategies and the acceptance
model read those and decide what to do about them. Only the last of those changes while the
acceptance model is being worked on, and only the fitter changes while the fitter is. Anything
upstream of the edit is being recomputed for nothing.

Measured over a set of real titles, the cacheable stages were about a third of pipeline time:
`parametric` roughly a quarter, `diagnose`/`extract`/`identify` most of the rest.

`parametric` is the expensive one and the one that least needs repeating. What it contributes
is a *diagnosis* — does this look like a deliberate rolloff, and of what alignment and order —
which is a property of the material, not of the run. It is also the only strategy whose target
derivation runs an optimiser: `flatten` and `counterfactual` derive a curve in deterministic
numpy, `parametric` calls `design`, which calls the fitter. So "cache the strategy that fits"
is a line with a reason behind it rather than a special case, and `Strategy.cache_modules` is
where another strategy would declare itself onto the same footing.

**Staleness is per stage, and each stage names its own dependencies.** `record._source_digest`
hashes design modules, root RBJ arithmetic and record/replay entry points, which is right for
"would this code still draw this picture" and wrong here: it would mean editing the fitter invalidates the analysis, which is exactly
the case a cache is for. `ANALYSIS_MODULES` and `PARAMETRIC_MODULES` are the correctness
argument, not a convenience — a module a stage can reach and that is not listed will leave a
stale answer looking fresh.

**Lossless, where `record.py` is lossy.** A record is read by `replay.py` to draw a picture,
so it rounds curves to three decimals — dB, against material that wobbles by several of them.
A cache is read by the *pipeline*, and what comes out of it feeds the target and therefore the
fit, so it may lose nothing at all. Arrays round-trip as raw float64 bytes and a cached run is
bit-identical to an uncached one. That is the whole claim; rounding here would quietly void it.
"""

import base64
import gzip
import hashlib
import json
import logging
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from beqforge import Alignment, BiquadSpec, HighPass
from beqforge.diagnose import ChannelDiagnosis, Diagnosis
from beqforge.extraction import Envelopes
from beqforge.identify import Identification
from beqforge.material import Material
from beqforge.rolloff import RolloffFit

logger = logging.getLogger(__name__)

SCHEMA = 2
"""Bumped when a stored field changes meaning. A mismatch is a miss, never an error."""

ANALYSIS_MODULES = (
    "__init__.py",
    "diagnose.py",
    "extraction.py",
    "identify.py",
    "material.py",
    "rolloff.py",
)
"""What `diagnose`, `extract` and `identify_rolloff` are computed by.

Deliberately excludes `filters`, `design`, `accept`, `verify`, `charts` and `pipeline`: they
consume the analysis and cannot change it. That exclusion is the point — it is what keeps the
analysis valid across an afternoon's work on the fitter.
"""

PARAMETRIC_MODULES = ANALYSIS_MODULES + (
    "biquad.py",
    "design.py",
    "filters.py",
    "pipeline.py",
    "verify.py",
)
"""What a parametric proposal is computed by — the analysis, plus the inversion and the fit.

`biquad.py` is here because `filters.py` imports `LowShelf`, `HighShelf` and `PeakingEQ` from
it — the RBJ formulae that produce every published cascade. Both this stage and the record
source fingerprint include it. The analysis does not depend on it and stays reusable when only
the RBJ arithmetic or fitting changes.

`pipeline.py` is here because `parametric_targets` lives in it and builds the `DesignParams`.
It over-invalidates — editing `counterfactual_target` drops a parametric proposal that did not
depend on it — and that is the right direction to be wrong in.

`verify.py` is here because the deficit a parametric target is capped at is measured against
`verify.house_curve_db`, the goal below the knee (IMPROVEMENT_PLAN C3).
"""


def _package_root() -> Path:
    return Path(__file__).resolve().parent


STAGE_DIGESTS_FILE = "STAGE_DIGESTS.json"
"""Written beside the package by `beqforge.spec`: each cached stage's module digest, baked."""


class CacheUnavailable(RuntimeError):
    """No trustworthy digest of the code a stage depends on, so no key: run uncached."""


def _module_set_name(modules: tuple[str, ...]) -> str:
    return "\0".join(modules)


def _digest_sources(modules: tuple[str, ...]) -> str:
    root = _package_root()
    digest = hashlib.sha256()
    for name in modules:
        digest.update(name.encode("utf-8"))
        digest.update((root / name).read_bytes())
    return digest.hexdigest()[:12]


def bake_digests(module_sets: list[tuple[str, ...]]) -> dict[str, str]:
    """What `beqforge.spec` writes to `STAGE_DIGESTS_FILE`, from the tree being built."""
    return {_module_set_name(m): _digest_sources(m) for m in module_sets}


def _baked_digests_path() -> Path:
    return _package_root() / STAGE_DIGESTS_FILE


def digest_of(modules: tuple[str, ...]) -> str:
    """SHA-256 over the named sources, first 12 hex. Paths are package-root relative.

    A frozen build ships bytecode, not sources, so it reads the digests `beqforge.spec` baked
    from the tree it was built from — identical to these by construction. Without them it
    raises `CacheUnavailable` rather than keying on nothing: before this the packaged
    `beqforge design` failed on its default cache with `FileNotFoundError` (IMPROVEMENT_PLAN
    R2a, step 3).
    """
    if not getattr(sys, "frozen", False):
        return _digest_sources(modules)
    try:
        baked = json.loads(_baked_digests_path().read_text(encoding="utf-8"))
    except (OSError, ValueError) as missing:
        raise CacheUnavailable(
            f"frozen build without {STAGE_DIGESTS_FILE}; stage cache disabled"
        ) from missing
    try:
        return baked[_module_set_name(modules)]
    except KeyError:
        raise CacheUnavailable(
            f"{STAGE_DIGESTS_FILE} has no digest for {', '.join(modules)}; "
            "stage cache disabled"
        ) from None


def material_fingerprint(material: Material) -> str:
    """SHA-256 over the samples themselves, not the file they arrived in.

    `record.material_digest` hashes the `.npz`, which is right for a record that names the
    path it was made from. Here the question is whether *these* samples are the ones the
    stage describes, and a `Material` need not have come from a file at all — the harness
    builds them and so do the tests. Hashing 488 MB costs 0.25 s against the 21-100 s a hit
    saves, so the exact answer is affordable and the cheap one is not worth its risk.

    The samples, not what they are called. No stage stores anything that depends on the
    material's name, so hashing it only stopped a renamed or moved file hitting — and every
    designer request is named "designer-request", whatever it carries (IMPROVEMENT_PLAN R2a).
    """
    digest = hashlib.sha256()
    digest.update(str(material.fs).encode("utf-8"))
    digest.update(str(material.coverage).encode("utf-8"))
    digest.update(memoryview(np.ascontiguousarray(material.mono_mix, dtype="<f8")))
    for name in sorted(material.channels):
        digest.update(name.encode("utf-8"))
        digest.update(
            memoryview(np.ascontiguousarray(material.channels[name], dtype="<f8"))
        )
    return digest.hexdigest()


def key_for(
    stage: str,
    modules: tuple[str, ...],
    material: Material,
    *params: object,
) -> dict[str, Any]:
    """Everything that decides whether a stored stage still describes this run."""
    return {
        "schema": SCHEMA,
        "stage": stage,
        "material": material_fingerprint(material),
        "params": [repr(p) for p in params],
        "modules": digest_of(modules),
    }


# --- array and scalar encoding ------------------------------------------------------------


def _pack(values: np.ndarray | None) -> dict[str, Any] | None:
    """An array as raw little-endian float64 bytes, base64'd. Lossless by construction."""
    if values is None:
        return None
    array = np.ascontiguousarray(values, dtype="<f8")
    return {
        "shape": list(array.shape),
        "b64": base64.b64encode(array.tobytes()).decode("ascii"),
    }


def _unpack(raw: dict[str, Any] | None) -> np.ndarray | None:
    if raw is None:
        return None
    flat = np.frombuffer(base64.b64decode(raw["b64"]), dtype="<f8")
    return flat.reshape(tuple(raw["shape"])).astype(np.float64, copy=True)


def _num(value: float | None) -> float | None:
    """NaN is not JSON, and NaN is meaningful here. It round-trips as null."""
    return None if value is None or math.isnan(value) else float(value)


def _back(value: float | None) -> float:
    return math.nan if value is None else float(value)


# --- the analysis stage -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Analysis:
    """What the first half of the pipeline produced."""

    diagnosis: Diagnosis
    envelopes: Envelopes
    identification: Identification | None


def _channel(channel: ChannelDiagnosis) -> dict[str, Any]:
    return {
        "name": channel.name,
        "response_db": _pack(channel.response_db),
        "share": _pack(channel.share),
        "share_se": _pack(channel.share_se),
        "tracking": _pack(channel.tracking),
        "level_spread_db": _pack(channel.level_spread_db),
        "contrast_db": _pack(channel.contrast_db),
        "contrast_se_db": _pack(channel.contrast_se_db),
        "max_slope_db_per_octave": _num(channel.max_slope_db_per_octave),
        "max_slope_hz": _num(channel.max_slope_hz),
        "passband_share": _num(channel.passband_share),
        "is_filtered": bool(channel.is_filtered),
        "plateau_hz": [_num(channel.plateau_hz[0]), _num(channel.plateau_hz[1])],
    }


def _channel_back(raw: dict[str, Any]) -> ChannelDiagnosis:
    return ChannelDiagnosis(
        name=str(raw["name"]),
        response_db=_unpack(raw["response_db"]),
        share=_unpack(raw["share"]),
        share_se=_unpack(raw.get("share_se")),
        tracking=_unpack(raw.get("tracking")),
        level_spread_db=_unpack(raw.get("level_spread_db")),
        contrast_db=_unpack(raw.get("contrast_db")),
        contrast_se_db=_unpack(raw.get("contrast_se_db")),
        max_slope_db_per_octave=_back(raw["max_slope_db_per_octave"]),
        max_slope_hz=_back(raw["max_slope_hz"]),
        passband_share=_back(raw["passband_share"]),
        is_filtered=bool(raw["is_filtered"]),
        plateau_hz=(_back(raw["plateau_hz"][0]), _back(raw["plateau_hz"][1])),
    )


def analysis_to_json(analysis: Analysis) -> dict[str, Any]:
    diagnosis, envelopes = analysis.diagnosis, analysis.envelopes
    found = analysis.identification
    return {
        "diagnosis": {
            "freqs": _pack(diagnosis.freqs),
            "mix_db": _pack(diagnosis.mix_db),
            "channels": [_channel(c) for c in diagnosis.channels.values()],
            "stratified": {k: _pack(v) for k, v in diagnosis.stratified.items()},
            "level_spread_db": _pack(diagnosis.level_spread_db),
            "filter_floor_hz": _num(diagnosis.filter_floor_hz),
            "noise_floor_hz": _num(diagnosis.noise_floor_hz),
        },
        "envelopes": {
            "freqs": _pack(envelopes.freqs),
            "mean_db": _pack(envelopes.mean_db),
            "peak_db": _pack(envelopes.peak_db),
            "quiet_db": _pack(envelopes.quiet_db),
            "coherence": _pack(envelopes.coherence),
            "reference_band_hz": list(envelopes.reference_band_hz),
            "loud_frames": int(envelopes.loud_frames),
            "quiet_frames": int(envelopes.quiet_frames),
            "total_frames": int(envelopes.total_frames),
            "margin_se_db": _pack(envelopes.margin_se_db),
            "confidence_computed": None
            if envelopes.confidence_computed is None
            else envelopes.confidence_computed.tolist(),
        },
        "identification": None
        if found is None
        else {
            "fit": {
                "corner_hz": float(found.fit.corner_hz),
                "slope_db_per_octave": float(found.fit.slope_db_per_octave),
                "knee": float(found.fit.knee),
                "residual_db": float(found.fit.residual_db),
            },
            "rolloff": None
            if found.rolloff is None
            else {
                "alignment": found.rolloff.alignment.value,
                "order": int(found.rolloff.order),
                "corner_hz": float(found.rolloff.corner_hz),
            },
            "improvement_db": float(found.improvement_db),
            "smooth_residual_db": float(found.smooth_residual_db),
            "weighted_bins": int(found.weighted_bins),
            "coherent_bandwidth_octaves": float(found.coherent_bandwidth_octaves),
            "min_improvement_db": float(found.min_improvement_db),
        },
    }


def analysis_from_json(raw: dict[str, Any]) -> Analysis:
    d, e = raw["diagnosis"], raw["envelopes"]
    diagnosis = Diagnosis(
        freqs=_unpack(d["freqs"]),
        mix_db=_unpack(d["mix_db"]),
        channels={c["name"]: _channel_back(c) for c in d["channels"]},
        stratified={k: _unpack(v) for k, v in d["stratified"].items()},
        level_spread_db=_unpack(d["level_spread_db"]),
        filter_floor_hz=_back(d["filter_floor_hz"]),
        noise_floor_hz=_back(d["noise_floor_hz"]),
    )
    envelopes = Envelopes(
        freqs=_unpack(e["freqs"]),
        mean_db=_unpack(e["mean_db"]),
        peak_db=_unpack(e["peak_db"]),
        quiet_db=_unpack(e["quiet_db"]),
        coherence=_unpack(e["coherence"]),
        reference_band_hz=tuple(e["reference_band_hz"]),
        loud_frames=int(e["loud_frames"]),
        quiet_frames=int(e["quiet_frames"]),
        total_frames=int(e["total_frames"]),
        margin_se_db=_unpack(e["margin_se_db"]),
        confidence_computed=None
        if e.get("confidence_computed") is None
        else np.asarray(e["confidence_computed"], dtype=bool),
    )
    found = raw["identification"]
    identification = None
    if found is not None:
        rolloff = found["rolloff"]
        identification = Identification(
            fit=RolloffFit(**found["fit"]),
            rolloff=None
            if rolloff is None
            else HighPass(
                alignment=Alignment(rolloff["alignment"]),
                order=int(rolloff["order"]),
                corner_hz=float(rolloff["corner_hz"]),
            ),
            improvement_db=float(found["improvement_db"]),
            smooth_residual_db=float(found["smooth_residual_db"]),
            weighted_bins=int(found["weighted_bins"]),
            coherent_bandwidth_octaves=float(found["coherent_bandwidth_octaves"]),
            min_improvement_db=float(found["min_improvement_db"]),
        )
    return Analysis(diagnosis, envelopes, identification)


# --- the proposal stage -------------------------------------------------------------------


def _spec(section: BiquadSpec) -> dict[str, Any]:
    return {
        "type": section.type,
        "freq_hz": float(section.freq_hz),
        "gain_db": float(section.gain_db),
        "q": float(section.q),
    }


def proposals_to_json(proposals: list) -> list[dict[str, Any]]:
    return [
        {
            "label": p.label,
            "method": p.method,
            "effective_params": p.effective_params,
            "target_db": _pack(p.target_db),
            "unpriced_target_db": _pack(p.unpriced_target_db),
            "filters": None if p.filters is None else [_spec(f) for f in p.filters],
            "residual_db": float(p.residual_db),
            "notes": list(p.notes),
        }
        for p in proposals
    ]


def proposals_from_json(raw: list[dict[str, Any]], factory) -> list:
    """Rebuild proposals. `factory` is `pipeline.Proposal`, passed to avoid a cycle."""
    return [
        factory(
            label=str(p["label"]),
            method=p.get("method"),
            effective_params=p.get("effective_params"),
            target_db=_unpack(p["target_db"]),
            unpriced_target_db=_unpack(p.get("unpriced_target_db")),
            filters=None
            if p["filters"] is None
            else [
                BiquadSpec(
                    str(f["type"]),
                    float(f["freq_hz"]),
                    float(f["gain_db"]),
                    float(f["q"]),
                )
                for f in p["filters"]
            ],
            residual_db=float(p["residual_db"]),
            notes=tuple(p["notes"]),
        )
        for p in raw
    ]


# --- the stores ---------------------------------------------------------------------------


class Store(Protocol):
    """Where stages are kept. `load` returns the payload or None, and never raises."""

    def load(self, stage: str, key: dict[str, Any]) -> Any | None: ...

    def store(self, stage: str, key: dict[str, Any], payload: Any) -> None: ...


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


def _write_atomic(path: Path, document: Any) -> None:
    """Write to a temporary name beside `path`, fsync, then rename over it.

    A reader sees the old file or the new one, never a partial one (IMPROVEMENT_PLAN R2a): a
    rename within one directory is atomic, and the fsync makes sure what is renamed is on disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        # `mkstemp` makes the file private (0600); a cache shared between processes, possibly
        # under different users, needs the mode an ordinary file would get here
        os.chmod(temporary, 0o666 & ~_umask())
        with os.fdopen(fd, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb") as zipped:
                zipped.write(json.dumps(document).encode("utf-8"))
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_document(path: Path) -> dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            document = json.load(handle)
        return document if isinstance(document, dict) else {}
    except (OSError, ValueError, EOFError):
        return {}


@dataclass(frozen=True, slots=True)
class FileStore:
    """One file per title, every stage in it — the CLI's layout, beside the material.

    Writing a stage reads the file, adds the stage and replaces the file atomically. Two
    writers on one title can still lose a stage (last one wins): that costs a recompute, never
    a wrong answer, so it is documented rather than locked.
    """

    path: Path

    def load(self, stage: str, key: dict[str, Any]) -> Any | None:
        if not self.path.is_file():
            return None
        entry = _read_document(self.path).get(stage)
        if not entry:
            return None
        stored = entry.get("key", {})
        moved = [name for name, value in key.items() if stored.get(name) != value]
        if moved:
            logger.info(
                f"  {stage}: cache stale ({', '.join(moved)} differ); recomputing"
            )
            return None
        logger.info(f"  {stage}: reused from {self.path}")
        return entry["payload"]

    def store(self, stage: str, key: dict[str, Any], payload: Any) -> None:
        document = _read_document(self.path) if self.path.is_file() else {}
        document[stage] = {"key": key, "payload": payload}
        _write_atomic(self.path, document)
        logger.info(
            f"  {stage}: cached to {self.path} ({self.path.stat().st_size / 1e6:.1f} MB)"
        )


@dataclass(frozen=True, slots=True)
class DirStore:
    """One file per entry under a directory: `<root>/<stage>/<sha256 of the key>.json.gz`.

    For the designer server, whose requests have no path to sit beside, and for several
    processes sharing one directory. The name is the key, so different configurations sit
    side by side — a server restarted with another goal dial does not evict the first one's
    entries. An entry is never rewritten with different content: two writers of one key write
    the same payload, so replacing an existing entry is harmless. `load` still compares the
    stored key, as a guard against a corrupt file or a hash collision. Never evicts.
    """

    root: Path

    def entry(self, stage: str, key: dict[str, Any]) -> Path:
        canonical = json.dumps(key, sort_keys=True, separators=(",", ":"))
        name = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return self.root / stage / f"{name}.json.gz"

    def load(self, stage: str, key: dict[str, Any]) -> Any | None:
        path = self.entry(stage, key)
        if not path.is_file():
            logger.info(f"  {stage}: no entry in {self.root}")
            return None
        document = _read_document(path)
        if document.get("key") != key:
            logger.info(f"  {stage}: entry in {self.root} unreadable or not this key")
            return None
        logger.info(f"  {stage}: reused from {path}")
        return document["payload"]

    def store(self, stage: str, key: dict[str, Any], payload: Any) -> None:
        path = self.entry(stage, key)
        _write_atomic(path, {"key": key, "payload": payload})
        logger.info(f"  {stage}: cached to {path} ({path.stat().st_size / 1e6:.1f} MB)")


def as_store(cache: "Path | str | Store | None") -> Store | None:
    """A path is today's per-title file; a store is used as it is; None is no cache."""
    if cache is None:
        return None
    if isinstance(cache, (str, Path)):
        return FileStore(Path(cache))
    return cache


def load(path: Path | str | None, stage: str, key: dict[str, Any]) -> Any | None:
    """The stored payload for `stage` in a per-title file, or None with the reason logged.

    A miss is never an error. The reason is logged at INFO, because "why did that take a
    hundred seconds again" is a question a run should answer without being asked twice.
    """
    return None if path is None else FileStore(Path(path)).load(stage, key)


def store(
    path: Path | str | None, stage: str, key: dict[str, Any], payload: Any
) -> None:
    """Write one stage to a per-title file, leaving the others in it alone."""
    if path is not None:
        FileStore(Path(path)).store(stage, key, payload)
