"""Frozen ezbeq catalogue inventories; published filters are never refitted."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from beqforge import BiquadSpec
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
    manifest = generate(profile, rate=rate, route=route, channel=channel)
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
