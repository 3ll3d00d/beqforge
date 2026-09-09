"""Analytic derivative of a cascade's dB magnitude with respect to its section parameters.

The prerequisite P14 turned out to need. Two-point differencing costs `3N + 1` response
evaluations per Jacobian, so a nine-parameter fit spends ten evaluations to establish one
direction to step in, and pays it again at every step. That is where P14's budget went, and
therefore where its accuracy went: the solver was not short of starts, it was short of the
budget to finish them.

`_fit_structure`'s own comment asks for this object for a different reason — a drift penalty
that helped "would have to be smooth: the derivative of the response with respect to the
coefficients, not a maximum over jittered evaluations" — so it is worth having even if the
retry fails.

Three properties make it tractable:

* **The cascade's dB response is a sum over sections**, so `d(total)/d(section i)` involves only
  section `i`. There are no cross terms to chase.
* **`magnitude_db` evaluates `a0 + a1 z + a2 z**2` directly** rather than assuming `a0 == 1`, so
  there is no normalisation to differentiate through.
* **`BiquadWithQ` computes `w0` from the unrounded frequency** — it rounds only `self.freq`, for
  display — so the coefficients really are smooth in `freq_hz`. `gain_db` is *not* like that:
  `BiquadWithQGain` rounds it to three decimals and the coefficients are built from the rounded
  value, so the response is a step function in gain at a 0.001 dB quantum. That is finer than
  the 0.005 dB gain is published at and so costs the fit nothing, but it is mirrored below, and
  it means the gain column is the derivative of the underlying function rather than of the
  staircase the code evaluates. An optimiser converging below 0.001 dB in gain would stall.

The chain, for one section at evaluation frequency `f` with `w = 2*pi*f/fs`:

    dB    = (10/ln10) * (ln|N|^2 - ln|D|^2)
    Nr    = b0 + b1*cos(w) + b2*cos(2w)
    Ni    = -(b1*sin(w) + b2*sin(2w))

    d|N|^2/db0 = 2*Nr
    d|N|^2/db1 = 2*(Nr*cos(w)  - Ni*sin(w))
    d|N|^2/db2 = 2*(Nr*cos(2w) - Ni*sin(2w))

    ddB/dp = (10/ln10) * ( (d|N|^2/dp)/|N|^2 - (d|D|^2/dp)/|D|^2 )

and `db_k/dp` comes from the RBJ formulae, which are quoted in `beqanalyser/__init__.py` on
`PeakingEQ` and `LowShelf` and reproduced in the two functions below.

**Verified against central differences** — see `tests/test_design_jacobian.py`. Hand-derived
calculus fails silently: a sign error here would surface as a slightly worse fit that nobody
traces back to its cause, so the agreement test is as much the deliverable as this file is.
"""

import math

import numpy as np

LN10 = math.log(10.0)


def _coefficients(kind: str, freq_hz: float, q: float, gain_db: float, fs: float):
    """The RBJ coefficients and everything the derivatives need alongside them."""
    w0 = 2.0 * math.pi * freq_hz / fs
    cos_w0, sin_w0 = math.cos(w0), math.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    # `BiquadWithQGain` stores `round(float(gain), 3)` and `_compute_coeffs` reads that, so the
    # response is evaluated at a quantised gain. Mirrored here or the derivative describes a
    # slightly different function: at a requested -0.010632 dB the code uses -0.011, which is a
    # 3.5% change in `A - 1` and showed up as an 8.3% error in the frequency column. Invisible
    # at ordinary gains, which is what makes it worth pinning rather than trusting.
    A = 10.0 ** (round(float(gain_db), 3) / 40.0)
    if kind == "peaking_eq":
        b = np.array([1.0 + alpha * A, -2.0 * cos_w0, 1.0 - alpha * A])
        a = np.array([1.0 + alpha / A, -2.0 * cos_w0, 1.0 - alpha / A])
    elif kind == "low_shelf":
        root = math.sqrt(A)
        shelf = 2.0 * root * alpha
        b = np.array(
            [
                A * ((A + 1) - (A - 1) * cos_w0 + shelf),
                2.0 * A * ((A - 1) - (A + 1) * cos_w0),
                A * ((A + 1) - (A - 1) * cos_w0 - shelf),
            ]
        )
        a = np.array(
            [
                (A + 1) + (A - 1) * cos_w0 + shelf,
                -2.0 * ((A - 1) + (A + 1) * cos_w0),
                (A + 1) + (A - 1) * cos_w0 - shelf,
            ]
        )
    else:
        raise ValueError(f"no derivative for section type {kind!r}")
    return b, a, w0, cos_w0, sin_w0, alpha, A


def _coefficient_derivatives(kind, q, fs, cos_w0, sin_w0, alpha, A):
    """`d[b0 b1 b2 a0 a1 a2]/dp` for p in (freq_hz, q, gain_db), as three 6-vectors."""
    dw0 = 2.0 * math.pi / fs
    dcos = -sin_w0 * dw0
    dalpha_df = cos_w0 * dw0 / (2.0 * q)
    dalpha_dq = -sin_w0 / (2.0 * q * q)
    dA = A * LN10 / 40.0

    if kind == "peaking_eq":
        by_freq = np.array(
            [
                A * dalpha_df,
                -2.0 * dcos,
                -A * dalpha_df,
                dalpha_df / A,
                -2.0 * dcos,
                -dalpha_df / A,
            ]
        )
        by_q = np.array(
            [
                A * dalpha_dq,
                0.0,
                -A * dalpha_dq,
                dalpha_dq / A,
                0.0,
                -dalpha_dq / A,
            ]
        )
        by_gain = np.array(
            [
                alpha * dA,
                0.0,
                -alpha * dA,
                -alpha * dA / (A * A),
                0.0,
                alpha * dA / (A * A),
            ]
        )
        return by_freq, by_q, by_gain

    root = math.sqrt(A)
    droot = dA / (2.0 * root)
    dshelf_df = 2.0 * root * dalpha_df
    dshelf_dq = 2.0 * root * dalpha_dq
    dshelf_dg = 2.0 * droot * alpha
    shelf = 2.0 * root * alpha

    by_freq = np.array(
        [
            A * (-(A - 1) * dcos + dshelf_df),
            2.0 * A * (-(A + 1) * dcos),
            A * (-(A - 1) * dcos - dshelf_df),
            (A - 1) * dcos + dshelf_df,
            -2.0 * (A + 1) * dcos,
            (A - 1) * dcos - dshelf_df,
        ]
    )
    by_q = np.array(
        [
            A * dshelf_dq,
            0.0,
            -A * dshelf_dq,
            dshelf_dq,
            0.0,
            -dshelf_dq,
        ]
    )
    by_gain = np.array(
        [
            dA * ((A + 1) - (A - 1) * cos_w0 + shelf)
            + A * (dA * (1.0 - cos_w0) + dshelf_dg),
            2.0 * dA * ((A - 1) - (A + 1) * cos_w0) + 2.0 * A * dA * (1.0 - cos_w0),
            dA * ((A + 1) - (A - 1) * cos_w0 - shelf)
            + A * (dA * (1.0 - cos_w0) - dshelf_dg),
            dA * (1.0 + cos_w0) + dshelf_dg,
            -2.0 * dA * (1.0 + cos_w0),
            dA * (1.0 + cos_w0) - dshelf_dg,
        ]
    )
    return by_freq, by_q, by_gain


def magnitude_jacobian(specs, freqs: np.ndarray, fs: float) -> np.ndarray:
    """`d(dB response)/d(parameters)` as `(len(freqs), 3 * len(specs))`.

    Columns run section by section, each as (freq_hz, q, gain_db) — the order `_unpack` reads
    a flat parameter vector in, so the result drops straight into `least_squares(jac=...)`.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    w = 2.0 * math.pi * freqs / fs
    cos1, sin1 = np.cos(w), np.sin(w)
    cos2, sin2 = np.cos(2.0 * w), np.sin(2.0 * w)
    jacobian = np.empty((freqs.size, 3 * len(specs)), dtype=np.float64)

    for index, spec in enumerate(specs):
        b, a, _, cos_w0, sin_w0, alpha, A = _coefficients(
            spec.type, spec.freq_hz, spec.q, spec.gain_db, fs
        )
        nr = b[0] + b[1] * cos1 + b[2] * cos2
        ni = -(b[1] * sin1 + b[2] * sin2)
        dr = a[0] + a[1] * cos1 + a[2] * cos2
        di = -(a[1] * sin1 + a[2] * sin2)
        n_sq = nr * nr + ni * ni
        d_sq = dr * dr + di * di

        # d|N|^2/db_k and d|D|^2/da_k, stacked as (3, len(freqs))
        num_by_coeff = 2.0 * np.stack(
            [
                nr,
                nr * cos1 - ni * sin1,
                nr * cos2 - ni * sin2,
            ]
        )
        den_by_coeff = 2.0 * np.stack(
            [
                dr,
                dr * cos1 - di * sin1,
                dr * cos2 - di * sin2,
            ]
        )

        derivatives = _coefficient_derivatives(
            spec.type, spec.q, fs, cos_w0, sin_w0, alpha, A
        )
        for offset, by_parameter in enumerate(derivatives):
            numerator = by_parameter[:3] @ num_by_coeff
            denominator = by_parameter[3:] @ den_by_coeff
            jacobian[:, 3 * index + offset] = (10.0 / LN10) * (
                numerator / n_sq - denominator / d_sq
            )
    return jacobian


def coefficient_sensitivity(
    specs, freqs: np.ndarray, fs: float, step: float
) -> np.ndarray:
    """Worst-case dB change per frequency if every coefficient rounds the wrong way.

    The smooth stand-in for `Realisation`'s drift term. That term rounds the coefficients and
    measures what happened, so it contains `np.round`, is piecewise constant, and has no
    derivative anywhere — which is why a smooth optimiser cannot see fragility while it fits and
    only discovers it when the drift screen rejects the result.

    A first-order bound has no such problem. Rounding moves each coefficient by at most
    `step / 2`, so the response moves by at most `(step / 2) * sum_k |d(dB)/d(c_k)|`, and those
    per-coefficient derivatives are exactly the intermediates `magnitude_jacobian` already forms
    on its way to the parameter derivatives. It is an upper bound rather than a sample: it
    assumes every coefficient rounds adversely at once, where a real rounding is one draw.

    `a0` is excluded because `Realisation.quantise` forces it back to 1 rather than rounding it.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    w = 2.0 * math.pi * freqs / fs
    cos1, sin1 = np.cos(w), np.sin(w)
    cos2, sin2 = np.cos(2.0 * w), np.sin(2.0 * w)
    total = np.zeros(freqs.size, dtype=np.float64)

    for spec in specs:
        b, a, _, _, _, _, _ = _coefficients(
            spec.type, spec.freq_hz, spec.q, spec.gain_db, fs
        )
        # the published cascade is normalised, and that is what gets rounded
        b, a = b / a[0], a / a[0]
        nr = b[0] + b[1] * cos1 + b[2] * cos2
        ni = -(b[1] * sin1 + b[2] * sin2)
        dr = a[0] + a[1] * cos1 + a[2] * cos2
        di = -(a[1] * sin1 + a[2] * sin2)
        scale = 10.0 / LN10
        by_b = (
            scale
            * 2.0
            * np.stack(
                [
                    nr,
                    nr * cos1 - ni * sin1,
                    nr * cos2 - ni * sin2,
                ]
            )
            / (nr * nr + ni * ni)
        )
        by_a = (
            scale
            * 2.0
            * np.stack(
                [
                    dr * cos1 - di * sin1,
                    dr * cos2 - di * sin2,
                ]
            )
            / (dr * dr + di * di)
        )
        total += np.sum(np.abs(by_b), axis=0) + np.sum(np.abs(by_a), axis=0)
    return total * (step / 2.0)
