"""Versioned, hashed and reproducible measurement cases. No device I/O."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from beqforge import BiquadSpec
from beqforge_device_check import SCHEMA_VERSION
from beqforge_device_check.coefficients import (
    coefficients,
    published,
    response,
    rounded,
    settling_seconds,
    stable,
)
from beqforge_device_check.profiles import DeviceProfile


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def make_case(
    name: str,
    filters: list[BiquadSpec],
    profile: DeviceProfile,
    rate: int,
    route: str,
    channel: int,
    *,
    canonicalise: bool = True,
    gain_db: float = 0,
) -> dict:
    capacity = profile.route(route, channel, rate).sections
    sections = published(filters) if canonicalise else filters
    exact = coefficients(sections, rate)
    models = {}
    for model in ("float64", "float32", "fixed5.23"):
        try:
            values = rounded(exact, model)
            models[model] = {"sos": values.tolist(), "stable": stable(values)}
        except ValueError as error:
            models[model] = {"stable": False, "reason": str(error)}
    reason = None
    if len(sections) > capacity:
        reason = f"{len(sections)} sections exceed {route} capacity {capacity}"
    elif not stable(exact):
        reason = "exact cascade is unstable"
    elif (
        profile.coefficient_format != "unknown"
        and not models[profile.coefficient_format]["stable"]
    ):
        reason = f"unstable after {profile.coefficient_format} coefficient conversion"
    case = {
        "name": name,
        "continuous_filters": [asdict(s) for s in filters],
        "publication_filters": [asdict(s) for s in sections],
        "canonicalised": canonicalise,
        "rate": rate,
        "route": route,
        "channel": channel,
        "gain_db": gain_db,
        "gain_application": "reported_separately",
        "exact_sos": exact.tolist(),
        "storage_models": models,
        "status": "unsupported" if reason else "planned",
        "reason": reason,
        "settling_seconds": settling_seconds(exact, rate) if stable(exact) else None,
    }
    case["id"] = digest(case)
    return case


def freeze_levels(manifest: dict) -> dict[str, str]:
    worst = 0.0
    remapping = {}
    for case in manifest["cases"]:
        if case["status"] != "planned":
            continue
        sos = np.asarray(case.get("transport_sos", case["exact_sos"])).reshape(-1, 6)
        frequencies = np.geomspace(0.1, case["rate"] / 2 * 0.999, 8192)
        peak = 0.0
        for count in range(1, len(sos) + 1):
            peak = max(
                peak,
                float(
                    np.max(
                        20
                        * np.log10(
                            np.abs(response(sos[:count], frequencies, case["rate"]))
                        )
                    )
                ),
            )
        old_id = case["id"]
        case["predicted_intermediate_peak_db"] = peak
        case["id"] = digest({k: v for k, v in case.items() if k != "id"})
        remapping[old_id] = case["id"]
        worst = max(worst, peak)
    reduction = max(0.0, worst + 6 - 30)
    manifest["levels_dbfs"] = [-30 - reduction, -50 - reduction]
    manifest["level_screen"] = {
        "maximum_intermediate_gain_db": worst,
        "nominal_levels_dbfs": [-30, -50],
        "reduction_db": reduction,
        "margin_db": 6,
        "limitation": "sampled ideal transfer screen, not a proof of internal state headroom; capture clipping still aborts",
    }
    return remapping


def generate(
    profile: DeviceProfile,
    *,
    rate: int = 96000,
    route: str | None = None,
    channel: int = 0,
    suite: str = "pilot",
    seed: int = 101,
    repeats: int = 3,
) -> dict:
    route = route or profile.routes[0].name
    profile.route(route, channel, rate)
    if repeats < 3:
        raise ValueError("at least three independently loaded repeats are required")
    cases = [make_case("identity", [], profile, rate, route, channel)]
    specs = [
        ("benign", [BiquadSpec("peaking_eq", 60, 3, 0.707)]),
        ("sensitive", [BiquadSpec("peaking_eq", 5, 12, 6)]),
    ]
    if suite == "matrix":
        specs += [
            (f"{kind}-{frequency:g}-{q:g}", [BiquadSpec(kind, frequency, 12, q)])
            for kind in ("peaking_eq", "low_shelf")
            for frequency in (5, 10, 15, 20, 30, 60)
            for q in (0.707, 2, 5.2, 6, 8)
        ]
        for count in range(1, 5):
            for opposing in (False, True):
                cascade = [
                    BiquadSpec(
                        "peaking_eq", 10 + 5 * i, -9 if opposing and i % 2 else 9, 5.2
                    )
                    for i in range(count)
                ]
                specs.append((f"cascade-{count}-{opposing}", cascade))
                if count > 1:
                    specs.append(
                        (
                            f"cascade-{count}-{opposing}-reversed",
                            list(reversed(cascade)),
                        )
                    )
    elif suite != "pilot":
        raise ValueError("suite must be pilot or matrix")
    cases += [
        make_case(name, sections, profile, rate, route, channel)
        for name, sections in specs
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "profile": profile.as_dict(),
        "suite": suite,
        "seed": seed,
        "repeats": repeats,
        "levels_dbfs": [-30.0, -50.0],
        "identity_repeats": 5,
        "cases": cases,
        "order": [],
        "identity_bracket_every": 1,
        "protocol": "f2-electrical-v1",
    }
    freeze_levels(manifest)
    manifest["order"] = [case["id"] for case in cases[1:] for _ in range(repeats)]
    np.random.default_rng(seed).shuffle(manifest["order"])
    manifest["hash"] = digest(manifest)
    return manifest


def validate(manifest: dict) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported manifest schema")
    if manifest.get("hash") != digest(
        {k: v for k, v in manifest.items() if k != "hash"}
    ):
        raise ValueError("manifest hash mismatch")
    profile = DeviceProfile.from_dict(manifest["profile"])
    ids = set()
    for case in manifest["cases"]:
        if case["id"] != digest({k: v for k, v in case.items() if k != "id"}):
            raise ValueError("case hash mismatch")
        if case["id"] in ids:
            raise ValueError("duplicate case id")
        ids.add(case["id"])
        profile.route(case["route"], case["channel"], case["rate"])
        filters = [BiquadSpec(**value) for value in case["publication_filters"]]
        if not np.array_equal(
            coefficients(filters, case["rate"]),
            np.asarray(case["exact_sos"]).reshape(-1, 6),
        ):
            raise ValueError("frozen coefficients disagree with published filters")
    if any(case_id not in ids for case_id in manifest["order"]):
        raise ValueError("order names an unknown case")
