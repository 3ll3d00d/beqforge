"""Automatic, immutable-result caching; catalogue metadata is never cached."""

import gzip
import hashlib
import json
import logging
import os
import platform
import sys
import tempfile
from dataclasses import asdict
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import numpy as np
import scipy

from beq_common import __version__

from . import core
from .core import FixedPoint, Float32, Precision, Result, Settings, stable

LOGGER = logging.getLogger(__name__)
CACHE_SCHEMA = 1


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def implementation_identity() -> dict:
    """Scope results to the numerical implementation and execution environment."""
    return {
        "schema": CACHE_SCHEMA,
        "version": __version__,
        "core": hashlib.sha256(
            files("beqoptimiser").joinpath("core.py").read_bytes()
        ).hexdigest(),
        "biquad": hashlib.sha256(
            files("beq_common").joinpath("biquad.py").read_bytes()
        ).hexdigest(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "system": platform.system(),
        "machine": platform.machine(),
        "byteorder": sys.byteorder,
        "longdouble_mantissa_bits": np.finfo(np.longdouble).nmant,
    }


def _precision_identity(precision: Precision | None):
    if precision is None:
        return {"type": "float64-transport"}
    kind = f"{type(precision).__module__}.{type(precision).__qualname__}"
    if type(precision) in (Float32, FixedPoint):
        return {"type": kind, "settings": asdict(precision)}
    identity = getattr(precision, "cache_identity", None)
    if callable(identity):
        return {"type": kind, "name": precision.name, "identity": identity()}
    # A format name alone cannot identify an arbitrary quantiser implementation.
    return None


def _request(
    reference, *, rate, precision=None, transport=None, sent=None, settings=None
):
    cfg, storage = settings or Settings(), precision or Float32()
    ref = np.array(reference, dtype=float, copy=True)
    original = np.array(ref if sent is None else sent, dtype=float, copy=True)
    if (
        rate not in (48000, 96000)
        or ref.ndim != 2
        or ref.shape[1] != 6
        or not len(ref)
        or original.shape != ref.shape
        or not np.all(np.isfinite(original))
        or not np.all(original[:, 3] == 1)
        or not stable(ref)
        or cfg.band_hz[1] >= rate / 2
    ):
        return None
    storage_id, transport_id = (
        _precision_identity(storage),
        _precision_identity(transport),
    )
    if storage_id is None or transport_id is None:
        return None
    payload = {
        "reference": ref.tolist(),
        "sent": original.tolist(),
        "rate": rate,
        "storage": storage.name,
        "transport": transport.name if transport else "float64",
        "settings": asdict(cfg),
        "version": __version__,
    }
    source = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    try:
        implementation = implementation_identity()
    except OSError:
        return None
    key = _digest(
        {
            "implementation": implementation,
            "request": payload,
            "storage_identity": storage_id,
            "transport_identity": transport_id,
        }
    )
    return key, source, ref, storage, transport, cfg, rate


def _encode(value):
    if isinstance(value, float) and not np.isfinite(value):
        return {
            "nonfinite": "nan" if np.isnan(value) else ("inf" if value > 0 else "-inf")
        }
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {"nonfinite"}:
            return float(value["nonfinite"])
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def _envelope(key: str, result: Result) -> dict:
    body = _encode(asdict(result))
    return {
        "schema": CACHE_SCHEMA,
        "key": key,
        "result": body,
        "checksum": _digest(body),
    }


def _restore(envelope: dict, request) -> Result:
    key, source, ref, storage, transport, cfg, rate = request
    if (
        envelope["schema"] != CACHE_SCHEMA
        or envelope["key"] != key
        or envelope["checksum"] != _digest(envelope["result"])
    ):
        raise ValueError("invalid cache envelope")
    body = _decode(envelope["result"])
    body["band_hz"] = tuple(body["band_hz"])
    if body["replacement"] is not None:
        body["replacement"] = tuple(tuple(row) for row in body["replacement"])
    result = Result(**body)
    if (
        result.source_digest != source
        or result.version != __version__
        or result.rate != rate
        or result.precision != storage.name
        or result.transport_precision != (transport.name if transport else "float64")
        or result.margin_db != cfg.margin_db
        or result.band_hz != cfg.band_hz
        or result.outcome
        not in ("within_margin", "replacement", "no_replacement", "unresolved")
        or np.isnan(result.original_error_db)
        or result.original_error_db < 0
        or result.evaluations < 0
    ):
        raise ValueError("cache result does not match request")
    if result.outcome == "within_margin" and (
        result.original_error_db > cfg.margin_db or result.evaluations != 0
    ):
        raise ValueError("invalid cached within-margin result")
    if result.outcome == "no_replacement" and result.original_error_db <= cfg.margin_db:
        raise ValueError("cached unsuccessful search was not licensed")
    if result.outcome == "replacement":
        rows = np.asarray(result.replacement, dtype=float)
        if (
            result.original_error_db <= cfg.margin_db
            or rows.shape != ref.shape
            or not stable(rows)
            or result.candidate_error_db is None
            or not np.isfinite(result.candidate_error_db)
            or not 0 <= result.candidate_error_db <= cfg.margin_db
            or abs(result.candidate_error_db - cfg.margin_db)
            < cfg.numerical_tolerance_db
            or result.guard_error_db is None
            or not np.isfinite(result.guard_error_db)
            or not 0 <= result.guard_error_db <= cfg.guard_margin_db
            or abs(result.guard_error_db - cfg.guard_margin_db)
            < cfg.numerical_tolerance_db
        ):
            raise ValueError("cached replacement violates publication policy")
        loaded = np.array(
            [[float(format(value, ".17g")) for value in row] for row in rows]
        )
        loaded = storage.quantise(transport.quantise(loaded) if transport else loaded)
        if not np.array_equal(loaded, rows):
            raise ValueError("cached replacement does not round-trip")
    elif result.replacement is not None:
        raise ValueError("unexpected cached replacement")
    return result


@lru_cache(maxsize=1)
def _bundled_entries() -> dict:
    try:
        raw = files("beqoptimiser").joinpath("data/seed.json.gz").read_bytes()
        document = json.loads(gzip.decompress(raw))
        if (
            document["schema"] == CACHE_SCHEMA
            and document["implementation"] == implementation_identity()
        ):
            return document["entries"]
    except (OSError, ValueError, KeyError, TypeError):
        LOGGER.debug("No compatible bundled optimiser seed", exc_info=True)
    return {}


class ResultCache:
    """Disk results plus a read-only seed shipped in the installed package.

    Writes use unique temporary files and atomic replacement, so concurrent callers
    cannot publish partial JSON. A damaged entry is a miss, never a replacement.
    """

    def __init__(self, directory: Path | str | None = None, *, use_seed: bool = True):
        if directory is None:
            directory = (
                os.environ.get("BEQOPTIMISER_CACHE_DIR")
                or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
                / "beqoptimiser"
            )
        self.directory = Path(directory)
        self.use_seed = use_seed

    def get(self, request) -> Result | None:
        key = request[0]
        try:
            result = _restore(
                json.loads((self.directory / f"{key}.json").read_text()), request
            )
            LOGGER.debug(f"Optimiser disk cache hit: {key}")
            return result
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            pass
        if self.use_seed:
            try:
                envelope = _bundled_entries().get(key)
                if envelope is not None:
                    result = _restore(envelope, request)
                    LOGGER.debug(f"Optimiser bundled cache hit: {key}")
                    return result
            except (ValueError, KeyError, TypeError, OverflowError):
                LOGGER.debug(
                    f"Ignoring invalid bundled cache entry: {key}", exc_info=True
                )
        return None

    def _write(self, envelope: dict) -> bool:
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.directory,
                prefix=".result-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(envelope, stream, allow_nan=False, separators=(",", ":"))
            temporary.replace(self.directory / f"{envelope['key']}.json")
            return True
        except OSError:
            LOGGER.debug(
                "Optimiser cache unavailable; returning uncached result", exc_info=True
            )
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    LOGGER.debug("Could not remove cache temporary file", exc_info=True)

    def seed(self, reference, result: Result, **kwargs) -> str:
        """Import an already validated result; raises on incompatible provenance/policy.

        Intended for trusted migrations, not importing arbitrary third-party claims.
        """
        request = _request(reference, **kwargs)
        if request is None:
            raise ValueError("request cannot be cached")
        envelope = _envelope(request[0], result)
        _restore(envelope, request)
        if not self._write(envelope):
            raise OSError(f"Cannot write optimiser cache: {self.directory}")
        return request[0]


def optimise(
    reference,
    *,
    rate: int,
    precision: Precision | None = None,
    transport: Precision | None = None,
    sent=None,
    settings: Settings | None = None,
    cache: ResultCache | bool | None = None,
) -> Result:
    """Optimise with automatic cache reuse; use cache=False for a fresh calculation."""
    kwargs = {
        "rate": rate,
        "precision": precision,
        "transport": transport,
        "sent": sent,
        "settings": settings,
    }
    if cache is False or os.environ.get("BEQOPTIMISER_CACHE") == "0":
        return core.optimise(reference, **kwargs)
    request = _request(reference, **kwargs)
    if request is None:
        return core.optimise(reference, **kwargs)
    store = cache if isinstance(cache, ResultCache) else ResultCache()
    result = store.get(request)
    if result is not None:
        return result
    result = core.optimise(reference, **kwargs)
    envelope = _envelope(request[0], result)
    _restore(envelope, request)
    store._write(envelope)
    return result
