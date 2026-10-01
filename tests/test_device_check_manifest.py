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
