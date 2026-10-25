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


def _touch(feature: str, kind: str, **counts: tuple[int, int]) -> impact.Touch:
    return impact.Touch(
        feature, kind, {k: counts.get(k, (0, 1)) for k in impact.OUTCOMES}
    )


def _behaviour(feature: str, **counts: tuple[int, int]) -> impact.Touch:
    return _touch(feature, "behaviour", **counts)


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
            'feature = "fit.choice"\nkind = "behaviour"\nbasis = { no_fit = [1, 2] }',
            "needs a basis",
        ),
        (
            (
                'feature = "fit.choice"\nkind = "behaviour"\nbasis = { no_fit = [3, 2], '
                "declined_after_fit = [0, 1], designed_with_failures = [0, 1], "
                "designed_all_passed = [0, 1] }"
            ),
            "moved <= measured",
        ),
        (
            'feature = "fit.choice"\nkind = "threshold"\nold = 1.0\nnew = 2.0',
            "records no margin",
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
        assert found[0] == "unknown_build"
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
    "record, code, because",
    [
        (_record(settings="0123456789ab"), "other_settings", "other settings"),
        (_record(settings=None), "other_settings", "settings"),
        (_record(version=8), "newer_version", "newer"),
        (
            _record(version=5),
            "older_than_data",
            "older than this designer's impact data",
        ),
        ({"candidates": []}, "not_a_record", "not a beqforge run record"),
        (
            _record(version=None, revision="unknown+src:c1ae12bafc27"),
            "unknown_build",
            "does not know",
        ),
    ],
)
def test_what_cannot_be_scored_is_unknown_never_left_out(record, code, because) -> None:
    found = impact.assess(record, (7, SETTINGS), _data())
    assert found.tier == "unknown" and found.score is None
    assert found.unknown_reason == code
    assert because in found.reasons[0].detail


def test_a_behaviour_change_scores_by_the_share_of_its_class_that_moved() -> None:
    data = _data(
        _behaviour("fit.choice", declined_after_fit=(4, 5), designed_all_passed=(1, 5))
    )
    declined = _record([_candidate("flatten", False, ("tilts +3 dB/oct",))])
    designed = _record([_candidate("flatten", True)], "flatten")
    first = impact.assess(declined, (7, SETTINGS), data)
    assert (first.tier, first.score, first.from_design_version) == ("likely", 0.8, 6)
    assert (first.reasons[0].change, first.reasons[0].feature) == (
        "a-change",
        "fit.choice",
    )
    assert "4 of 5 such designs moved" in first.reasons[0].detail
    second = impact.assess(designed, (7, SETTINGS), data)
    assert (second.tier, second.score) == ("possible", 0.2)


def test_changes_combine_as_independent_chances_of_moving() -> None:
    """A score is an estimated probability, so two halves make three quarters, not one half."""
    data = impact.ImpactData(
        5,
        (),
        tuple(
            impact.Change(
                name, version, "s", (_behaviour(feature, designed_all_passed=(1, 2)),)
            )
            for name, version, feature in (
                ("six", 6, "fit.choice"),
                ("seven", 7, "fit.search"),
            )
        ),
    )
    record = _record([_candidate("flatten", True)], "flatten", version=5)
    found = impact.assess(record, (7, SETTINGS), data)
    assert (found.tier, found.score) == ("likely", 0.75)
    assert [r.change for r in found.reasons] == ["six", "seven"]


def test_a_design_declined_before_the_fit_does_not_rely_on_it() -> None:
    data = _data(_behaviour("fit.choice", **dict.fromkeys(impact.OUTCOMES, (1, 1))))
    found = impact.assess(_record(), (7, SETTINGS), data)
    assert found.tier == "unaffected"


def test_a_change_reaching_every_design_is_at_least_likely() -> None:
    data = _data(_touch("analysis.input", "all", no_fit=(1, 4)))
    found = impact.assess(_record(), (7, SETTINGS), data)
    assert (found.tier, found.score) == ("likely", 0.25)


def test_an_unchanged_touch_scores_nothing() -> None:
    data = _data(impact.Touch("fit.input", "unchanged", note="plumbing"))
    found = impact.assess(
        _record([_candidate("flatten", True)], "flatten"), (7, SETTINGS), data
    )
    assert found.tier == "unaffected"


def test_only_changes_after_the_records_version_count() -> None:
    data = impact.ImpactData(
        5,
        (),
        (
            impact.Change(
                "six",
                6,
                "s",
                (_touch("analysis.input", "all", designed_all_passed=(1, 1)),),
            ),
            impact.Change(
                "seven",
                7,
                "s",
                (_behaviour("fit.choice", designed_all_passed=(3, 10)),),
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


# -- a threshold, from the margins each recorded fit scored

CLIFF = impact.Touch("judge.cliff", "threshold", old=2.0, new=2.5)
CLIFF_FAILURE = "introduces a cliff of 40 dB/oct"


def _fit(
    cliff: float,
    passed: bool,
    *,
    kept: bool,
    answer: bool = True,
    failures=(),
    lift=3.0,
):
    return {
        "sections": 2,
        "error_db": 0.4,
        "answer": answer,
        "kept": kept,
        "passed": passed,
        "failures": list(failures),
        "margins": {"cliff": cliff, "tilt": 0.5},
        "lift_db": lift,
    }


def _fitted(label: str, *options: dict) -> dict:
    kept = next(o for o in options if o["kept"])
    return {
        "label": label,
        "verdict": {"passed": kept["passed"], "failures": kept["failures"]},
        "fit_options": list(options),
    }


def _scored(*candidates: dict, accepted=None) -> impact.Assessment:
    record = _record(list(candidates), accepted, params=repr(PipelineParams()))
    return impact.assess(record, (7, SETTINGS), _data(CLIFF))


def test_a_threshold_that_flips_the_winners_verdict_will_move() -> None:
    found = _scored(_fitted("flatten", _fit(2.2, True, kept=True)), accepted="flatten")
    assert (found.tier, found.score) == ("will_move", 1.0)
    assert "the winner" in found.reasons[0].detail


def test_a_threshold_that_flips_nothing_leaves_the_design_unaffected() -> None:
    found = _scored(_fitted("flatten", _fit(0.4, True, kept=True)), accepted="flatten")
    assert found.tier == "unaffected"


def test_a_decline_designs_when_a_fit_failing_only_that_check_passes() -> None:
    alone = _scored(
        _fitted("flatten", _fit(2.3, False, kept=True, failures=(CLIFF_FAILURE,)))
    )
    assert alone.tier == "will_move"
    also_tilt = _scored(
        _fitted(
            "flatten",
            _fit(2.3, False, kept=True, failures=(CLIFF_FAILURE, "tilts +4.0 dB/oct")),
        )
    )
    assert also_tilt.tier == "unaffected"


def test_an_earlier_fit_that_now_passes_would_be_kept_instead() -> None:
    """TODO 32's choice: the fewest-section fit failed only the cliff, so it is kept now."""
    candidate = _fitted(
        "flatten",
        _fit(2.4, False, kept=False, answer=False, failures=(CLIFF_FAILURE,)),
        _fit(0.3, True, kept=True),
    )
    assert _scored(candidate, accepted="flatten").tier == "will_move"
    lifts_little = _fitted(
        "flatten",
        _fit(2.4, False, kept=False, answer=False, failures=(CLIFF_FAILURE,), lift=1.0),
        _fit(0.3, True, kept=True),
    )
    assert _scored(lifts_little, accepted="flatten").tier == "unaffected"


def test_a_loser_that_now_passes_cannot_be_ranked_from_the_record() -> None:
    found = _scored(
        _fitted("flatten", _fit(0.3, True, kept=True)),
        _fitted(
            "counterfactual/25dB",
            _fit(2.3, False, kept=True, failures=(CLIFF_FAILURE,)),
        ),
        accepted="flatten",
    )
    assert (found.tier, found.unknown_reason) == ("unknown", "no_figure")
    assert "outranks flatten" in found.reasons[0].detail


def test_a_record_before_margins_cannot_score_a_threshold() -> None:
    found = _scored(_candidate("flatten", False, (CLIFF_FAILURE,)))
    assert (found.tier, found.unknown_reason) == ("unknown", "no_figure")
    assert (found.reasons[0].change, found.reasons[0].feature) == (
        "a-change",
        "judge.cliff",
    )


# -- whether a design moved


def _design(label: str | None, *filters: dict) -> dict:
    return {
        "accepted": label,
        "candidates": []
        if label is None
        else [{"label": label, "filters": list(filters)}],
    }


SHELF = {"type": "low_shelf", "freq_hz": 20.0, "gain_db": 10.0, "q": 0.7}


def test_moved_is_a_decision_a_strategy_or_more_than_a_db_of_cascade() -> None:
    nudged = {**SHELF, "gain_db": 10.5}
    shifted = {**SHELF, "gain_db": 12.0}
    assert impact.moved(_design(None), _design(None))[0] is False
    assert impact.moved(_design(None), _design("flatten", SHELF))[0] is True
    assert impact.moved(
        _design("flatten", SHELF), _design("counterfactual/25dB", SHELF)
    )[0]
    assert impact.moved(
        _design("counterfactual/25dB", SHELF), _design("counterfactual/45dB", SHELF)
    )[0]
    assert (
        impact.moved(_design("flatten", SHELF), _design("flatten", nudged))[0] is False
    )
    changed, how = impact.moved(_design("flatten", SHELF), _design("flatten", shifted))
    assert changed and "1.98 dB apart" in how


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
    data = _data(_behaviour("fit.choice", designed_all_passed=(3, 5)))
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
        "unknown_reason": "not_found",
    }
    assert body["results"][3]["unknown_reason"] == "unreadable"
    assert "unknown_reason" not in body["results"][1]
    assert body["changes"] == [
        {
            "design_version": 7,
            "id": "a-change",
            "summary": "what moved",
            "basis": [
                {"class": "no_fit", "measured": 1, "moved": 0},
                {"class": "declined_after_fit", "measured": 1, "moved": 0},
                {"class": "designed_with_failures", "measured": 1, "moved": 0},
                {"class": "designed_all_passed", "measured": 5, "moved": 3},
            ],
            "moved": impact.MOVED,
        }
    ]
    assert {k: body[k] for k in IDENTITY} == IDENTITY
    assert body["contract_version"] == "1.6"


def test_one_record_under_two_ids_is_answered_for_each(tmp_path) -> None:
    """Two library entries can name one record; each id gets its own result."""
    path = _write(tmp_path, "a.run.json.gz", _record(version=7))
    status, body = impact.answer(
        _ask(("x", path), ("y", path)), tmp_path, IDENTITY, _data()
    )
    assert status == 200
    assert [(r["id"], r["tier"]) for r in body["results"]] == [
        ("x", "unaffected"),
        ("y", "unaffected"),
    ]


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
    assert body["results"][0]["unknown_reason"] == "outside_root"


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
    data = _data(
        _touch("analysis.input", "all", no_fit=(1, 1)), version=DESIGN_VERSION + 1
    )
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
        + "basis = { no_fit = [0, 1], declined_after_fit = [0, 1], "
        + "designed_with_failures = [0, 1], designed_all_passed = [0, 1] }\n",
    )
    assert tool.check("base", "head") == 0


def test_check_refuses_code_no_feature_owns(monkeypatch, capsys) -> None:
    _fake_git(
        monkeypatch,
        {"beqforge/filters.py": (None, "def brand_new():\n    pass\n")},
        _TOML + '[[change.touches]]\nfeature = "fit.choice"\nkind = "unchanged"\n',
    )
    assert tool.check("base", "head") == 1
    assert "filters:brand_new changed and no feature owns it" in capsys.readouterr().out


def test_module_names_follow_the_packages() -> None:
    assert tool.module_name("beqforge/pipeline.py") == "pipeline"
    assert tool.module_name("beqforge/__init__.py") == "__init__"
    assert tool.module_name("beq_common/biquad.py") == "beq_common.biquad"
    assert tool.module_name("beq_common/__init__.py") == "beq_common"
