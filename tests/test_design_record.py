"""The run record and the beqdesigner export.

Two different jobs, deliberately two different files. The record is ours and has to be exact
and self-describing; the export is beqdesigner's and is allowed to drop what that tool cannot
show.

The export's schema is pinned here by assertion rather than by round-tripping through
beqdesigner, which cannot be imported — it pulls PyQt6 and qtawesome behind it. The keys below
are what `beqdesigner/src/main/python/model/codec.py` *reads*:

* `signaldata_from_json` — `_type` in {SingleChannelSignalData, SignalData}, `name`, `fs`,
  `data.avg`, `data.peak`, optional `filter`, `metadata`, `offset`
* `xydata_from_json` — `_type` in {MagnitudeData, XYData}, `name`, `x`, `y`
* `filter_from_json` — `CompleteFilter` needs `filters` and `description`; `LowShelf` and
  `HighShelf` need `fs`, `fc`, `q`, `gain`, `count`; `PeakingEQ` needs `fs`, `fc`, `q`, `gain`
  and takes no `count`

If beqdesigner moves, this test is where to look.
"""

import gzip
import json
import math

import pytest

from beqanalyser.design import beqd, record


@pytest.fixture
def a_record() -> dict:
    return {
        "material": {"name": "demo", "fs": 1000},
        "accepted": "flatten",
        "curves": {
            "freqs": [1.0, 2.0, 3.0],
            "unfiltered": {
                "mono": {
                    "average": [-60.0, -61.0, -62.0],
                    "peak": [-40.0, -41.0, -42.0],
                },
                "LFE": {
                    "average": [-70.0, -71.0, -72.0],
                    "peak": [-50.0, -51.0, -52.0],
                },
            },
            "filtered": {},
        },
        "candidates": [
            {
                "label": "flatten",
                "filters": [
                    {
                        "type": "low_shelf",
                        "freq_hz": 27.24,
                        "gain_db": 19.38,
                        "q": 0.681,
                    },
                    {"type": "peaking_eq", "freq_hz": 23.5, "gain_db": -8.9, "q": 5.4},
                ],
                "target_notes": ["a target note"],
                "mv_adjust_db": 19.4,
                "verdict": {
                    "passed": True,
                    "failures": [],
                    "notes": ["a verdict note"],
                },
            },
            {
                "label": "parametric",
                "filters": [
                    {
                        "type": "high_shelf",
                        "freq_hz": 52.9,
                        "gain_db": -3.25,
                        "q": 0.327,
                    }
                ],
                "target_notes": [],
                "mv_adjust_db": 0.0,
                "verdict": {"passed": False, "failures": ["not flat"], "notes": []},
            },
        ],
    }


def _written(tmp_path, a_record) -> list[dict]:
    with gzip.open(beqd.export(tmp_path / "p.beq", a_record)) as handle:
        return json.loads(handle.read().decode("utf-8"))


def test_the_export_is_gzipped_json_of_a_signal_list(tmp_path, a_record) -> None:
    signals = _written(tmp_path, a_record)
    assert isinstance(signals, list) and signals
    for signal in signals:
        assert signal["_type"] in {"SingleChannelSignalData", "SignalData"}
        assert {"name", "fs", "data", "offset"} <= signal.keys()
        for curve in signal["data"].values():
            assert curve["_type"] in {"MagnitudeData", "XYData"}
            assert {"name", "x", "y"} <= curve.keys()
            assert len(curve["x"]) == len(curve["y"])


def test_every_candidate_is_exported_including_the_rejected_ones(
    tmp_path, a_record
) -> None:
    """On the fourth title every candidate was rejected; those are what you want on screen."""
    names = [s["name"] for s in _written(tmp_path, a_record)]
    assert any("flatten" in n and "accepted" in n for n in names)
    assert any("parametric" in n for n in names)
    # and the underlying signal is there to look at, not just the designs
    assert any(n.endswith("LFE") for n in names)


def test_filter_sections_carry_what_beqdesigners_decoder_reads(
    tmp_path, a_record
) -> None:
    designs = [s for s in _written(tmp_path, a_record) if "filter" in s]
    assert designs
    for signal in designs:
        cascade = signal["filter"]
        assert cascade["_type"] == "CompleteFilter"
        assert {"filters", "description"} <= cascade.keys()
        for section in cascade["filters"]:
            assert section["_type"] in {"LowShelf", "HighShelf", "PeakingEQ"}
            assert {"fs", "fc", "q", "gain"} <= section.keys()
            # `count` is a Shelf argument; PeakingEQ's constructor does not take one
            assert ("count" in section) == (section["_type"] != "PeakingEQ")


def test_metadata_does_not_trip_their_loader(tmp_path, a_record) -> None:
    """`signaldata_from_json` reads `metadata['src']` before anything else.

    A missing key raises there and is logged as an exception on every load; an empty string
    fails `os.path.isfile` cleanly, which is what we want since we have no source file to
    point at.
    """
    for signal in _written(tmp_path, a_record):
        if "metadata" in signal:
            assert signal["metadata"]["src"] == ""
            assert "beqanalyser" in signal["metadata"]


def test_an_unknown_filter_type_is_refused_rather_than_guessed(
    tmp_path, a_record
) -> None:
    a_record["candidates"][0]["filters"] = [
        {"type": "all_pass", "freq_hz": 20.0, "gain_db": 0.0, "q": 1.0}
    ]
    with pytest.raises(ValueError, match="all_pass"):
        beqd.export(tmp_path / "bad.beq", a_record)


def test_a_record_without_curves_cannot_be_exported(tmp_path, a_record) -> None:
    a_record["curves"] = None
    with pytest.raises(ValueError, match="no curves"):
        beqd.export(tmp_path / "empty.beq", a_record)


def test_nan_survives_the_round_trip_as_nan(tmp_path) -> None:
    """NaN is not JSON, and it is meaningful here — an unmeasured floor is not zero."""
    assert record._num(math.nan) is None
    assert math.isnan(record._back(None))
    assert record._back(record._num(4.5)) == 4.5


def test_a_record_knows_when_it_is_stale(tmp_path) -> None:
    """The whole point. A cache that cannot say it is out of date is worse than none."""
    fingerprint = record.Fingerprint(
        schema=record.SCHEMA,
        material_sha256="abc",
        material_path="data/x.npz",
        params="PipelineParams()",
        revision=record._git_revision(),
        written_at="2026-01-01T00:00:00+00:00",
    )

    class Params:
        def __repr__(self) -> str:
            return "PipelineParams()"

    assert stale_reasons(fingerprint, Params(), "abc") == []
    assert any(
        "material has changed" in r for r in stale_reasons(fingerprint, Params(), "def")
    )

    class Other:
        def __repr__(self) -> str:
            return "PipelineParams(max_gain_db=30.0)"

    assert any(
        "parameters differ" in r for r in stale_reasons(fingerprint, Other(), "abc")
    )


def stale_reasons(fingerprint, params, digest):
    return record.stale_against(fingerprint, params, digest)


def test_a_different_schema_is_refused(tmp_path) -> None:
    fingerprint = record.Fingerprint(
        schema=record.SCHEMA + 1,
        material_sha256="abc",
        material_path="data/x.npz",
        params="PipelineParams()",
        revision=record._git_revision(),
        written_at="2026-01-01T00:00:00+00:00",
    )

    class Params:
        def __repr__(self) -> str:
            return "PipelineParams()"

    assert any(
        "schema" in r for r in record.stale_against(fingerprint, Params(), "abc")
    )


def test_a_dirty_tree_is_distinguishable_from_itself() -> None:
    """`git describe --dirty` gives one string however the tree is dirty.

    This tree is dirty most of the time, so a record written before an edit and one written
    after were indistinguishable by revision alone — the exact case the check exists for. The
    revision therefore carries a hash of the design sources.
    """
    revision = record._git_revision()
    assert "+src:" in revision
    digest = revision.split("+src:")[1]
    assert len(digest) == 12 and all(c in "0123456789abcdef" for c in digest)
    assert record._source_digest() == digest, "the digest must be stable within a run"


def test_ledger_preserves_unavailable_headroom(a_record):
    from tools.render_ledger import title_entry

    a_record["fingerprint"] = {"material_path": "data/demo.npz"}
    a_record["material"]["duration_s"] = 60.0
    candidate = a_record["candidates"][0]
    candidate["correction"] = {"band_hz": (5.0, 45.0)}
    candidate["verdict"].update(
        required_offset_db=None, recovered_fraction=None, shaping_fraction=None
    )
    assert title_entry(a_record)["offset_db"] is None


def test_ledger_entry_for_no_candidate_is_strict_json(a_record):
    """`NaN` is not JSON — `json.dumps` emits it anyway, and a browser's `JSON.parse` throws
    on it, which silently kills the whole page's rendering script, not just one title's entry.

    Reproduced: the "no candidate was ever constructed" fallback (R1 can block a title before
    any target is built, leaving `candidates: []`) once filled its missing band with
    `float("nan")` instead of `None`, and the resulting page rendered nothing at all — not an
    empty entry, the entire ledger, because one bad title's JSON broke `JSON.parse` for all of
    them. `record.py`'s own convention (`_json_float`) is `None`, which round-trips as `null`;
    this pins the ledger to the same rule.
    """
    from tools.render_ledger import title_entry

    a_record["fingerprint"] = {"material_path": "data/demo.npz"}
    a_record["material"]["duration_s"] = 60.0
    a_record["accepted"] = None
    a_record["candidates"] = []
    a_record["evidence_notes"] = ["no usable contiguous mix plateau; restoration withheld"]

    entry = title_entry(a_record)
    assert entry["status"] == "abstained"
    assert entry["band"] == [None, None]

    def reject(x):
        raise ValueError(f"non-finite constant in ledger entry: {x}")

    json.loads(json.dumps(entry), parse_constant=reject)


@pytest.fixture
def replay_document(tmp_path, a_record):
    from beqanalyser.design.pipeline import PipelineParams

    material = tmp_path / "demo.npz"
    material.write_bytes(b"original material")
    params = PipelineParams(strategies=("flatten",), exclude_bands_hz=((12.0, 14.0),))
    a_record["fingerprint"] = record.Fingerprint(
        schema=record.SCHEMA,
        material_sha256=record.material_digest(material),
        material_path=str(material),
        params=repr(params),
        revision=record._git_revision(),
        written_at="2026-01-01T00:00:00+00:00",
    ).to_json()
    a_record["material"]["duration_s"] = 60.0
    candidate = a_record["candidates"][0]
    candidate["correction"] = {"band_hz": (5.0, 45.0)}
    candidate["verdict"].update(
        required_offset_db=0.0, recovered_fraction=None, shaping_fraction=None
    )
    return a_record


@pytest.mark.parametrize("reader", ["replay", "ledger"])
@pytest.mark.parametrize("changed", [None, "material", "revision", "schema"])
def test_replay_uses_recorded_parameters_but_still_checks_provenance(
    tmp_path, monkeypatch, replay_document, reader, changed
):
    from pathlib import Path

    from tools import render_ledger, replay

    fingerprint = replay_document["fingerprint"]
    if changed == "material":
        Path(fingerprint["material_path"]).write_bytes(b"different material")
    elif changed == "revision":
        fingerprint["revision"] = "old revision"
    elif changed == "schema":
        fingerprint["schema"] += 1
    path = tmp_path / "demo.run.json.gz"
    with gzip.open(path, "wt") as handle:
        json.dump(replay_document, handle)
    charts = tmp_path / "charts"
    rendered = []

    def render(document, destination):
        rendered.append(document)
        return []

    if reader == "replay":
        monkeypatch.setattr(replay, "render_cached", render)
        monkeypatch.setattr(replay.sys, "argv", ["replay", str(path), "--charts", str(charts)])
        assert replay.main() == (0 if changed is None else 2)
    else:
        monkeypatch.setattr(render_ledger, "render_cached", render)
        result = render_ledger.render_title(path, charts, force=False)
        assert (result is not None) == (changed is None)
    assert bool(rendered) == (changed is None)
