import copy

import numpy as np
import pytest
from scipy.signal import sosfreqz

from beqforge import BiquadSpec
from beqforge_device_check.coefficients import (
    coefficients,
    minidsp_text,
    response,
    rounded,
    stable,
)
from beqforge_device_check.manifest import generate, make_case, validate
from beqforge_device_check.profiles import PROFILES, DeviceProfile


def test_profiles_round_trip_and_enforce_actual_rate_and_capacity():
    profile = PROFILES["minidsp-2x4hd"]
    assert DeviceProfile.from_dict(profile.as_dict()) == profile
    with pytest.raises(ValueError, match="internal rate"):
        generate(profile, rate=48000)
    case = make_case(
        "over-capacity",
        [BiquadSpec("low_shelf", 20, 3, 0.707)] * 11,
        profile,
        96000,
        "input",
        0,
    )
    assert case["status"] == "unsupported"
    assert len(case["publication_filters"]) == 11


def test_manifest_frozen_reproducible_and_tamper_detected():
    manifest = generate(PROFILES["minidsp-2x4hd"])
    assert manifest == generate(PROFILES["minidsp-2x4hd"])
    validate(manifest)
    changed = copy.deepcopy(manifest)
    changed["cases"][1]["exact_sos"][0][0] += 1e-5
    with pytest.raises(ValueError, match="hash"):
        validate(changed)


def test_response_against_independent_scipy_evaluation_and_feedback_sign():
    sos = coefficients([BiquadSpec("peaking_eq", 20, 8, 2)], 96000)
    frequencies = np.geomspace(2, 200, 200)
    _, expected = sosfreqz(sos, worN=frequencies, fs=96000)
    np.testing.assert_allclose(response(sos, frequencies, 96000), expected, rtol=2e-9)
    text = minidsp_text(sos)
    assert f"a1={-sos[0, 4]:.17g}," in text
    assert stable(rounded(sos, "float32"))
    np.testing.assert_array_equal(
        rounded(sos, "float32"), sos.astype(np.float32).astype(float)
    )


def test_rounding_can_make_low_frequency_high_q_unstable():
    sos = coefficients([BiquadSpec("peaking_eq", 0.01, 12, 8)], 96000)
    assert stable(sos)
    assert not stable(rounded(sos, "float32"))


def test_characterisation_suites_load_each_filter_once_with_one_reloaded_control():
    profile = PROFILES["minidsp-2x4hd"]
    grid = generate(profile, suite="grid")
    validate(grid)
    filters = grid["cases"][1:]
    # 10-20 Hz at Q 0.707, plus each type's other realistic Qs at 10 Hz.
    assert len(filters) == 2 * 11 + 5 + 4
    assert min(c["publication_filters"][0]["freq_hz"] for c in filters) == 10
    shelves = [c for c in filters if c["publication_filters"][0]["type"] == "low_shelf"]
    assert max(c["publication_filters"][0]["q"] for c in shelves) <= 1.0
    assert max(c["publication_filters"][0]["q"] for c in filters) <= 2.0
    loads = {case_id: grid["order"].count(case_id) for case_id in grid["order"]}
    assert loads[grid["control"]] == 3
    assert sorted(set(loads.values())) == [1, 3]
    assert len(grid["levels_dbfs"]) == 1
    assert grid["identity_bracket_every"] == 4
    both = generate(profile, suite="pilot", levels=(-30.0, -50.0))
    assert both["levels_dbfs"] == [-30.0, -50.0]


def test_boundary_suite_spans_the_predicted_coefficient_error_targets():
    from beqforge_device_check.manifest import BOUNDARY_TARGETS_DB, predicted_error_db

    manifest = generate(PROFILES["minidsp-2x4hd"], suite="boundary")
    errors = sorted(
        predicted_error_db([BiquadSpec(**c["publication_filters"][0])], 96000)
        for c in manifest["cases"][1:]
    )
    # Realistic filters only, chosen either side of the requirement, ~0.01 to ~10 dB.
    specs = [c["publication_filters"][0] for c in manifest["cases"][1:]]
    assert all(10 <= s["freq_hz"] <= 60 for s in specs)
    assert all(s["q"] <= (1.0 if s["type"] == "low_shelf" else 2.0) for s in specs)
    # Realistic filters reach a few dB at most; the targets they can reach are hit.
    assert errors[0] < 0.02 and errors[-1] > 2
    for target in (t for t in BOUNDARY_TARGETS_DB if t <= 1):
        assert min(abs(np.log(e / target)) for e in errors) < np.log(2)


def test_level_screen_uses_the_coefficients_the_device_stores():
    """Mojin: The Worm Valley clipped a 2x4 HD: float32 storage adds 16 dB at 1 Hz."""
    from beqforge_device_check.coefficients import published
    from beqforge_device_check.manifest import freeze_levels

    specs = [BiquadSpec("low_shelf", 10, 6.2, 0.9)] * 5 + [
        BiquadSpec("peaking_eq", 12, 4.7, 5),
        BiquadSpec("peaking_eq", 16, 8, 1.8),
        BiquadSpec("peaking_eq", 24, 2, 11),
        BiquadSpec("peaking_eq", 33, 0.7, 3),
    ]
    sos = coefficients(published(specs), 96000)
    case = {
        "status": "planned",
        "id": "x",
        "rate": 96000,
        "exact_sos": sos.tolist(),
        "transport_sos": sos.tolist(),
    }
    sent_only = {"profile": {"coefficient_format": "float64"}, "cases": [dict(case)]}
    stored = {"profile": {"coefficient_format": "float32"}, "cases": [dict(case)]}
    freeze_levels(sent_only, (-30.0,))
    freeze_levels(stored, (-30.0,))
    assert sent_only["cases"][0]["predicted_intermediate_peak_db"] < 33
    peak = stored["cases"][0]["predicted_intermediate_peak_db"]
    assert peak > 48
    # The stored-coefficient peak keeps the screen's 6 dB below full scale.
    assert stored["levels_dbfs"][0] + peak == pytest.approx(-6)
