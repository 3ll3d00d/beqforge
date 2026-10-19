"""The answers a few fixed requests get, keyed to the `DESIGN_VERSION` that gives them (1.4).

A caller trusts `design_version` to say whether a release answers a title differently, so
forgetting to bump it is the failure this guards against: an answer that moves fails here until
`DESIGN_VERSION` is bumped and the golden regenerated, and a bump fails here until the golden is
regenerated with it. Regenerate with

    BEQFORGE_REGENERATE_GOLDEN=1 uv run pytest tests/test_design_golden.py

and commit `tests/fixtures/design_golden.json` beside the bump.

An answer is everything `DESIGN_VERSION` covers: the candidates' filters and figures, the
rejected designs' figures and how many reasons each was refused for, and a decline's reason.
Wording is not compared (`commentary`, `decline_message`, the reasons' text), nor the build.
Numbers compare within `REL_TOL`/`ABS_TOL`, not bit for bit: the fixed requests run on every CI
platform, which need not agree in the last digits.

Each request is the synthetic known-rolloff title the server tests use, run with one strategy
at a time so each costs a bounded fit (~8-16 s here); together the cases reach every strategy,
an acceptance and both kinds of decline.
"""

import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pytest
from scipy import signal

from beqforge import Alignment, HighPass
from beqforge.designer import (
    DESIGN_VERSION,
    _ndarray_to_json,
    design,
    request_from_json,
    response_to_json,
)
from beqforge.harness import apply_high_pass
from beqforge.material import LFE_GAIN
from beqforge.pipeline import PipelineParams

GOLDEN = Path(__file__).parent / "fixtures" / "design_golden.json"
REGENERATE = os.environ.get("BEQFORGE_REGENERATE_GOLDEN") == "1"

REL_TOL = 1e-4
ABS_TOL = 1e-3
"""An answer change is one beyond these: a thousandth of a dB or Hz, or a part in 10^4."""

_WORDING = ("commentary", "decline_message", "contract_version")
_IDENTITY = ("design_version", "design_settings", "designer_build")


def _title(high_pass: HighPass | None, duration_s: float = 150.0, seed: int = 101):
    """A single-channel (LFE) title, scenes at three levels, with `high_pass` injected."""
    fs = 1000
    n = int(duration_s * fs)
    rng = np.random.default_rng(seed)
    scene = np.arange(n) // (4 * fs)
    levels = np.where(scene % 3 == 0, 0.0, np.where(scene % 3 == 1, 0.06, 0.3))
    source = rng.standard_normal(n) * levels
    low = signal.sosfilt(signal.butter(2, 35, fs=fs, output="sos"), source)
    samples = source + np.where(scene % 3 == 1, 5.0, 0.0) * low
    if high_pass is not None:
        samples = apply_high_pass(samples, high_pass, fs)
    samples = samples + rng.standard_normal(n) * 1e-5
    return {
        "contract_version": "1.4",
        "fs": fs,
        "coverage": "complete_programme",
        "mono_mix": _ndarray_to_json(LFE_GAIN * samples),
        "channels": {"LFE": _ndarray_to_json(samples)},
        "bass_management": None,
    }


def _no_channels():
    mono = np.random.default_rng(0).normal(scale=0.05, size=1000 * 60)
    return {
        "contract_version": "1.4",
        "fs": 1000,
        "coverage": "complete_programme",
        "mono_mix": _ndarray_to_json(mono),
        "channels": None,
        "bass_management": None,
    }


_ROLLOFF = HighPass(Alignment.BUTTERWORTH, 4, 24.0)

CASES = {
    "rolloff/flatten": (lambda: _title(_ROLLOFF), ("flatten",)),
    "rolloff/counterfactual": (lambda: _title(_ROLLOFF), ("counterfactual",)),
    "rolloff/parametric": (lambda: _title(_ROLLOFF), ("parametric",)),
    "unfiltered/flatten": (lambda: _title(None), ("flatten",)),
    "no-channels": (_no_channels, ("flatten",)),
}


def _answer(body: dict) -> dict:
    """The response body less wording and identity; a rejected design's reasons as a count."""
    answer = {k: v for k, v in body.items() if k not in _WORDING + _IDENTITY}
    for key in ("candidates", "rejected"):
        if answer.get(key) is not None:
            answer[key] = [
                {
                    **{k: v for k, v in c.items() if k not in _WORDING},
                    **(
                        {"rejection_reasons": len(c["rejection_reasons"])}
                        if "rejection_reasons" in c
                        else {}
                    ),
                }
                for c in answer[key]
            ]
    return answer


def _differences(expected, actual, where: str = "") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        if expected.keys() != actual.keys():
            return [f"{where}: keys {sorted(expected)} != {sorted(actual)}"]
        return [
            d
            for k in expected
            for d in _differences(expected[k], actual[k], f"{where}.{k}")
        ]
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{where}: {len(expected)} entries != {len(actual)}"]
        return [
            d
            for i, (e, a) in enumerate(zip(expected, actual, strict=True))
            for d in _differences(e, a, f"{where}[{i}]")
        ]
    numbers = (int, float)
    if (
        isinstance(expected, numbers)
        and isinstance(actual, numbers)
        and not isinstance(expected, bool)
        and not isinstance(actual, bool)
    ):
        if math.isclose(expected, actual, rel_tol=REL_TOL, abs_tol=ABS_TOL):
            return []
        return [f"{where}: {expected!r} != {actual!r}"]
    return [] if expected == actual else [f"{where}: {expected!r} != {actual!r}"]


def _run(name: str) -> dict:
    build, strategies = CASES[name]
    request = request_from_json(build())
    return response_to_json(design(request, PipelineParams(strategies=strategies)))


def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}


@pytest.mark.parametrize("name", list(CASES))
def test_an_unchanged_request_gets_the_answer_its_design_version_gives(name) -> None:
    body = _run(name)
    assert body["design_version"] == DESIGN_VERSION
    if REGENERATE:
        # one file, one writer per case: under xdist the cases may run in separate processes
        _write_case(name, _answer(body))
        return
    golden = _golden()
    assert golden.get("design_version") == DESIGN_VERSION, (
        f"the golden was made with design version {golden.get('design_version')}, the code "
        f"is {DESIGN_VERSION}: regenerate it (BEQFORGE_REGENERATE_GOLDEN=1)"
    )
    assert name in golden["answers"], f"no golden answer for {name}: regenerate"
    differences = _differences(golden["answers"][name], _answer(body), name)
    assert not differences, (
        f"the answer to an unchanged request moved under design version {DESIGN_VERSION}: "
        "bump DESIGN_VERSION and regenerate the golden, or undo the change.\n"
        + "\n".join(differences)
    )


def _write_case(name: str, answer: dict) -> None:
    """Merge one case's answer into the golden, under a lock file, at `DESIGN_VERSION`."""
    lock = GOLDEN.with_suffix(".lock")
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(0.05)
    try:
        golden = _golden()
        if golden.get("design_version") != DESIGN_VERSION:
            golden = {"design_version": DESIGN_VERSION, "answers": {}}
        golden["answers"][name] = answer
        golden["answers"] = dict(sorted(golden["answers"].items()))
        GOLDEN.write_text(json.dumps(golden, indent=1) + "\n", encoding="utf-8")
    finally:
        os.close(fd)
        os.unlink(lock)


def test_the_comparison_tolerates_last_digits_but_not_an_answer() -> None:
    answer = {"candidates": [{"filters": [{"fc": 20.0, "gain": 6.0}], "method": "x"}]}
    nudged = {
        "candidates": [{"filters": [{"fc": 20.0000001, "gain": 6.0}], "method": "x"}]
    }
    moved = {"candidates": [{"filters": [{"fc": 20.01, "gain": 6.0}], "method": "x"}]}
    assert _differences(answer, nudged) == []
    assert _differences(answer, moved) == [
        ".candidates[0].filters[0].fc: 20.0 != 20.01"
    ]
    assert _differences({"decline_reason": "a"}, {"decline_reason": "b"})
    assert _differences({"candidates": [{}]}, {"candidates": [{}, {}]})


def test_wording_and_identity_are_not_part_of_an_answer() -> None:
    body = {
        "contract_version": "1.4",
        "decline_reason": "within_programme_ripple",
        "decline_message": "anything",
        "rejected": [{"commentary": {"a": "b"}, "rejection_reasons": ["x: 1", "y: 2"]}],
        "design_version": DESIGN_VERSION,
        "design_settings": "abc",
        "designer_build": "def",
    }
    assert _answer(body) == {
        "decline_reason": "within_programme_ripple",
        "rejected": [{"rejection_reasons": 2}],
    }
