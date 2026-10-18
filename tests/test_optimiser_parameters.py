import json
import math
import warnings

import numpy as np
import pytest

from beqoptimiser import (
    Fixed,
    FixedPoint,
    Float32,
    ParameterSettings,
    ResultCache,
    Section,
    magnitude,
    optimise_parameters,
    parameters,
)
from beqoptimiser import cache as cache_module

F32_48 = (48000, Float32())
F32_96 = (96000, Float32())
FIXED_48 = (48000, FixedPoint(5, 23))
HARD = Section("PeakingEQ", 10, 2, 12)
"""A 10 Hz peak float32 cannot hold within 0.5 dB at 48 kHz, but a nearby one it can."""


def _on_grid(s: Section) -> bool:
    return (
        round(s.freq, 2) == s.freq
        and round(s.q, 4) == s.q
        and round(s.gain, 2) == s.gain
    )


def _realised_error(sections, rate, precision, authored) -> float:
    """Independently: the candidate as the profile holds it against the authored ideal."""
    realised = precision.quantise(np.array([s.sos(rate) for s in sections]))
    reference = np.array([s.sos(rate) for s in authored])
    f = np.geomspace(2, 200, 32768)
    return float(
        np.max(np.abs(magnitude(realised, f, rate) - magnitude(reference, f, rate)))
    )


@pytest.mark.parametrize("profile", [F32_48, FIXED_48])
def test_an_accurate_original_is_not_searched(profile):
    result = optimise_parameters(
        [Section("LowShelf", 30, 0.7, 6)], profiles=[profile], cache=False
    )
    assert result.outcome == "within_margin"
    assert result.sections is None
    assert result.evaluations == 0


def test_a_replacement_is_on_the_grid_within_bounds_and_meets_the_margin():
    result = optimise_parameters([HARD], profiles=[F32_48], cache=False)
    assert result.outcome == "replacement"
    assert result.original_error_db > 0.5 > result.candidate_error_db
    (new,) = result.sections
    assert new.type == HARD.type and _on_grid(new)
    assert abs(new.freq - HARD.freq) <= 0.01 * HARD.freq
    assert abs(new.q - HARD.q) <= 0.02 * HARD.q + 1e-12
    assert abs(new.gain - HARD.gain) <= 0.1 + 1e-12
    assert _realised_error(result.sections, 48000, Float32(), [HARD]) < 0.5
    (profile,) = result.profiles
    assert profile.candidate_error_db == result.candidate_error_db
    assert profile.guard_error_db < 0.5


@pytest.mark.parametrize("profile", [F32_96, FIXED_48])
def test_each_rate_and_precision_improves_or_says_why_not(profile):
    sections = [Section("PeakingEQ", 5, 6, 6)]
    result = optimise_parameters(sections, profiles=[profile], cache=False)
    assert result.original_error_db > 0.5
    assert result.outcome in ("replacement", "improvement", "no_replacement")
    if result.sections is not None:
        assert result.candidate_error_db < result.original_error_db
        assert all(_on_grid(s) for s in result.sections)
        rate, precision = profile
        assert _realised_error(result.sections, rate, precision, sections) == (
            pytest.approx(result.candidate_error_db, abs=1e-3)
        )


def test_several_profiles_minimise_the_worst_without_quietly_costing_another():
    sections = [Section("LowShelf", 15, 0.9, 4)] * 3 + [Section("PeakingEQ", 5, 6, 6)]
    result = optimise_parameters(
        sections, profiles=[F32_96, FIXED_48, F32_48], cache=False
    )
    assert result.outcome in ("replacement", "improvement")
    assert result.candidate_error_db < result.original_error_db
    for p in result.profiles:
        assert p.candidate_error_db <= max(p.original_error_db, 0.5) + 1e-6
    assert result.candidate_error_db == max(
        p.candidate_error_db for p in result.profiles
    )
    # the repeated shelf stays one shelf x3
    assert result.sections[0] == result.sections[1] == result.sections[2]


def test_fixed_sections_are_kept_and_counted():
    # a gain stage the search may not touch, as SOS for each rate
    gain = Fixed.of({48000: [1.12, 0, 0, 1, 0, 0], 96000: [1.12, 0, 0, 1, 0, 0]})
    result = optimise_parameters([gain, HARD], profiles=[F32_48], cache=False)
    assert result.outcome == "replacement"
    assert result.sections[0] == gain
    alone = optimise_parameters([gain], profiles=[F32_48], cache=False)
    assert alone.outcome == "within_margin"


def _high_pass(freq: float, q: float, rate: int) -> list[float]:
    """RBJ high-pass, normalised: an exact zero at DC that float32 keeps."""
    w = 2 * math.pi * freq / rate
    alpha, cos = math.sin(w) / (2 * q), math.cos(w)
    a0 = 1 + alpha
    b0 = (1 + cos) / 2 / a0
    return [b0, -2 * b0, b0, 1.0, -2 * cos / a0, (1 - alpha) / a0]


def test_a_high_pass_agrees_at_dc_rather_than_making_the_guard_infinite():
    # both responses are -inf dB at DC; core's subtraction made that NaN, an infinite guard
    # error and numpy warnings
    hpf = Fixed.of({rate: _high_pass(5, 0.7071, rate) for rate in (48000, 96000)})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = optimise_parameters([HARD, hpf], profiles=[F32_48], cache=False)
    assert result.outcome == "replacement"
    (profile,) = result.profiles
    assert np.isfinite(profile.guard_error_db)
    assert profile.guard_error_db == pytest.approx(
        parameters._guard(
            np.array([HARD.sos(48000), hpf.sos(48000)]),
            Float32().quantise(
                np.array([result.sections[0].sos(48000), hpf.sos(48000)])
            ),
            48000,
            ParameterSettings(),
        )
    )


def test_nothing_searchable_is_no_replacement():
    rough = Fixed.of({48000: HARD.sos(48000)})
    result = optimise_parameters([rough], profiles=[F32_48], cache=False)
    assert result.original_error_db > 0.5
    assert result.outcome == "no_replacement"
    assert result.sections is None


def test_off_grid_parameters_are_judged_against_what_was_authored():
    # more decimals than the grid holds: the original is the published (grid) value,
    # the reference the exact one
    authored = Section("PeakingEQ", 10.004, 2.00004, 12.004)
    result = optimise_parameters([authored], profiles=[F32_48], cache=False)
    assert result.outcome == "replacement"
    assert _on_grid(result.sections[0])
    assert _realised_error(result.sections, 48000, Float32(), [authored]) < 0.5


def test_no_bounds_means_no_movement():
    still = ParameterSettings(freq_bound=0, q_bound=0, gain_bound_db=0)
    result = optimise_parameters([HARD], profiles=[F32_48], settings=still, cache=False)
    assert result.outcome == "no_replacement"


@pytest.mark.parametrize(
    "sections,profiles",
    [
        ([], [F32_48]),
        ([HARD], []),
        ([HARD], [(44100, Float32())]),
        ([Section("Gain", 10, 1, 1)], [F32_48]),
        ([Fixed.of({96000: [1, 0, 0, 1, 0, 0]})], [F32_48]),
    ],
)
def test_invalid_requests_are_refused(sections, profiles):
    with pytest.raises(ValueError):
        optimise_parameters(sections, profiles=profiles, cache=False)


def test_a_repeat_request_comes_from_the_cache(tmp_path, monkeypatch):
    store = ResultCache(tmp_path, use_seed=False)
    first = optimise_parameters([HARD], profiles=[F32_48], cache=store)
    assert len(list(tmp_path.glob("*.json"))) == 1

    def refuse(*args, **kwargs):
        raise AssertionError("searched again")

    monkeypatch.setattr(parameters, "optimise_parameters", refuse)
    assert optimise_parameters([HARD], profiles=[F32_48], cache=store) == first


def test_the_cache_key_covers_sections_profiles_and_settings():
    def key(sections=(HARD,), profiles=(F32_48,), settings=None):
        return cache_module._parameter_request(
            sections, profiles=profiles, settings=settings
        )[0]

    base = key()
    assert key() == base
    assert key(sections=(Section("PeakingEQ", 10, 2, 12.01),)) != base
    assert key(profiles=(F32_96,)) != base
    assert key(profiles=(FIXED_48,)) != base
    assert key(profiles=((48000, FixedPoint(5, 22)),)) != base
    assert key(settings=ParameterSettings(gain_bound_db=0.2)) != base


def test_the_coefficient_seed_identity_is_unchanged():
    # the bundled seed only loads while this identity matches; parameter search must not
    # move it
    assert "parameters" not in cache_module.implementation_identity()


def test_a_tampered_or_off_grid_cached_result_is_a_miss(tmp_path, monkeypatch):
    store = ResultCache(tmp_path, use_seed=False)
    optimise_parameters([HARD], profiles=[F32_48], cache=store)
    (path,) = tmp_path.glob("*.json")
    envelope = json.loads(path.read_text())
    envelope["result"]["sections"][0]["q"] = 2.00001
    envelope["checksum"] = cache_module._digest(envelope["result"])
    path.write_text(json.dumps(envelope))
    calls = []
    original = parameters.optimise_parameters

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(parameters, "optimise_parameters", counted)
    result = optimise_parameters([HARD], profiles=[F32_48], cache=store)
    assert calls == [1]
    assert _on_grid(result.sections[0])
