"""R2a step 3: a frozen build keys the stage cache on baked digests, or runs without it.

A frozen executable ships bytecode, not the `.py` sources the cache key digests. Before this,
the packaged `beqforge design` failed on its default cache with `FileNotFoundError`.
"""

import json
import logging

import pytest

from beqforge import cache as C
from beqforge import pipeline as P
from tests.test_design_strategy_config import inputs


def test_the_baked_map_is_the_digest_of_every_cached_module_set() -> None:
    """What the spec writes equals what an unfrozen build computes, set by set."""
    baked = C.bake_digests(P.cached_module_sets())
    for modules in P.cached_module_sets():
        assert baked["\0".join(modules)] == C.digest_of(modules)


def test_the_map_covers_every_caching_strategy() -> None:
    sets = P.cached_module_sets()
    assert C.ANALYSIS_MODULES in sets
    for strategy in P.STRATEGIES.values():
        if strategy.cache_modules is not None:
            assert strategy.cache_modules in sets


def test_frozen_keys_equal_unfrozen_keys(tmp_path, monkeypatch) -> None:
    material = inputs()[0]
    unfrozen = C.key_for("analysis", C.ANALYSIS_MODULES, material)
    baked = tmp_path / C.STAGE_DIGESTS_FILE
    baked.write_text(json.dumps(C.bake_digests(P.cached_module_sets())))
    monkeypatch.setattr(C, "_baked_digests_path", lambda: baked)
    monkeypatch.setattr(C.sys, "frozen", True, raising=False)
    # sources the frozen build would not have: reading one would be the old bug
    monkeypatch.setattr(C, "_digest_sources", lambda *_: pytest.fail("read sources"))
    assert C.key_for("analysis", C.ANALYSIS_MODULES, material) == unfrozen


def test_a_frozen_build_without_the_map_raises_rather_than_keying_on_nothing(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(C, "_baked_digests_path", lambda: tmp_path / "absent.json")
    monkeypatch.setattr(C.sys, "frozen", True, raising=False)
    with pytest.raises(C.CacheUnavailable):
        C.digest_of(C.ANALYSIS_MODULES)


def test_a_run_without_the_map_completes_uncached_and_says_so(
    tmp_path, monkeypatch, caplog
) -> None:
    material, diagnosis, envelopes, identification = inputs()
    monkeypatch.setattr(P, "diagnose", lambda *a: diagnosis)
    monkeypatch.setattr(P, "extract", lambda *a: envelopes)
    monkeypatch.setattr(P, "identify_rolloff", lambda *a: identification)
    monkeypatch.setattr(P, "passband_ripple_db", lambda *a, **k: None)
    monkeypatch.setattr(C, "_baked_digests_path", lambda: tmp_path / "absent.json")
    monkeypatch.setattr(C.sys, "frozen", True, raising=False)
    path = tmp_path / "title.cache.json.gz"
    with caplog.at_level(logging.WARNING, logger="beqforge.pipeline"):
        report = P.run(
            material,
            P.PipelineParams(strategies=("parametric",), max_sections=1),
            cache_path=path,
        )
    assert report.candidates
    assert not path.exists()
    warnings = [r for r in caplog.records if "without the stage cache" in r.message]
    assert len(warnings) == 1
