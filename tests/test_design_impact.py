"""Which designs a designer upgrade may move (TODO 34; designer-interface.md 1.6 §7.1, "Impact")."""

import dataclasses
import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from beqforge import impact
from beqforge.designer import (
    DESIGN_VERSION,
    DesignRequest,
    design,
    design_settings_digest,
)
from beqforge.pipeline import PipelineParams
from tools import impact as tool

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = design_settings_digest(PipelineParams())


def _candidate(label: str, passed: bool, failures: tuple[str, ...] = ()) -> dict:
    return {"label": label, "verdict": {"passed": passed, "failures": list(failures)}}


def _record(
    candidates: list[dict] | None = None,
    accepted: str | None = None,
    *,
    version: int | None = 6,
    settings: str | None = SETTINGS,
    revision: str = "abc123+src:def456",
    params: str = "",
) -> dict:
    document = {
        "fingerprint": {"schema": 1, "revision": revision, "params": params},
        "candidates": candidates or [],
        "accepted": accepted,
    }
    if version is not None:
        document["design_identity"] = {
            "design_version": version,
            "design_settings": settings,
        }
    return document


def _data(
    *touches: impact.Touch, version: int = 7, since: int = 6
) -> impact.ImpactData:
    return impact.ImpactData(
        since,
        (),
        (impact.Change("a-change", version, "what moved", tuple(touches)),),
    )


def _behaviour(feature: str, **degree: float) -> impact.Touch:
    return impact.Touch(
        feature, "behaviour", {k: degree.get(k, 0.0) for k in impact.OUTCOMES}
    )


# -- the catalogue


def _definitions() -> list[str]:
    paths = sorted(
        [*(ROOT / "beqforge").glob("*.py"), *(ROOT / "beq_common").glob("*.py")]
    )
    return [
        f"{tool.module_name(p.relative_to(ROOT).as_posix())}:{q}"
        for p in paths
        for q in impact.definitions(p.read_text(encoding="utf-8"))
    ]


def test_every_definition_belongs_to_a_feature() -> None:
    """The ownership map can't fall out of date: a new function needs an owner to be merged."""
    assert [q for q in _definitions() if not impact.owners(q)] == []


def test_a_literal_glob_owns_before_a_module_wildcard() -> None:
    assert [f.id for f in impact.owners("pipeline:<module>")] == ["reporting"]
    assert [f.id for f in impact.owners("filters:fit_near_equal_all")] == ["fit.choice"]
    assert [
        f.id for f in impact.owners("accept:AcceptParams.cliff_tolerance_db_per_octave")
    ] == ["judge.cliff"]
    assert impact.owners("nowhere:anything") == ()


def test_the_shipped_impact_data_loads() -> None:
    data = impact.load()
    assert data.changes[-1].design_version == DESIGN_VERSION
    assert all(c.design_version > data.since for c in data.changes)


@pytest.mark.parametrize(
    "touch, match",
    [
        ('feature = "no.such"\nkind = "all"', "unknown feature"),
        ('feature = "fit.choice"\nkind = "sideways"', "unknown kind"),
        (
            'feature = "fit.choice"\nkind = "behaviour"\ndegree = { no_fit = 0.5 }',
            "a degree",
        ),
        ('feature = "judge.cliff"\nkind = "threshold"\nold = 2.0', "old and new"),
    ],
)
def test_a_bad_declaration_is_refused(touch: str, match: str) -> None:
    text = (
        'since = 6\n[[change]]\nid = "x"\ndesign_version = 7\nsummary = "s"\n'
        f"[[change.touches]]\n{touch}\n"
    )
    with pytest.raises(ValueError, match=match):
        impact.parse(text)


# -- which design a record holds


def test_a_record_says_its_identity_itself() -> None:
    found = impact.record_identity(_record(version=6), impact.load())
    assert found == impact.RecordIdentity(6, SETTINGS)


@pytest.mark.parametrize(
    "revision, version",
    [
        (
            "517cc6930fd6+src:b5356b22f9fa (frozen build)",
            6,
        ),  # the Windows build of 0.2.10
        ("unknown+src:77edc1b4dc54", 6),  # 0.2.10's image or wheel: no git, its sources
        ("v0.2.9+src:anything", 5),
        (
            "517cc6930fd6-dirty+src:77edc1b4dc54",
            None,
        ),  # a development tree is not the release
        ("unknown+src:000000000000", None),
    ],
)
def test_an_older_record_is_recognised_by_the_release_that_wrote_it(
    revision, version
) -> None:
    record = _record(version=None, revision=revision, params=repr(PipelineParams()))
    found = impact.record_identity(record, impact.load())
    if version is None:
        assert isinstance(found, str)
    else:
        assert found == impact.RecordIdentity(version, SETTINGS)


def test_settings_are_read_from_the_params_a_record_was_designed_with() -> None:
    assert impact.settings_from_params(repr(PipelineParams())) == SETTINGS
    other = dataclasses.replace(
        PipelineParams(),
        accept=dataclasses.replace(PipelineParams().accept, goal_tolerance_db=2.0),
    )
    assert impact.settings_from_params(repr(other)) == design_settings_digest(other)
    assert impact.settings_from_params(repr(other)) != SETTINGS
    assert impact.settings_from_params("PipelineParams(nonsense") is None
    assert impact.settings_from_params("__import__('os').system('true')") is None


# -- scoring


def test_a_record_at_this_identity_is_unaffected_with_no_reasons() -> None:
    found = impact.assess(_record(version=7), (7, SETTINGS), _data())
    assert found == impact.Assessment("unaffected", 0.0, 7, ())


@pytest.mark.parametrize(
    "record, because",
    [
        (_record(settings="0123456789ab"), "other settings"),
        (_record(settings=None), "settings"),
        (_record(version=8), "newer"),
        (_record(version=5), "older than this designer's impact data"),
        ({"candidates": []}, "not a beqforge run record"),
    ],
)
def test_what_cannot_be_scored_is_unknown_never_left_out(record, because) -> None:
    found = impact.assess(record, (7, SETTINGS), _data())
    assert found.tier == "unknown" and found.score is None
    assert because in found.reasons[0].detail


def test_a_behaviour_change_scores_by_the_share_of_its_class_that_moved() -> None:
    data = _data(
        _behaviour("fit.choice", declined_after_fit=0.8, designed_all_passed=0.2)
    )
    declined = _record([_candidate("flatten", False, ("tilts +3 dB/oct",))])
    designed = _record([_candidate("flatten", True)], "flatten")
    first = impact.assess(declined, (7, SETTINGS), data)
    assert (first.tier, first.score, first.from_design_version) == ("likely", 0.8, 6)
    assert (
        first.reasons[0].change == "a-change"
        and first.reasons[0].feature == "fit.choice"
    )
    assert "80% of such designs moved" in first.reasons[0].detail
    second = impact.assess(designed, (7, SETTINGS), data)
    assert (second.tier, second.score) == ("possible", 0.2)


def test_a_design_declined_before_the_fit_does_not_rely_on_it() -> None:
    data = _data(_behaviour("fit.choice", **dict.fromkeys(impact.OUTCOMES, 1.0)))
    found = impact.assess(_record(), (7, SETTINGS), data)
    assert found.tier == "unaffected"


def test_a_change_reaching_every_design_is_at_least_likely() -> None:
    data = _data(impact.Touch("analysis.input", "all"))
    found = impact.assess(_record(), (7, SETTINGS), data)
    assert (found.tier, found.score) == ("likely", 1.0)


def test_an_unchanged_touch_scores_nothing() -> None:
    data = _data(impact.Touch("fit.input", "unchanged", note="plumbing"))
    found = impact.assess(
        _record([_candidate("flatten", True)], "flatten"), (7, SETTINGS), data
    )
    assert found.tier == "unaffected"


def test_a_threshold_needs_the_recorded_figure_or_says_it_cannot_score() -> None:
    data = _data(impact.Touch("judge.cliff", "threshold", old=2.0, new=2.5))
    record = _record([_candidate("flatten", False, ("introduces a cliff of 3",))])
    found = impact.assess(record, (7, SETTINGS), data)
    assert found.tier == "unknown"
    assert (found.reasons[0].change, found.reasons[0].feature) == (
        "a-change",
        "judge.cliff",
    )
    assert (
        "failed it: flatten" not in found.reasons[0].detail
    )  # the figure is what's missing


def test_a_recorded_figure_between_a_thresholds_values_will_move() -> None:
    touch = impact.Touch("judge.cliff", "threshold", old=2.0, new=2.5, near=0.5)
    assert impact._threshold(touch, impact.Reliance("x", "", 2.2)) == (1.0, True)
    near, sure = impact._threshold(touch, impact.Reliance("x", "", 2.75))
    assert not sure and impact.LIKELY <= near < 1.0
    assert impact._threshold(touch, impact.Reliance("x", "", 9.0)) == (0.1, False)


def test_only_changes_after_the_records_version_count() -> None:
    data = impact.ImpactData(
        5,
        (),
        (
            impact.Change("six", 6, "s", (impact.Touch("analysis.input", "all"),)),
            impact.Change(
                "seven", 7, "s", (_behaviour("fit.choice", designed_all_passed=0.3),)
            ),
        ),
    )
    found = impact.assess(
        _record([_candidate("flatten", True)], "flatten"), (7, SETTINGS), data
    )
    assert [r.change for r in found.reasons] == ["seven"]


def test_the_strategy_and_check_readers_say_what_the_record_shows() -> None:
    record = _record(
        [
            _candidate("flatten", True),
            _candidate("counterfactual/25dB", False, ("introduces a cliff of 9",)),
        ],
        "flatten",
    )
    assert "flatten won" in impact.feature("targets.flatten").reader(record).detail
    assert impact.feature("targets.parametric").reader(record) is None
    cliff = impact.feature("judge.cliff").reader(record)
    assert cliff.kind == "designed_with_failures"
    assert "failed it: counterfactual/25dB" in cliff.detail


# -- the endpoint


def _write(root: Path, name: str, document) -> str:
    path = root / "records" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(document, f)
    return f"records/{name}"


IDENTITY = {"design_version": 7, "design_settings": SETTINGS, "designer_build": "b"}


def _ask(*records: tuple[str, str]) -> dict:
    return {
        "contract_version": "1.6",
        "records": [{"id": i, "path": p} for i, p in records],
    }


def test_impact_answers_each_record_in_order_with_the_changes_since_the_oldest(
    tmp_path,
) -> None:
    data = _data(_behaviour("fit.choice", designed_all_passed=0.6))
    old = _write(
        tmp_path, "a.run.json.gz", _record([_candidate("flatten", True)], "flatten")
    )
    new = _write(tmp_path, "b.run.json.gz", _record(version=7))
    (tmp_path / "records" / "c.run.json.gz").write_bytes(b"not gzip")
    status, body = impact.answer(
        _ask(
            ("b", new),
            ("a", old),
            ("gone", "records/missing.run.json.gz"),
            ("c", "records/c.run.json.gz"),
        ),
        tmp_path,
        IDENTITY,
        data,
    )
    assert status == 200
    assert [r["id"] for r in body["results"]] == ["b", "a", "gone", "c"]
    assert [r["tier"] for r in body["results"]] == [
        "unaffected",
        "likely",
        "unknown",
        "unknown",
    ]
    assert body["results"][0]["reasons"] == []
    assert body["results"][1]["score"] == 0.6
    assert body["results"][2] == {
        "id": "gone",
        "tier": "unknown",
        "score": None,
        "from_design_version": None,
        "reasons": [{"change": None, "feature": None, "detail": "record not found"}],
    }
    assert body["changes"] == [
        {"design_version": 7, "id": "a-change", "summary": "what moved"}
    ]
    assert {k: body[k] for k in IDENTITY} == IDENTITY
    assert body["contract_version"] == "1.6"


def test_a_symlink_out_of_the_root_is_that_records_unknown(tmp_path) -> None:
    outside = tmp_path / "outside.run.json.gz"
    with gzip.open(outside, "wt") as f:
        json.dump(_record(version=7), f)
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.run.json.gz").symlink_to(outside)
    status, body = impact.answer(
        _ask(("x", "link.run.json.gz")), root, IDENTITY, _data()
    )
    assert status == 200
    assert body["results"][0]["tier"] == "unknown"
    assert "outside the root" in body["results"][0]["reasons"][0]["detail"]


@pytest.mark.parametrize(
    "body",
    [
        "not an object",
        {"contract_version": "1.5", "records": [{"id": "a", "path": "x"}]},
        {"contract_version": "1.6", "records": []},
        {"contract_version": "1.6", "records": [{"id": "a", "path": "x"}] * 2},
        _ask(*[(str(i), "x") for i in range(impact.MAX_RECORDS + 1)]),
        _ask(("a", "/etc/passwd")),
        _ask(("a", "records/../../x")),
        _ask(("a", "records\\x")),
        _ask(("a", "C:/x")),
        _ask(("", "x")),
        {"contract_version": "1.6", "records": [{"id": "a", "path": "x", "extra": 1}]},
    ],
)
def test_a_body_that_fails_the_schema_is_400(body, tmp_path) -> None:
    status, payload = impact.answer(body, tmp_path, IDENTITY, _data())
    assert status == 400 and "malformed impact request" in payload["error"]


def test_no_shared_root_is_422_naming_it() -> None:
    status, payload = impact.answer(_ask(("a", "x")), None, IDENTITY, _data())
    assert status == 422
    assert payload["reason"] == "no shared root is configured on this designer"


def test_a_real_record_scores_against_this_designer_and_a_later_one(
    tmp_path, monkeypatch
) -> None:
    """The record `design` writes holds what `/impact` reads: its identity, its outcome."""
    mono = np.random.default_rng(0).normal(scale=0.05, size=1000 * 60)
    request = DesignRequest(
        contract_version="1.6", fs=1000, mono_mix=mono, coverage="complete_programme"
    )
    response = design(request, record_dir=tmp_path / "records", shared_root=tmp_path)
    identity = {
        "design_version": DESIGN_VERSION,
        "design_settings": response.design_settings,
        "designer_build": "b",
    }
    status, body = impact.answer(_ask(("t", response.run_record)), tmp_path, identity)
    assert status == 200 and body["results"][0]["tier"] == "unaffected"
    later = {**identity, "design_version": DESIGN_VERSION + 1}
    data = _data(impact.Touch("analysis.input", "all"), version=DESIGN_VERSION + 1)
    status, body = impact.answer(
        _ask(("t", response.run_record)), tmp_path, later, data
    )
    assert body["results"][0]["tier"] == "likely"
    assert body["results"][0]["from_design_version"] == DESIGN_VERSION
    assert "declined before any fit" in body["results"][0]["reasons"][0]["detail"]


# -- which code changed


def test_docstrings_and_comments_are_not_changes() -> None:
    before = 'def f(x):\n    """Old."""\n    return x  # old\n'
    after = 'def f(x):\n    """New words."""\n    # a comment\n    return x\n'
    assert impact.changed(before, after) == set()
    assert impact.changed(before, "def f(x):\n    return x + 1\n") == {"f"}


def test_a_change_is_named_down_to_the_field_method_or_constant() -> None:
    before = (
        "import a\nLIMIT = 1\n"
        "class P:\n    x: float = 1.0\n    y: float = 2.0\n    def m(self):\n        return 1\n"
    )
    after = (
        "import a, b\nLIMIT = 2\n"
        "class P:\n    x: float = 1.5\n    y: float = 2.0\n    def m(self):\n        return 1\n"
        "def new():\n    pass\n"
    )
    assert impact.changed(before, after) == {"<module>", "LIMIT", "P.x", "new"}
    assert impact.changed(before, None) == set(impact.definitions(before))


def _fake_git(
    monkeypatch, files: dict[str, tuple[str | None, str | None]], toml: str
) -> None:
    designer = "DESIGN_VERSION = {}\n"
    sides = {
        "base": {
            **{p: b for p, (b, _) in files.items()},
            "beqforge/designer.py": designer.format(6),
        },
        "head": {
            **{p: a for p, (_, a) in files.items()},
            "beqforge/designer.py": designer.format(7),
            "beqforge/impact.toml": toml,
        },
    }
    monkeypatch.setattr(tool, "_show", lambda rev, path: sides[rev].get(path))
    monkeypatch.setattr(
        tool, "_git", lambda *args: "\n".join(files) if args[0] == "diff" else ""
    )


_TOML = 'since = 6\n[[change]]\nid = "x"\ndesign_version = 7\nsummary = "s"\n'


def test_check_refuses_an_answer_reaching_change_nobody_declared(
    monkeypatch, capsys
) -> None:
    _fake_git(
        monkeypatch,
        {
            "beqforge/filters.py": (
                "def _escalate():\n    return 1\n",
                "def _escalate():\n    return 2\n",
            )
        },
        _TOML + '[[change.touches]]\nfeature = "fit.input"\nkind = "unchanged"\n',
    )
    assert tool.check("base", "head") == 1
    assert "fit.choice changed (filters:_escalate)" in capsys.readouterr().out


def test_check_passes_a_declared_change(monkeypatch, capsys) -> None:
    _fake_git(
        monkeypatch,
        {
            "beqforge/filters.py": (
                "def _escalate():\n    return 1\n",
                "def _escalate():\n    return 2\n",
            )
        },
        _TOML
        + '[[change.touches]]\nfeature = "fit.choice"\nkind = "behaviour"\n'
        + "degree = { no_fit = 0, declined_after_fit = 0, designed_with_failures = 0, designed_all_passed = 0 }\n",
    )
    assert tool.check("base", "head") == 0


def test_check_refuses_code_no_feature_owns(monkeypatch, capsys) -> None:
    _fake_git(
        monkeypatch,
        {"beqforge/filters.py": (None, "def brand_new():\n    pass\n")},
        _TOML + '[[change.touches]]\nfeature = "fit.choice"\nkind = "all"\n',
    )
    assert tool.check("base", "head") == 1
    assert "filters:brand_new changed and no feature owns it" in capsys.readouterr().out


def test_module_names_follow_the_packages() -> None:
    assert tool.module_name("beqforge/pipeline.py") == "pipeline"
    assert tool.module_name("beqforge/__init__.py") == "__init__"
    assert tool.module_name("beq_common/biquad.py") == "beq_common.biquad"
    assert tool.module_name("beq_common/__init__.py") == "beq_common"
