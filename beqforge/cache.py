"""The stage cache — work that does not change kept so it need not be repeated.

The pipeline has seams. `diagnose`, `extract` and `identify` read the *material* and say what
is there; `parametric` turns that into a cascade; the remaining strategies and the acceptance
model read those and decide what to do about them. Only the last of those changes while the
acceptance model is being worked on, and only the fitter changes while the fitter is. Anything
upstream of the edit is being recomputed for nothing.

Measured across the four titles, at 1,586 s of pipeline time:

    target/parametric   403.2 s   25.4%
    diagnose etc.       116.9 s    7.4%
    ---------------------------------
    cacheable           520.1 s   32.8%

`parametric` is the expensive one and the one that least needs repeating. What it contributes
is a *diagnosis* — does this look like a deliberate rolloff, and of what alignment and order —
which is a property of the material, not of the run. It is also the only strategy whose target
derivation runs an optimiser: `flatten` and `counterfactual` derive a curve in deterministic
numpy, `parametric` calls `design`, which calls the fitter. So "cache the strategy that fits"
is a line with a reason behind it rather than a special case, and `Strategy.cache_modules` is
where another strategy would declare itself onto the same footing.

**Staleness is per stage, and each stage names its own dependencies.** `record._source_digest`
hashes every module in `design/`, which is right for "would this code still draw this picture"
and wrong here: it would mean editing the fitter invalidates the analysis, which is exactly
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from beqanalyser.design import Alignment, BiquadSpec, HighPass
from beqanalyser.design.diagnose import ChannelDiagnosis, Diagnosis
from beqanalyser.design.extraction import Envelopes
from beqanalyser.design.identify import Identification
from beqanalyser.design.material import Material
from beqanalyser.design.rolloff import RolloffFit

logger = logging.getLogger(__name__)

SCHEMA = 1
"""Bumped when a stored field changes meaning. A mismatch is a miss, never an error."""

ANALYSIS_MODULES = (
    "design/__init__.py",
    "design/diagnose.py",
    "design/extraction.py",
    "design/identify.py",
    "design/material.py",
    "design/rolloff.py",
)
"""What `diagnose`, `extract` and `identify_rolloff` are computed by.

Deliberately excludes `filters`, `design`, `accept`, `verify`, `charts` and `pipeline`: they
consume the analysis and cannot change it. That exclusion is the point — it is what keeps the
analysis valid across an afternoon's work on the fitter.
"""

PARAMETRIC_MODULES = ANALYSIS_MODULES + (
    "__init__.py",
    "design/design.py",
    "design/filters.py",
    "design/pipeline.py",
)
"""What a parametric proposal is computed by — the analysis, plus the inversion and the fit.

`__init__.py` here is the **package root**, not `design/__init__.py`. `filters.py` imports
`LowShelf`, `HighShelf` and `PeakingEQ` from it, so the RBJ formulae that produce every
published cascade live outside `design/` entirely. `record._source_digest` globs `design/*.py`
and therefore cannot see them; a cache that inherited that blind spot would serve a cascade
built by superseded arithmetic and call it current.

`pipeline.py` is here because `parametric_targets` lives in it and builds the `DesignParams`.
It over-invalidates — editing `counterfactual_target` drops a parametric proposal that did not
depend on it — and that is the right direction to be wrong in.
"""


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def digest_of(modules: tuple[str, ...]) -> str:
    """SHA-256 over the named sources, first 12 hex. Paths are package-root relative."""
    root = _package_root()
    digest = hashlib.sha256()
    for name in modules:
        digest.update(name.encode("utf-8"))
        digest.update((root / name).read_bytes())
    return digest.hexdigest()[:12]


def material_fingerprint(material: Material) -> str:
    """SHA-256 over the samples themselves, not the file they arrived in.

    `record.material_digest` hashes the `.npz`, which is right for a record that names the
    path it was made from. Here the question is whether *these* samples are the ones the
    stage describes, and a `Material` need not have come from a file at all — the harness
    builds them and so do the tests. Hashing 488 MB costs 0.25 s against the 21-100 s a hit
    saves, so the exact answer is affordable and the cheap one is not worth its risk.
    """
    digest = hashlib.sha256()
    digest.update(material.name.encode("utf-8"))
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


# --- the file -----------------------------------------------------------------------------


def _read_document(path: Path) -> dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            document = json.load(handle)
        return document if isinstance(document, dict) else {}
    except (OSError, ValueError, EOFError):
        return {}


def load(path: Path | str | None, stage: str, key: dict[str, Any]) -> Any | None:
    """The stored payload for `stage`, or None with the reason logged.

    A miss is never an error. The reason is logged at INFO, because "why did that take a
    hundred seconds again" is a question a run should answer without being asked twice.
    """
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        return None
    entry = _read_document(path).get(stage)
    if not entry:
        return None
    stored = entry.get("key", {})
    moved = [name for name, value in key.items() if stored.get(name) != value]
    if moved:
        logger.info(f"  {stage}: cache stale ({', '.join(moved)} differ); recomputing")
        return None
    logger.info(f"  {stage}: reused from {path}")
    return entry["payload"]


def store(
    path: Path | str | None, stage: str, key: dict[str, Any], payload: Any
) -> None:
    """Write one stage, leaving the others in the file alone."""
    if path is None:
        return
    path = Path(path)
    document = _read_document(path) if path.is_file() else {}
    document[stage] = {"key": key, "payload": payload}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(document, handle)
    logger.info(f"  {stage}: cached to {path} ({path.stat().st_size / 1e6:.1f} MB)")
