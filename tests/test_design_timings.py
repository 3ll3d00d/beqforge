"""C5: a run accounts for its wall time, and keeps its own copy of the fitting cost."""

import gzip
import json
import math

from beqforge import pipeline as P
from beqforge import record
from beqforge.filters import FIT_STATS
from tests.test_design_strategy_config import inputs


def _run(monkeypatch):
    material, diagnosis, envelopes, identification = inputs()
    monkeypatch.setattr(P, "diagnose", lambda *a: diagnosis)
    monkeypatch.setattr(P, "extract", lambda *a: envelopes)
    monkeypatch.setattr(P, "identify_rolloff", lambda *a: identification)
    monkeypatch.setattr(P, "passband_ripple_db", lambda *a, **k: None)
    return P.run(material, P.PipelineParams(strategies=("parametric",), max_sections=1))


def test_elapsed_covers_the_stages_and_the_remainder_is_explicit(monkeypatch):
    report = _run(monkeypatch)
    timings = report.timings
    assert timings.elapsed_s >= timings.total_s
    assert timings.unattributed_s == timings.elapsed_s - timings.total_s
    # judging is broken down beside the stages, never inside the stage total
    assert {"judge.sub_feed", "judge.verify", "judge.headroom", "judge.assess"} <= set(
        timings.details
    )
    judged = sum(s for label, s in timings.stages if label.startswith("judge/"))
    assert sum(timings.details.values()) <= judged + 1e-6


def test_a_report_keeps_its_fitting_cost_when_the_next_run_resets_it(monkeypatch):
    report = _run(monkeypatch)
    calls = report.fit_stats.calls
    assert report.fit_stats is not FIT_STATS
    FIT_STATS.reset()
    assert report.fit_stats.calls == calls


def test_the_record_carries_the_accounting(monkeypatch, tmp_path):
    report = _run(monkeypatch)
    written = record.write(
        tmp_path / "r.run.json.gz",
        report,
        P.PipelineParams(),
        None,
        {},
        material_sha256="0" * 64,
    )
    timings = json.load(gzip.open(written))["timings"]
    assert timings["elapsed_s"] >= timings["total_s"]
    assert math.isfinite(timings["unattributed_s"])
    assert set(timings["fit"]) == {
        "optimiser_runs",
        "worker_seconds",
        "cost_evaluations",
    }
    assert "judge.verify" in timings["details"]


def test_timings_never_finished_report_no_elapsed():
    timings = P.Timings()
    assert math.isnan(timings.elapsed_s)
    assert math.isnan(timings.unattributed_s)
