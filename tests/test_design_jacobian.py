"""The analytic Jacobian must agree with the derivative it claims to be.

Hand-derived calculus fails silently. A sign error in one coefficient would not raise, would not
look wrong in a plot, and would surface only as a fit that converges a little worse than it
should — which is the sort of thing that gets blamed on the optimiser and never traced back. So
the agreement with numerical differentiation is asserted directly, over the parameter space the
fitter actually searches, and it is as much the deliverable as the derivative is.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "tools" / "experiments")
)

from p14_jacobian import magnitude_jacobian  # noqa: E402

from beqanalyser.design import BiquadSpec  # noqa: E402
from beqanalyser.design.filters import biquad_sos, magnitude_db  # noqa: E402

FS = 96000.0
GRID = np.logspace(math.log10(3.0), math.log10(400.0), 200)

STEPS = (3e-2, 3e-2, 1e-1)
"""Differencing step for (freq_hz, q, gain_db), measured rather than assumed.

Swept with the extrapolation below actually in place, over thirty random sections plus the
degenerate ones, the disagreement bottoms out at 1.9e-5, 1.2e-5 and 5.7e-7 respectively and
rises either side — round-off below, truncation above. A step that merely "looks small" is wrong
in both directions here: the coefficients move by ~1e-9 for a 1e-5 Hz change, so differencing
responses at that scale is catastrophic cancellation.

`gain_db` additionally cannot go near 1e-3 at all, because the coefficients are built from a
gain rounded to three decimals (see `test_gain_is_quantised_in_the_coefficients`).
"""

RELATIVE = 5e-5
ABSOLUTE = 1e-5
"""Agreement is `max|analytic - numeric| <= RELATIVE * max|numeric| + ABSOLUTE`.

Relative alone is the wrong test for a column that is genuinely zero, and several are: at a gain
of 0 dB, `A = 1`, the RBJ numerator and denominator coefficients become identical and the section
is a literal no-op — flat response, every derivative exactly zero. Dividing a 1e-6 disagreement by
a zero scale reports a catastrophic error for a perfectly correct column. Absolute alone is the
wrong test for a 26 dB shelf, whose derivatives are orders of magnitude larger. The pair is what
holds across the box.

`RELATIVE` sits comfortably above the 1.9e-5 floor the steps reach and far below anything a real
mistake survives: the two this test actually caught measured 2.7e-2 and 8.3e-2.
"""


def response(specs):
    return magnitude_db(biquad_sos(specs, FS), GRID, FS)


def numerical_column(specs, index, axis, step):
    """Richardson-extrapolated central difference of the response in one parameter.

    A plain central difference is `f' + O(h^2)`, and no single step serves the whole box: a
    high-Q section at 8 Hz has a far narrower feature than a broad shelf at 38 Hz, so a step
    fine enough for one is lost to round-off and one coarse enough for the other carries visible
    truncation. Combining `h` and `h/2` as `(4*D(h/2) - D(h))/3` cancels the `h^2` term, which
    holds everywhere the fitter searches without tuning per case.
    """

    def moved(delta):
        shifted = list(specs)
        spec = shifted[index]
        values = [spec.freq_hz, spec.q, spec.gain_db]
        values[axis] += delta
        shifted[index] = BiquadSpec(spec.type, values[0], values[2], values[1])
        return response(shifted)

    def central(h):
        return (moved(h) - moved(-h)) / (2.0 * h)

    return (4.0 * central(step / 2.0) - central(step)) / 3.0


def agrees(specs):
    analytic = magnitude_jacobian(specs, GRID, FS)
    steps = list(STEPS) * len(specs)
    for index in range(len(specs)):
        for axis in range(3):
            column = 3 * index + axis
            numeric = numerical_column(specs, index, axis, steps[column])
            scale = float(np.max(np.abs(numeric)))
            worst = float(np.max(np.abs(analytic[:, column] - numeric)))
            allowed = RELATIVE * scale + ABSOLUTE
            assert worst <= allowed, (
                f"section {index} {specs[index].type} "
                f"{('freq_hz', 'q', 'gain_db')[axis]}: |analytic - numeric| {worst:.2e} "
                f"exceeds {allowed:.2e} (derivative scale {scale:.2e})"
            )


@pytest.mark.parametrize(
    "spec",
    [
        BiquadSpec("low_shelf", 12.0, 14.0, 0.7),
        BiquadSpec("low_shelf", 30.0, -6.0, 2.5),
        BiquadSpec("low_shelf", 5.5, 26.0, 0.35),
        BiquadSpec("peaking_eq", 20.0, 8.0, 1.0),
        BiquadSpec("peaking_eq", 8.0, -12.0, 5.5),
        BiquadSpec("peaking_eq", 38.0, 0.5, 0.2),
    ],
)
def test_one_section_matches_numerical_differentiation(spec: BiquadSpec) -> None:
    agrees([spec])


def test_a_cascade_matches_numerical_differentiation() -> None:
    """Sections sum in dB, so each column must depend on its own section and no other."""
    agrees(
        [
            BiquadSpec("low_shelf", 12.0, 14.0, 0.7),
            BiquadSpec("peaking_eq", 20.0, -4.0, 2.0),
            BiquadSpec("low_shelf", 28.0, 3.0, 1.4),
            BiquadSpec("peaking_eq", 9.0, 6.0, 4.0),
        ]
    )


def test_it_holds_across_the_box_the_fitter_searches() -> None:
    """Random parameters over the fitter's own bounds, rather than convenient ones."""
    rng = np.random.default_rng(0)
    for _ in range(25):
        sections = int(rng.integers(1, 5))
        agrees(
            [
                BiquadSpec(
                    "low_shelf" if rng.random() < 0.5 else "peaking_eq",
                    float(rng.uniform(5.0, 40.0)),
                    float(rng.uniform(-26.0, 26.0)),
                    float(rng.uniform(0.3, 6.0)),
                )
                for _ in range(sections)
            ]
        )


def test_a_zero_gain_section_has_a_defined_derivative() -> None:
    """A = 1 collapses several terms; the shelf's sqrt(A) is the one worth checking."""
    agrees([BiquadSpec("low_shelf", 18.0, 0.0, 0.9)])
    agrees([BiquadSpec("peaking_eq", 18.0, 0.0, 0.9)])


def test_gain_is_quantised_in_the_coefficients() -> None:
    """Pinning the quantum, because a derivative is only meaningful well above it.

    `BiquadWithQGain` stores `round(float(gain), 3)` and the coefficients are computed from it,
    so the response does not move at all for a gain change under 0.001 dB. Harmless for the fit
    — gain is published at 0.005 dB, coarser than this — but it makes the objective a step
    function at that scale, which is exactly what a gradient method walks into.

    Frequency, by contrast, rounds only for display: `w0` is built from the raw value.
    """
    base = biquad_sos([BiquadSpec("low_shelf", 12.0, 14.0, 0.7)], FS)[0]

    def with_gain(delta):
        return biquad_sos([BiquadSpec("low_shelf", 12.0, 14.0 + delta, 0.7)], FS)[0]

    assert np.array_equal(with_gain(1e-4), base), (
        "the 0.001 dB quantum should swallow this"
    )
    assert not np.array_equal(with_gain(1e-2), base)

    moved_freq = biquad_sos([BiquadSpec("low_shelf", 12.000001, 14.0, 0.7)], FS)[0]
    assert not np.array_equal(moved_freq, base)
