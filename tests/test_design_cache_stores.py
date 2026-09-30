"""R2a: the stage cache's two stores — the CLI's file per title, the server's entry per file.

Both must return exactly what they were given or nothing, and a reader must never see half
of what a writer is writing: the server and the CLI may share a directory, and a partial
entry read as a whole one is a wrong answer, not a slow one.
"""

import gzip
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from beqforge import cache as C
from tests.test_design_cache import analysis, analysis_key, material

STORES = {
    "file": lambda root: C.FileStore(root / "title.cache.json.gz"),
    "dir": lambda root: C.DirStore(root / "stages"),
}


@pytest.mark.parametrize("kind", STORES)
def test_each_store_round_trips_bit_for_bit(tmp_path, kind) -> None:
    store = STORES[kind](tmp_path)
    before = analysis()
    store.store("analysis", analysis_key(), C.analysis_to_json(before))
    after = C.analysis_from_json(store.load("analysis", analysis_key()))
    assert np.array_equal(after.diagnosis.mix_db, before.diagnosis.mix_db)
    assert np.array_equal(
        after.diagnosis.channels["LFE"].tracking,
        before.diagnosis.channels["LFE"].tracking,
    )


@pytest.mark.parametrize("kind", STORES)
def test_a_different_key_is_a_miss(tmp_path, kind) -> None:
    store = STORES[kind](tmp_path)
    store.store("analysis", analysis_key(), C.analysis_to_json(analysis()))
    assert store.load("analysis", analysis_key(material(seed=99))) is None


def test_the_directory_keeps_configurations_side_by_side(tmp_path) -> None:
    """A server restarted with another dial must not evict the first dial's entries."""
    store = C.DirStore(tmp_path)
    one, two = analysis_key(), analysis_key(material(seed=7))
    store.store("analysis", one, {"which": 1})
    store.store("analysis", two, {"which": 2})
    assert store.load("analysis", one) == {"which": 1}
    assert store.load("analysis", two) == {"which": 2}
    assert len(list((tmp_path / "analysis").iterdir())) == 2


def test_an_entry_holding_another_key_is_a_miss(tmp_path) -> None:
    """The file name is a hash of the key; the key inside is still checked."""
    store = C.DirStore(tmp_path)
    key = analysis_key()
    store.store("analysis", key, {"which": 1})
    path = store.entry("analysis", key)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(
            {"key": {**key, "stage": "tampered"}, "payload": {"which": 2}}, handle
        )
    assert store.load("analysis", key) is None


@pytest.mark.parametrize("kind", STORES)
def test_a_truncated_entry_is_a_miss(tmp_path, kind) -> None:
    store = STORES[kind](tmp_path)
    key = analysis_key()
    store.store("analysis", key, C.analysis_to_json(analysis()))
    path = store.path if kind == "file" else store.entry("analysis", key)
    path.write_bytes(path.read_bytes()[: path.stat().st_size // 2])
    assert store.load("analysis", key) is None


def test_the_pipeline_takes_a_store(tmp_path) -> None:
    from beqforge.pipeline import PipelineParams, analyse

    rng = np.random.default_rng(5)
    t = np.arange(60_000) / 1000
    programme = rng.standard_normal(t.size) * (1 + np.sin(2 * np.pi * t / 7))
    from beqforge.material import Material

    m = Material("m", 1000, programme, {"L": programme}, "complete_programme")
    store = C.DirStore(tmp_path)
    first = analyse(m, PipelineParams(), store)
    assert list((tmp_path / "analysis").iterdir())
    again = analyse(m, PipelineParams(), store)
    assert np.array_equal(first.diagnosis.mix_db, again.diagnosis.mix_db)


_WRITER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from beqforge import cache as C
    kind, root, rounds = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
    store = C.FileStore(root / "title.cache.json.gz") if kind == "file" else C.DirStore(root / "stages")
    key = {"schema": 1, "stage": "analysis", "material": "m", "params": [], "modules": "x"}
    payload = {"values": list(range(400_000))}
    for _ in range(rounds):
        store.store("analysis", key, payload)
    """
)


@pytest.mark.parametrize("kind", STORES)
def test_no_reader_ever_sees_a_partial_entry(tmp_path, kind) -> None:
    """A writer in another process rewrites a ~2 MB entry while this one reads in a loop."""
    store = STORES[kind](tmp_path)
    key = {
        "schema": 1,
        "stage": "analysis",
        "material": "m",
        "params": [],
        "modules": "x",
    }
    expected = {"values": list(range(400_000))}
    repo = Path(__file__).resolve().parents[1]
    writer = subprocess.Popen(
        [sys.executable, "-c", _WRITER, kind, str(tmp_path), "25"],
        cwd=repo,
        env={"PYTHONPATH": str(repo)},
    )
    loads = complete = 0
    while writer.poll() is None:
        loaded = store.load("analysis", key)
        loads += 1
        if loaded is not None:
            assert loaded == expected
            complete += 1
    assert writer.returncode == 0
    assert loads > 1
    assert store.load("analysis", key) == expected


@pytest.mark.parametrize("kind", STORES)
def test_entries_get_an_ordinary_files_permissions(tmp_path, kind) -> None:
    """Not `mkstemp`'s private 0600: another process, maybe another user, reads them."""
    import os

    store = STORES[kind](tmp_path)
    key = analysis_key()
    store.store("analysis", key, {"which": 1})
    path = store.path if kind == "file" else store.entry("analysis", key)
    umask = os.umask(0)
    os.umask(umask)
    assert path.stat().st_mode & 0o777 == 0o666 & ~umask
