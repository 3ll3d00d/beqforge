"""Frozen ezbeq catalogue inventories; published filters are never refitted."""

import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from beq_common.types import BiquadSpec
from beqforge_device_check.coefficients import rounded, stable
from beqforge_device_check.manifest import digest, freeze_levels, generate, make_case
from beqforge_device_check.profiles import DeviceProfile, finite

TYPE_MAP = {
    "PeakingEQ": "peaking_eq",
    "LowShelf": "low_shelf",
    "HighShelf": "high_shelf",
}


def import_snapshot(
    path: Path,
    profile: DeviceProfile,
    *,
    rate: int = 96000,
    route: str | None = None,
    channel: int = 0,
    complete: bool = False,
    attribution: str,
    revision: str,
    deduplicate: bool = True,
) -> tuple[dict, dict]:
    if not attribution or not revision:
        raise ValueError("snapshot revision and licence/attribution are required")
    raw = path.read_bytes()
    records = json.loads(raw)
    if not isinstance(records, list):
        raise TypeError(
            "expected ezbeq database.json array; pages/shards must be resolved explicitly"
        )
    route = route or profile.routes[0].name
    # The catalogue keeps its population design: every cascade reloaded, both levels,
    # every cascade bracketed by identities.
    manifest = generate(
        profile,
        rate=rate,
        route=route,
        channel=channel,
        repeats=3,
        levels=(-30.0, -50.0),
        bracket_every=1,
    )
    manifest.pop("control", None)
    manifest.pop("control_repeats", None)
    manifest["suite"] = "catalogue"
    cases = [manifest["cases"][0]]
    seen = {}
    inventory = []
    for ordinal, record in enumerate(records):
        if not isinstance(record, dict):
            inventory.append(
                {
                    "id": f"invalid-{ordinal}",
                    "status": "unsupported",
                    "reason": "record is not an object",
                }
            )
            continue
        entry_id = str(record.get("digest") or record.get("id") or digest(record))
        item = {
            "id": entry_id,
            "ordinal": ordinal,
            "title": record.get("title", ""),
            "edition": record.get("edition", ""),
            "source_url": record.get("catalogue_url", ""),
            "id_source": "published"
            if record.get("digest") or record.get("id")
            else "snapshot-content-digest",
            "scope": "common published BEQ cascade on the selected single route",
            "source_record": record,
        }
        try:
            filters = record["filters"]
            if isinstance(filters, str):
                filters = json.loads(filters)
            if not isinstance(filters, list) or not filters:
                raise ValueError("missing/empty published filters")
            if any(
                key in record
                for key in ("channel_cascades", "channelFilters", "channel_scope")
            ):
                raise ValueError(
                    "channel-specific catalogue schema is unsupported; applicability must be resolved explicitly"
                )
            sections, sent = [], []
            has_all_coefficients = True
            for value in filters:
                if not isinstance(value, dict) or value.get("type") not in TYPE_MAP:
                    raise ValueError("unsupported filter type or malformed filter")
                if any(key in value for key in ("channels", "channel", "slope")):
                    raise ValueError(
                        "unsupported channel/slope field; no guessed applicability or Q"
                    )
                section = BiquadSpec(
                    TYPE_MAP[value["type"]],
                    finite(value["freq"], "frequency"),
                    finite(value["gain"], "gain"),
                    finite(value["q"], "Q"),
                )
                count = value.get("count", 1)
                if (
                    not isinstance(count, int)
                    or isinstance(count, bool)
                    or not 1 <= count <= 1000
                ):
                    raise ValueError("invalid filter count")
                sections.extend([section] * count)
                cached = value.get("biquads", {}).get(str(rate))
                if cached is None:
                    has_all_coefficients = False
                else:
                    if len(cached["b"]) != 3 or len(cached["a"]) != 2:
                        raise ValueError("invalid published coefficient lengths")
                    values = [
                        *(finite(x, "coefficient") for x in cached["b"]),
                        1,
                        *(-finite(x, "feedback coefficient") for x in cached["a"]),
                    ]
                    sent.extend([values] * count)
            case = make_case(
                str(record.get("title", entry_id)),
                sections,
                profile,
                rate,
                route,
                channel,
                canonicalise=False,
                gain_db=finite(record.get("mv", 0), "volume offset"),
            )
            if has_all_coefficients:
                case["transport_sos"] = sent
                case["transport_source"] = (
                    "published ezbeq coefficients, additive feedback converted to denominator convention"
                )
                if not stable(np.asarray(sent)) or (
                    profile.coefficient_format != "unknown"
                    and not stable(
                        rounded(np.asarray(sent), profile.coefficient_format)
                    )
                ):
                    case["status"], case["reason"] = (
                        "unsupported",
                        "published coefficient cascade is unstable at selected storage precision",
                    )
            else:
                case["transport_source"] = (
                    "RBJ coefficients at selected rate; no complete published coefficient set at this rate"
                )
            case["id"] = digest({k: v for k, v in case.items() if k != "id"})
            key = digest(
                {
                    k: case.get(k)
                    for k in (
                        "publication_filters",
                        "exact_sos",
                        "transport_sos",
                        "rate",
                        "route",
                        "channel",
                        "gain_db",
                        "gain_application",
                    )
                }
            )
            if deduplicate and key in seen:
                case_id = seen[key]
            else:
                case_id = case["id"]
                # Identical records without dedup still have unique manifest IDs.
                if any(existing["id"] == case_id for existing in cases):
                    case["source_ordinal"] = ordinal
                    case["id"] = digest({k: v for k, v in case.items() if k != "id"})
                    case_id = case["id"]
                cases.append(case)
                seen[key] = case_id
            item.update(
                {
                    "case": case_id,
                    "status": case["status"],
                    "reason": case["reason"],
                    "published_filters": [asdict(s) for s in sections],
                    "gain_db": case["gain_db"],
                }
            )
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            item.update({"status": "unsupported", "reason": str(error)})
        inventory.append(item)
    manifest["cases"] = cases
    remapping = freeze_levels(manifest)
    for item in inventory:
        if item.get("case") in remapping:
            item["case"] = remapping[item["case"]]
    manifest["order"] = [
        case["id"] for case in cases[1:] for _ in range(manifest["repeats"])
    ]
    np.random.default_rng(manifest["seed"]).shuffle(manifest["order"])
    source = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "revision": revision,
        "attribution": attribution,
        "complete_snapshot_declared": complete,
        "source_schema": "ezbeq database.json",
        "entries": len(records),
    }
    manifest["source"] = source
    manifest["hash"] = digest({k: v for k, v in manifest.items() if k != "hash"})
    return manifest, {
        "schema_version": 1,
        "source": source,
        "entries": inventory,
        "unique_cases": len(cases) - 1,
        "deduplicated": deduplicate,
    }


# A catalogue entry's predicted error is judged over the whole sweep band.
PREDICTION_BAND_HZ = (2.0, 200.0)
# Longer settling cannot be swept (measure's control bound); such entries are
# predicted but never sampled for hardware.
SAMPLE_MAX_SETTLING_S = 60.0


def predict(manifest: dict, inventory: dict, profile: DeviceProfile) -> dict:
    """Predicted coefficient error for every catalogue entry, without hardware.

    The coefficients ezbeq sends (published, else RBJ at the rate) rounded to the
    device's coefficient format, against the intended filter. The device check is what
    shows a unit plays rounded coefficients as predicted; this applies that to all.
    """
    from beqforge_device_check.coefficients import response

    if profile.coefficient_format == "unknown":
        raise ValueError(
            "the profile's coefficient format is unknown; nothing to predict"
        )
    frequencies = np.geomspace(*PREDICTION_BAND_HZ, 2048)
    cases = {}
    for case in manifest["cases"][1:]:
        if case["status"] != "planned":
            continue
        exact = np.asarray(case["exact_sos"]).reshape(-1, 6)
        sent = np.asarray(case.get("transport_sos", exact)).reshape(-1, 6)
        stored = rounded(sent, profile.coefficient_format)
        error = 20 * np.log10(
            np.abs(
                response(stored, frequencies, case["rate"])
                / response(exact, frequencies, case["rate"])
            )
        )
        worst = int(np.argmax(np.abs(error)))
        below = frequencies < 10
        sections = case["publication_filters"]
        cases[case["id"]] = {
            "worst_db": float(abs(error[worst])),
            "signed_worst_db": float(error[worst]),
            "worst_hz": float(frequencies[worst]),
            "below_10_hz_db": float(np.max(np.abs(error[below]))),
            "from_10_hz_db": float(np.max(np.abs(error[~below]))),
            "sections": len(sections),
            "lowest_hz": min(s["freq_hz"] for s in sections),
            "maximum_q": max(s["q"] for s in sections),
            "settling_seconds": case["settling_seconds"],
        }
    entries = []
    for item in inventory["entries"]:
        record = item.get("source_record", {})
        prediction = cases.get(item.get("case"))
        entries.append(
            {
                "id": item["id"],
                "case": item.get("case"),
                "title": item.get("title", ""),
                "edition": item.get("edition", ""),
                "year": record.get("year"),
                "author": record.get("author", ""),
                "url": item.get("source_url", ""),
                "status": item.get("status"),
                "reason": item.get("reason"),
                **(prediction or {}),
            }
        )
    return {
        "schema_version": 1,
        "source": inventory["source"],
        "profile": profile.id,
        "coefficient_format": profile.coefficient_format,
        "rate": manifest["cases"][0]["rate"],
        "band_hz": list(PREDICTION_BAND_HZ),
        "scope": "predicted from coefficients alone; hardware agreement is shown by the device check",
        "cases": cases,
        "entries": entries,
    }


def sample(manifest: dict, predictions: dict, count: int, *, worst: int = 5) -> dict:
    """A characterisation manifest of real cascades spread across the predicted error.

    Picks are evenly spaced through the predicted-error distribution of distinct
    cascades, plus the `worst` largest, so a hardware run checks the prediction where
    it is small, typical and extreme. Each is loaded once (one control reloaded), at
    -30 dBFS nominal, with an identity every four loads, like the generated suites.
    """
    usable = sorted(
        (
            (p["worst_db"], case_id)
            for case_id, p in predictions["cases"].items()
            if (p["settling_seconds"] or 0) <= SAMPLE_MAX_SETTLING_S
        ),
    )
    if count < 2 or len(usable) < count:
        raise ValueError(f"cannot sample {count} of {len(usable)} sweepable cascades")
    tail = [case_id for _, case_id in usable[-worst:]] if worst else []
    spread = [
        usable[int(index)][1]
        for index in np.linspace(0, len(usable) - 1 - len(tail), count - len(tail))
    ]
    chosen = list(dict.fromkeys(spread + tail))
    by_id = {case["id"]: case for case in manifest["cases"]}
    result = {
        key: value
        for key, value in manifest.items()
        if key not in ("cases", "order", "hash", "levels_dbfs", "level_screen")
    }
    result.update(
        {
            "suite": "catalogue-sample",
            "repeats": 1,
            "control_repeats": 3,
            "identity_bracket_every": 4,
            # Copies: freezing levels annotates cases, and the full manifest is not ours.
            "cases": copy.deepcopy([manifest["cases"][0], *(by_id[c] for c in chosen)]),
            "sample": {
                "count": len(chosen),
                "worst": worst,
                "of_sweepable_cascades": len(usable),
                "excluded_unsweepable": len(predictions["cases"]) - len(usable),
                "method": "evenly spaced through predicted worst error, plus the largest",
            },
        }
    )
    remapping = freeze_levels(result, (-30.0,))
    chosen = [remapping.get(c, c) for c in chosen]
    result["control"] = chosen[0]
    result["order"] = [c for c in chosen for _ in range(3 if c == chosen[0] else 1)]
    np.random.default_rng(result.get("seed", 101)).shuffle(result["order"])
    result["hash"] = digest({k: v for k, v in result.items() if k != "hash"})
    return result
