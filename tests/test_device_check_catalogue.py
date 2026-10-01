import json

from beqforge_device_check.catalogue import import_snapshot
from beqforge_device_check.manifest import validate
from beqforge_device_check.profiles import PROFILES


def test_snapshot_dedup_inventory_gain_and_unsupported(tmp_path):
    filters = [{"type": "LowShelf", "freq": 20, "gain": 5, "q": 0.707, "count": 1}]
    records = [
        {"digest": "a", "title": "One", "filters": filters, "mv": -5},
        {"digest": "b", "title": "Other version", "filters": filters, "mv": -5},
        {"digest": "c", "title": "Too many", "filters": [dict(filters[0], count=11)]},
        {
            "digest": "d",
            "title": "Missing Q",
            "filters": [{"type": "LowShelf", "freq": 20, "gain": 5}],
        },
    ]
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(records))
    manifest, inventory = import_snapshot(
        path,
        PROFILES["minidsp-2x4hd"],
        complete=True,
        attribution="test fixture",
        revision="fixture-v1",
    )
    validate(manifest)
    assert inventory["unique_cases"] == 2
    assert inventory["entries"][0]["case"] == inventory["entries"][1]["case"]
    assert inventory["entries"][0]["gain_db"] == -5
    assert inventory["entries"][2]["status"] == "unsupported"
    assert inventory["entries"][3]["status"] == "unsupported"
    assert len(manifest["cases"][2]["publication_filters"]) == 11
    assert inventory["source"]["complete_snapshot_declared"]


def test_cached_ezbeq_coefficients_preserved_with_explicit_sign(tmp_path):
    from beqforge import BiquadSpec
    from beqforge_device_check.coefficients import coefficients

    sos = coefficients([BiquadSpec("peaking_eq", 30, 3, 1)], 96000)[0]
    filters = [
        {
            "type": "PeakingEQ",
            "freq": 30,
            "gain": 3,
            "q": 1,
            "biquads": {"96000": {"b": sos[:3].tolist(), "a": (-sos[4:]).tolist()}},
        }
    ]
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps([{"id": "test", "filters": filters}]))
    manifest, _ = import_snapshot(
        path, PROFILES["minidsp-2x4hd"], attribution="test", revision="1"
    )
    assert manifest["cases"][1]["transport_sos"] == [sos.tolist()]


def test_section_order_and_dedup_disabled(tmp_path):
    filters = [
        {"type": "PeakingEQ", "freq": frequency, "gain": 5, "q": 2}
        for frequency in (10, 20)
    ]
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            [
                {"id": "a", "filters": filters},
                {"id": "b", "filters": filters},
                {"id": "c", "filters": filters[::-1]},
            ]
        )
    )
    manifest, inventory = import_snapshot(
        path,
        PROFILES["minidsp-2x4hd"],
        attribution="test",
        revision="1",
        deduplicate=False,
    )
    assert inventory["unique_cases"] == 3
    validate(manifest)
