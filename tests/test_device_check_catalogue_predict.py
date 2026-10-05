import csv
import json
from pathlib import Path

from beqforge_device_check.cli import main
from beqforge_device_check.manifest import validate

BENCH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "device-check-examples"
    / "minidsp-2x4hd-usb-loopback.json"
)


def record(title: str, filters: list[tuple]) -> dict:
    return {
        "title": title,
        "digest": title.lower().replace(" ", "-"),
        "year": 2020,
        "author": "someone",
        "catalogue_url": f"https://example.invalid/{title}",
        "filters": [
            {"type": kind, "freq": freq, "gain": gain, "q": q}
            for kind, freq, gain, q in filters
        ],
    }


def test_catalogue_predict_flags_entries_and_writes_a_sweepable_sample(
    tmp_path, capsys
):
    records = [
        record("Gentle", [("LowShelf", 40, 3, 0.707)]),
        record("Typical", [("LowShelf", 15, 6, 0.707)] * 3),
        record("Deep", [("LowShelf", 11, 6, 0.707)] * 4 + [("PeakingEQ", 20, -3, 1)]),
        record(
            "Deep again", [("LowShelf", 11, 6, 0.707)] * 4 + [("PeakingEQ", 20, -3, 1)]
        ),
        record("Mid", [("LowShelf", 25, 4, 0.8), ("PeakingEQ", 30, 2, 1)]),
        {"title": "Empty", "filters": []},
    ]
    catalogue = tmp_path / "database.json"
    catalogue.write_text(json.dumps(records))
    out = tmp_path / "predicted"
    arguments = [
        "catalogue-predict",
        "--config",
        str(BENCH),
        "--catalogue",
        str(catalogue),
        "--revision",
        "test",
        "--attribution",
        "synthetic",
        "--out",
        str(out),
        "--sample",
        "3",
        "--worst",
        "1",
    ]
    assert main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    # Six entries, five with filters, four distinct cascades (two identical).
    assert result["entries"] == 6
    assert result["predicted"] == 5
    assert result["distinct_cascades"] == 4
    predictions = json.loads((out / "predictions.json").read_text())
    by_title = {e["title"]: e for e in predictions["entries"]}
    assert by_title["Deep"]["worst_db"] == by_title["Deep again"]["worst_db"]
    assert by_title["Deep"]["worst_db"] > by_title["Gentle"]["worst_db"]
    assert result["above_threshold"] == sum(
        e.get("worst_db", 0) > 1 for e in predictions["entries"]
    )
    with (out / "predictions.csv").open(encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 6
    page = (out / "report.html").read_text(encoding="utf-8")
    assert "Catalogue coefficient error" in page
    # Every predicted entry is a row that can be plotted from the shipped coefficients.
    assert page.count("<tr data-c=") == 5
    script = (out / "cascades.js").read_text()
    cascades = json.loads(script.removeprefix("window.CASCADES=").rstrip().rstrip(";"))
    assert len(cascades) == 4
    assert all(len(flat) % 5 == 0 for flat, _ in cascades)
    # The sample is a runnable manifest: three real cascades including the worst,
    # each loaded once, one control reloaded, one level.
    manifest = json.loads((out / "sample-cases.json").read_text())
    validate(manifest)
    assert manifest["suite"] == "catalogue-sample"
    assert len(manifest["cases"]) == 1 + 3
    assert len(manifest["order"]) == 3 + 2
    assert len(manifest["levels_dbfs"]) == 1
    worst_case = max(
        predictions["cases"], key=lambda c: predictions["cases"][c]["worst_db"]
    )
    assert worst_case in {c["id"] for c in manifest["cases"]}
