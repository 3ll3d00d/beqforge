"""Versioned, hashed and reproducible measurement cases. No device I/O."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from beq_common.types import BiquadSpec
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


# Characterisation suites: one load per filter, swept rather than repeated.
SWEEP_GAIN_DB = 12.0
SWEEP_TYPES = ("low_shelf", "peaking_eq")
# Where each type is realistically used: nothing below 10 Hz.
REALISTIC_FREQUENCIES_HZ = {"low_shelf": (10.0, 60.0), "peaking_eq": (10.0, 60.0)}
# 1 Hz steps from each type's lowest realistic frequency to 20 Hz.
GRID_FREQUENCIES_HZ = {
    kind: tuple(float(f) for f in range(int(low), 21))
    for kind, (low, _) in REALISTIC_FREQUENCIES_HZ.items()
}
GRID_Q = 0.707
GRID_CENTRE_HZ = 10.0
# Qs people use in BEQ: shelves stay near Butterworth, peaks stay broad.
REALISTIC_QS = {
    "low_shelf": (0.5, 0.6, 0.707, 0.8, 0.9, 1.0),
    "peaking_eq": (0.5, 0.707, 1.0, 1.5, 2.0),
}
# Predicted float32 coefficient error targets spanning a 0.1 dB requirement.
BOUNDARY_TARGETS_DB = (0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0)


def predicted_error_db(
    sections: list[BiquadSpec], rate: int, low_hz: float = 2, high_hz: float = 200
) -> float:
    """Worst float32-coefficient departure from the exact cascade over the sweep band."""
    exact = coefficients(published(sections), rate)
    frequencies = np.geomspace(low_hz, high_hz, 1024)
    stored = response(rounded(exact, "float32"), frequencies, rate)
    return float(
        np.max(
            np.abs(20 * np.log10(np.abs(stored / response(exact, frequencies, rate))))
        )
    )


def sweep_name(spec: BiquadSpec) -> str:
    kind = "shelf" if spec.type == "low_shelf" else "peak"
    return f"{kind} {spec.freq_hz:g} Hz Q{spec.q:g} {spec.gain_db:+g} dB"


def grid_specs() -> list[BiquadSpec]:
    """A frequency sweep at one Q, then a Q sweep at one frequency, per filter type."""
    specs = []
    for kind in SWEEP_TYPES:
        for frequency in GRID_FREQUENCIES_HZ[kind]:
            specs.append(BiquadSpec(kind, frequency, SWEEP_GAIN_DB, GRID_Q))
        for q in REALISTIC_QS[kind]:
            spec = BiquadSpec(kind, GRID_CENTRE_HZ, SWEEP_GAIN_DB, q)
            if spec not in specs:
                specs.append(spec)
    return specs


def boundary_specs(rate: int) -> list[BiquadSpec]:
    """Filters whose predicted float32 error lands nearest each target, per type.

    Chosen offline from the coefficients alone, so the hardware run spends its sweeps
    either side of where coefficient rounding crosses the accuracy requirement. Only
    filters people use are candidates (`REALISTIC_FREQUENCIES_HZ`, `REALISTIC_QS`), so a target the pool
    cannot reach exactly gets its nearest realistic filter instead.
    """
    chosen = []
    for kind in SWEEP_TYPES:
        pool = []
        for frequency in np.geomspace(*REALISTIC_FREQUENCIES_HZ[kind], 40):
            for q in REALISTIC_QS[kind]:
                spec = BiquadSpec(kind, round(float(frequency), 2), SWEEP_GAIN_DB, q)
                exact = coefficients(published([spec]), rate)
                if not stable(exact) or not stable(rounded(exact, "float32")):
                    continue
                pool.append((predicted_error_db([spec], rate), spec))
        for target in BOUNDARY_TARGETS_DB:
            _, spec = min(
                pool, key=lambda item: abs(np.log(max(item[0], 1e-12) / target))
            )
            if spec not in chosen:
                chosen.append(spec)
    return chosen


def freeze_levels(
    manifest: dict, nominal: tuple[float, ...] = (-30.0, -50.0)
) -> dict[str, str]:
    worst = 0.0
    remapping = {}
    model = manifest.get("profile", {}).get("coefficient_format", "unknown")
    for case in manifest["cases"]:
        if case["status"] != "planned":
            continue
        sent = np.asarray(case.get("transport_sos", case["exact_sos"])).reshape(-1, 6)
        # Screen what the device will play, not only what is sent: storing float32
        # coefficients gave one catalogue cascade 16 dB more infrasonic gain than its
        # float64 ones (+48.8 against +32.5 dB), and that clipped the device.
        screened = [sent]
        if model in ("float32", "fixed5.23"):
            try:
                screened.append(rounded(sent, model))
            except ValueError:  # Out of the format's range: make_case reports it.
                pass
        frequencies = np.geomspace(0.1, case["rate"] / 2 * 0.999, 8192)
        peak = 0.0
        for sos in screened:
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
    # Headroom is set by the loudest nominal level; every level moves down together.
    reduction = max(0.0, worst + 6 + max(nominal))
    manifest["levels_dbfs"] = [float(level) - reduction for level in nominal]
    manifest["level_screen"] = {
        "maximum_intermediate_gain_db": worst,
        "nominal_levels_dbfs": [float(level) for level in nominal],
        "reduction_db": reduction,
        "margin_db": 6,
        "limitation": "sampled transfer screen of the sent and the device-stored coefficients, not a proof of internal state headroom; capture clipping, including a flat top below full scale, still aborts",
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
    repeats: int = 1,
    control_repeats: int = 3,
    levels: tuple[float, ...] = (-30.0,),
    bracket_every: int = 4,
) -> dict:
    """Freeze a suite's cases, levels and measurement order.

    Each filter is loaded `repeats` times; the first is a control loaded
    `control_repeats` times, so reload variability is still measured once rather than
    by repeating every filter. An identity is measured after every `bracket_every`
    filters to bound bench drift.
    """
    route = route or profile.routes[0].name
    profile.route(route, channel, rate)
    if repeats < 1 or control_repeats < 2 or bracket_every < 1 or not levels:
        raise ValueError(
            "need at least one load per filter, a reloaded control, a bracket interval"
            " and a level"
        )
    cases = [make_case("identity", [], profile, rate, route, channel)]
    specs = [
        ("benign", [BiquadSpec("peaking_eq", 60, 3, 0.707)]),
        ("sensitive", [BiquadSpec("peaking_eq", 5, 12, 6)]),
    ]
    if suite in ("grid", "boundary"):
        chosen = grid_specs() if suite == "grid" else boundary_specs(rate)
        specs = [(sweep_name(spec), [spec]) for spec in chosen]
    elif suite == "matrix":
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
        raise ValueError("suite must be pilot, grid, boundary or matrix")
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
        "control_repeats": control_repeats,
        "levels_dbfs": [],
        "identity_repeats": 5,
        "cases": cases,
        "order": [],
        "identity_bracket_every": bracket_every,
        "protocol": "f2-electrical-v1",
    }
    freeze_levels(manifest, tuple(levels))
    loaded = [c for c in cases[1:] if c["status"] == "planned"]
    manifest["control"] = loaded[0]["id"] if loaded else None
    manifest["order"] = [
        case["id"]
        for case in cases[1:]
        for _ in range(
            control_repeats if case["id"] == manifest["control"] else repeats
        )
    ]
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
