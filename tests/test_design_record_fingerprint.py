"""R12: source dependency coverage and explicit handling of historical records."""

import gzip
import json
import subprocess
import sys

import pytest

from beqanalyser.design import cache, record
from tools import replay


def git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    # Real paths, isolated files: never mutate the working tree to test dirty fingerprints.
    root = tmp_path / "repository"
    for path in record._source_paths(record._repository_root()):
        relative = path.relative_to(record._repository_root())
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# fixture for {relative}\n")
    (root / "README.md").write_text("documentation\n")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "fixture",
    )
    monkeypatch.setattr(record, "_repository_root", lambda: root)
    monkeypatch.setattr(cache, "_package_root", lambda: root / "beqanalyser")
    return root


class RecordedParams:
    def __repr__(self):
        return "PipelineParams()"


def fingerprint(revision):
    return record.Fingerprint(
        record.SCHEMA,
        "abc",
        "missing.npz",
        "PipelineParams()",
        revision,
        "2026-09-15T00:00:00+00:00",
    )


def test_successive_rbj_edits_in_an_already_dirty_tree_are_distinct(source_tree):
    (source_tree / "README.md").write_text("already dirty\n")
    described = git(source_tree, "describe", "--always", "--dirty", "--abbrev=12")
    assert described.endswith("-dirty")
    revisions = [record._git_revision()]
    rbj = source_tree / "beqanalyser" / "__init__.py"
    for edit in ("first RBJ edit", "second RBJ edit"):
        rbj.write_text(edit)
        assert (
            git(source_tree, "describe", "--always", "--dirty", "--abbrev=12")
            == described
        )
        revisions.append(record._git_revision())
    assert len(set(revisions)) == 3
    for revision in revisions[:-1]:
        assert any(
            "code was" in reason
            for reason in record.stale_against(fingerprint(revision), RecordedParams())
        )
    assert record.stale_against(fingerprint(revisions[-1]), RecordedParams()) == []


@pytest.mark.parametrize(
    "relative",
    [
        "beqanalyser/design/filters.py",
        "beqanalyser/design/accept.py",
        "beqanalyser/design/charts.py",
        "beqanalyser/design/beqd.py",
        "tools/extract.py",
        "tools/design_beq.py",
        "tools/replay.py",
        "tools/render_ledger.py",
        "tools/ledger_template.html",
    ],
)
def test_record_arithmetic_and_presentation_dependencies_count(source_tree, relative):
    before = record._source_digest()
    (source_tree / relative).write_text("changed source\n")
    assert record._source_digest() != before


def test_new_design_modules_and_removal_count(source_tree):
    before = record._source_digest()
    module = source_tree / "beqanalyser/design/new_module.py"
    module.write_text("new arithmetic\n")
    assert record._source_digest() != before
    module.unlink()
    assert record._source_digest() == before
    (source_tree / "beqanalyser/design/verify.py").unlink()
    assert record._source_digest() != before


def test_missing_declared_dependency_cannot_silently_disappear(source_tree):
    (source_tree / "beqanalyser/__init__.py").unlink()
    with pytest.raises(FileNotFoundError):
        record._source_digest()


def test_unrelated_edits_follow_the_documented_policy(source_tree):
    readme = source_tree / "README.md"
    readme.write_text("first edit\n")
    before = record._git_revision()
    for relative in (
        "README.md",
        "tests/test_new.py",
        "beqanalyser/analyser.py",
        "tools/experiments/new.py",
        "tools/summarise.py",
    ):
        path = source_tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unrelated edit\n")
        assert record._git_revision() == before


def test_record_invalidation_does_not_evict_unaffected_analysis(source_tree):
    analysis = cache.digest_of(cache.ANALYSIS_MODULES)
    parametric = cache.digest_of(cache.PARAMETRIC_MODULES)
    for relative in ("beqanalyser/__init__.py", "beqanalyser/design/filters.py"):
        (source_tree / relative).write_text("changed arithmetic\n")
        assert cache.digest_of(cache.ANALYSIS_MODULES) == analysis
        changed = cache.digest_of(cache.PARAMETRIC_MODULES)
        assert changed != parametric
        parametric = changed
    before = record._source_digest()
    (source_tree / "beqanalyser/design/charts.py").write_text("changed chart\n")
    assert record._source_digest() != before
    assert cache.digest_of(cache.ANALYSIS_MODULES) == analysis
    assert cache.digest_of(cache.PARAMETRIC_MODULES) == parametric


@pytest.mark.parametrize("schema", [0, record.SCHEMA])
def test_legacy_record_requires_force_and_never_acquires_new_claims(
    tmp_path, monkeypatch, schema
):
    old = fingerprint("historical+src:old")
    document = {
        "fingerprint": dict(old.to_json(), schema=schema),
        "material": {"name": "legacy", "fs": 1000, "duration_s": 1.0},
        "accepted": None,
        "candidates": [
            {
                "label": "parametric",
                "filters": [],
                "target_db": [0.0],
                "verdict": {"passed": False, "failures": ["historical abstention"]},
            }
        ],
    }
    path = tmp_path / "legacy.run.json.gz"
    with gzip.open(path, "wt") as handle:
        json.dump(document, handle)
    assert record.read(path) == document
    drawn = []
    monkeypatch.setattr(
        replay, "render_cached", lambda data, directory: drawn.append(data) or []
    )
    argv = ["replay", str(path), "--charts", str(tmp_path / "charts")]
    monkeypatch.setattr(sys, "argv", argv)
    assert replay.main() == 2
    assert drawn == []
    monkeypatch.setattr(sys, "argv", argv + ["--force"])
    assert replay.main() == 0
    assert drawn == [document]
    assert record.read(path) == document
    assert "publication" not in drawn[0]
    assert "evidence_notes" not in drawn[0]
    assert "method" not in drawn[0]["candidates"][0]
    assert "effective_params" not in drawn[0]["candidates"][0]
