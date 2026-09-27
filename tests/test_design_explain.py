"""The designer response's plain-language account (`beqforge.explain`).

It measures and decides nothing, so these tests pin what it says against a real analysis and
hand-built candidates rather than a fitter run.
"""

import dataclasses

import numpy as np

from beqforge import explain
from beqforge.pipeline import FitStats, PipelineParams, Report, Timings, analyse
from tests.test_design_designer import _candidate, _report
from tests.test_design_diagnose import FS, high_passed, material_from
from tests.test_design_pipeline import scened_noise


def _analysed_report():
    samples = int(FS * 300.0)
    lfe = high_passed(scened_noise(22, samples), 22.0, order=6)
    lfe[: int(len(lfe) * 0.6)] = 0.0  # an LFE that is mostly empty, as on real dialogue titles
    material = material_from(
        {"L": scened_noise(20, samples), "C": scened_noise(21, samples), "LFE": lfe}
    )
    analysed = analyse(material, PipelineParams(strategies=("flatten",)))
    return Report(
        material,
        analysed.diagnosis,
        analysed.identification,
        [],
        Timings(),
        FitStats(),
        evidence_notes=analysed.limitations,
        mix_reference_db=analysed.mix_reference_db,
        mix_plateau_hz=analysed.mix_plateau_hz,
        judged_band_hz=analysed.judged_band_hz,
    )


def test_found_names_the_reference_its_carriers_and_silent_channels() -> None:
    report = _analysed_report()
    text = explain.found(report)
    low, high = report.mix_plateau_hz
    assert f"the mix's own plateau, {low:.1f}-{high:.1f} Hz" in text
    assert "the plateau is carried by" in text
    assert "LFE is exact digital silence for 6" in text  # ~60%, framing rounds it
    assert "L " in text and "C " in text


def test_found_without_a_plateau_says_there_is_nothing_to_measure_against() -> None:
    report = dataclasses.replace(_report([]), mix_reference_db=float("nan"))
    assert "no usable flat plateau" in explain.found(report)


def test_alternatives_say_why_each_other_candidate_lost() -> None:
    chosen = _candidate("flatten")
    rejected = dataclasses.replace(
        _candidate("counterfactual/25dB", passed=False),
        verdict=dataclasses.replace(
            _candidate(passed=False).verdict, failures=["overshoot", "cliff"]
        ),
    )
    tied = _candidate("parametric")  # same correction, same section count
    text = explain.alternatives(_report([chosen, rejected, tied]), chosen)
    assert "counterfactual/25dB rejected: overshoot (+1 more)" in text
    assert "parametric passed but was not chosen: tied on section count" in text
    assert explain.alternatives(_report([chosen]), chosen) == (
        "no other candidate was proposed"
    )


def test_correction_reads_the_low_end_before_and_after() -> None:
    text = explain.correction(_candidate())
    assert "flatten: 1 section(s) — low_shelf 15.81 Hz +15.9 dB Q 0.71" in text
    assert "frequency by frequency, dB against the reference: 5 Hz" in text
    assert np.isfinite(_candidate().correction.before_db).all()
