"""Real end-to-end tests for `beqforge serve-designer` — the one place the whole stack runs
together: a real socket, `http.server`'s request handling, JSON over the wire, and (for one
test) the real fitter.

Everything else about the designer binding is tested in isolation in
`test_design_designer.py`, on purpose (see that file's docstring) — this file exists because
none of those tests ever go through an actual HTTP request, so a bug in `_Handler` itself (a
wrong status code, a header the client can't parse, `do_POST` never reaching `design()`) would
be invisible to them.

The accepted-candidate case costs a real, bounded fit — `strategies=("flatten",)` measured
directly at ~4-8s (AGENTS.md's "40-80s a title" is for a full multi-strategy run against real,
much longer material; this is neither). Still real: injected via `beqforge.harness`, same
recipe `beqforge.harness.evidence_cases` uses for its own validated positives.
"""

import http.client
import json
import logging
import threading

import numpy as np
import pytest
from scipy import signal

from beqforge import Alignment, BiquadSpec, HighPass
from beqforge.designer import (
    DesignCandidate,
    DesignResponse,
    _ndarray_to_json,
    validate_response,
)
from beqforge.harness import apply_high_pass
from beqforge.material import LFE_GAIN
from beqforge.pipeline import PipelineParams
from tools.designer_server import DESIGN_PATH, HTTPServer, _Handler


@pytest.fixture(scope="module")
def server():
    """`HTTPServer`, same as production (see its fork-safety comment) — driven from a
    background thread here only because the test itself needs the main thread free to make
    requests; the real deployment calls `serve_forever()` from the process's only thread.
    """
    _Handler.params = PipelineParams(strategies=("flatten",))
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def _request(address, method: str, path: str, body=None, timeout: float = 30.0):
    conn = http.client.HTTPConnection(*address, timeout=timeout)
    try:
        payload = None
        headers = {}
        if body is not None:
            payload = body if isinstance(body, (bytes, str)) else json.dumps(body)
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        return response.status, (json.loads(raw) if raw else None)
    finally:
        conn.close()


def _response_from_json(body: dict) -> DesignResponse:
    """The test's own client-side decode — the production server never needs this direction."""
    if body.get("candidates") is not None:
        candidates = [
            DesignCandidate(
                filters=[BiquadSpec(**f) for f in c["filters"]],
                confidence=c["confidence"],
                mv_adjust_db=c["mv_adjust_db"],
                method=c["method"],
                gain_reduction_db=c.get("gain_reduction_db"),
                residual_db=c.get("residual_db"),
                residual_band_hz=(
                    tuple(c["residual_band_hz"]) if c.get("residual_band_hz") else None
                ),
                commentary=c.get("commentary"),
            )
            for c in body["candidates"]
        ]
        return DesignResponse(
            contract_version=body["contract_version"], candidates=candidates
        )
    return DesignResponse(
        contract_version=body["contract_version"],
        decline_reason=body.get("decline_reason"),
        decline_message=body.get("decline_message"),
    )


def _no_evidence_request() -> dict:
    rng = np.random.default_rng(0)
    mono = rng.normal(
        scale=0.05, size=1000 * 20
    )  # 20s, no channels: fast, certain decline
    return {
        "contract_version": "1.0",
        "fs": 1000,
        "coverage": "complete_programme",
        "mono_mix": _ndarray_to_json(mono),
        "channels": None,
        "bass_management": None,
    }


def _known_filter_request(duration_s: float = 150.0, seed: int = 101) -> dict:
    """A single-channel (LFE) title with a real, known Butterworth-4 rolloff injected at 24 Hz —
    the same construction `beqforge.harness.evidence_cases`' `varying_filtered` case uses.
    """
    fs = 1000
    n = int(duration_s * fs)
    rng = np.random.default_rng(seed)
    scene = np.arange(n) // (4 * fs)
    levels = np.where(scene % 3 == 0, 0.0, np.where(scene % 3 == 1, 0.06, 0.3))
    source = rng.standard_normal(n) * levels
    hp = HighPass(Alignment.BUTTERWORTH, 4, 24.0)
    low = signal.sosfilt(signal.butter(2, 35, fs=fs, output="sos"), source)
    varying = source + np.where(scene % 3 == 1, 5.0, 0.0) * low
    filtered = apply_high_pass(varying, hp, fs)
    noise = rng.standard_normal(n) * 1e-5
    samples = filtered + noise
    return {
        "contract_version": "1.0",
        "fs": fs,
        "coverage": "complete_programme",
        "mono_mix": _ndarray_to_json(LFE_GAIN * samples),
        "channels": {"LFE": _ndarray_to_json(samples)},
        "bass_management": None,
    }


def test_health_check(server) -> None:
    status, body = _request(server, "GET", "/health")
    assert status == 200
    assert body == {"status": "ok"}


def test_unknown_get_path_is_404(server) -> None:
    status, _ = _request(server, "GET", "/nope")
    assert status == 404


def test_unknown_post_path_is_404(server) -> None:
    status, _ = _request(server, "POST", "/nope", body={})
    assert status == 404


def test_malformed_json_body_is_400(server) -> None:
    status, body = _request(server, "POST", DESIGN_PATH, body="not json")
    assert status == 400
    assert "error" in body


def test_request_missing_a_required_field_is_400(server) -> None:
    status, body = _request(
        server, "POST", DESIGN_PATH, body={"contract_version": "1.0"}
    )
    assert status == 400
    assert "error" in body


def test_channel_length_mismatch_is_a_bad_request(server) -> None:
    body = {
        "contract_version": "1.0",
        "fs": 1000,
        "coverage": "complete_programme",
        "mono_mix": _ndarray_to_json(np.zeros(8)),
        "channels": {"L": _ndarray_to_json(np.zeros(5))},
    }
    status, response = _request(server, "POST", DESIGN_PATH, body=body)
    assert status == 400
    assert "channel 'L' has 5 samples; mono_mix has 8" in response["error"]


def test_declines_over_a_real_connection_with_no_channels(server) -> None:
    status, body = _request(server, "POST", DESIGN_PATH, body=_no_evidence_request())
    assert status == 200
    assert body["contract_version"] == "1.0"
    assert body["decline_reason"] == "channel_evidence_unavailable"
    assert "candidates" not in body


def test_accepts_a_real_injected_rolloff_over_http(server) -> None:
    """The one real proof this behaves: real audio in, over a real socket, a contract-valid
    correction out — checked against the same validator the server runs on itself before
    replying (`ContractViolation`'s docstring), not just this test's own assertions.
    """
    status, body = _request(
        server, "POST", DESIGN_PATH, body=_known_filter_request(), timeout=60.0
    )
    assert status == 200
    assert body["contract_version"] == "1.0"
    assert "decline_reason" not in body
    assert len(body["candidates"]) == 1

    candidate = body["candidates"][0]
    assert 0.0 <= candidate["confidence"] <= 1.0
    assert candidate["method"] in ("exact", "fitted", "non_parametric")
    assert 1 <= len(candidate["filters"]) <= 10
    assert candidate["mv_adjust_db"] > 0.0  # a boost was actually proposed

    validate_response(_response_from_json(body))  # must not raise


def _serve(monkeypatch, params: PipelineParams, cache):
    """A server of its own, with its own settings — `_Handler`'s are class attributes, so
    these are restored when the test ends and the module's shared server is unaffected."""
    monkeypatch.setattr(_Handler, "params", params)
    monkeypatch.setattr(_Handler, "cache", cache)
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def _stop(httpd, thread) -> None:
    httpd.shutdown()
    thread.join(timeout=5)
    httpd.server_close()


def _reused(caplog) -> set[str]:
    return {
        r.message.split(":")[0].strip()
        for r in caplog.records
        if "reused from" in r.message
    }


BOTH = ("flatten", "parametric")


def test_a_repeat_request_reuses_every_stage_and_answers_the_same(
    monkeypatch, tmp_path, caplog
) -> None:
    """R2a: `--cache-dir` — the second request for a title skips its analysis."""
    from beqforge.cache import DirStore

    httpd, thread = _serve(
        monkeypatch, PipelineParams(strategies=BOTH), DirStore(tmp_path)
    )
    try:
        request = _known_filter_request()
        first = _request(httpd.server_address, "POST", DESIGN_PATH, request, 120.0)
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="beqforge.cache"):
            second = _request(httpd.server_address, "POST", DESIGN_PATH, request, 120.0)
    finally:
        _stop(httpd, thread)
    assert first == second
    assert _reused(caplog) == {"analysis", "parametric"}
    assert list((tmp_path / "analysis").iterdir())


def test_another_server_setting_reuses_the_analysis_only(
    monkeypatch, tmp_path, caplog
) -> None:
    from beqforge.accept import AcceptParams
    from beqforge.cache import DirStore

    request = _known_filter_request()
    httpd, thread = _serve(
        monkeypatch, PipelineParams(strategies=BOTH), DirStore(tmp_path)
    )
    try:
        _request(httpd.server_address, "POST", DESIGN_PATH, request, 120.0)
    finally:
        _stop(httpd, thread)
    tilted = PipelineParams(
        strategies=BOTH, accept=AcceptParams(target_tilt_db_per_octave=1.0)
    )
    httpd, thread = _serve(monkeypatch, tilted, DirStore(tmp_path))
    caplog.clear()
    try:
        with caplog.at_level(logging.INFO, logger="beqforge.cache"):
            _request(httpd.server_address, "POST", DESIGN_PATH, request, 120.0)
    finally:
        _stop(httpd, thread)
    assert _reused(caplog) == {"analysis"}
    # both configurations' parametric entries kept side by side
    assert len(list((tmp_path / "parametric").iterdir())) == 2


def test_bass_management_alone_reuses_the_analysis(
    monkeypatch, tmp_path, caplog
) -> None:
    from beqforge.cache import DirStore

    request = _known_filter_request()
    httpd, thread = _serve(
        monkeypatch, PipelineParams(strategies=("flatten",)), DirStore(tmp_path)
    )
    try:
        _request(httpd.server_address, "POST", DESIGN_PATH, request, 120.0)
        managed = {
            **request,
            "bass_management": {
                "lpf_fs": 100.0,
                "lpf_position": "Before",
                "headroom_type": "WCS",
                "clip_before": False,
                "clip_after": False,
            },
        }
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="beqforge.cache"):
            status, _ = _request(
                httpd.server_address, "POST", DESIGN_PATH, managed, 120.0
            )
    finally:
        _stop(httpd, thread)
    assert status == 200
    assert "analysis" in _reused(caplog)


def test_without_a_cache_dir_nothing_is_written(monkeypatch, tmp_path) -> None:
    httpd, thread = _serve(monkeypatch, PipelineParams(strategies=("flatten",)), None)
    try:
        status, _ = _request(
            httpd.server_address, "POST", DESIGN_PATH, _no_evidence_request()
        )
    finally:
        _stop(httpd, thread)
    assert status == 200
    assert not list(tmp_path.iterdir())
