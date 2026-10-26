"""The fit's cost over a whole differential-evolution population at once (TODO 23).

`_fit_structure` spends almost all of a fit in differential evolution, and its scalar cost was
100-120 µs an evaluation, most of it arithmetic over 400 bins rather than Python overhead: the
scalar path was already vectorised over frequency. Two things make this one cheaper.

* **One call per generation.** `differential_evolution(vectorized=True)` hands over every
  member, so the per-member work scipy and the cost each do in Python is paid once.
* **Comparisons in the linear domain.** The worst absolute dB error, the device's drift and the
  over-lift against the ceiling are each monotone in the power ratio, so the maxima are taken
  over power ratios and a member needs three logarithms rather than one per bin per section.

The arithmetic is split so the answer cannot depend on whether numba is installed. numpy
computes every coefficient and every transcendental, for both paths; the kernels do only
`+`, `*`, `/` and max, in the same order, which IEEE arithmetic makes bit-identical between the
compiled loop and the numpy one as long as nothing is fused into a multiply-add. numba is not
asked for `fastmath`, so it fuses nothing; `tests/test_fit_kernel.py` holds the two to
equality. numba is several times faster; numpy is the fallback.

Not bit-identical to the scalar cost, which sums per-bin logarithms: they agree to ~1e-9 dB,
and the optimiser turns any difference into a possibly different optimum (TODO 28, 32). Its
answers are therefore its own, which is why the polish and the residual a fit returns stay on
the scalar cost, the definition `residual_db` reports.
"""

import os

import numpy as np

try:
    if os.environ.get("BEQ_FIT_KERNEL", "").lower() == "numpy":
        raise ImportError("BEQ_FIT_KERNEL=numpy")
    import numba
except ImportError:
    numba = None

OVERLIFT_OFFSET_DB = 1e3
"""What a member over the ceiling is charged on top of its overshoot, as in `_fit_structure`."""

_NUMPY_CHUNK = 32
"""Members per numpy pass: big enough to amortise the calls, small enough to stay in cache."""


def kernel_name() -> str:
    """Which implementation scores a population here, for timing reports."""
    return "numpy" if numba is None else "numba"


class PopulationCost:
    """`_fit_structure`'s cost for every member of a population: `(parameters, members) -> (members,)`.

    The same terms as the scalar cost. The worst error against the target over the scored band,
    taken together with the worst drift the device's coefficient rounding causes there; and,
    with a ceiling, every member under it ranked before every member over it, those over it by
    how far. Parameters are rounded as `publication_filters` rounds them, with numpy's rounding
    rather than Python's, which differs only for a value within an ulp of a half step; the
    cascade a fit returns is rounded the exact way afterwards.
    """

    def __init__(
        self,
        target_db: np.ndarray,
        freqs: np.ndarray,
        fs: float,
        shelves: int,
        peaks: int,
        mask: np.ndarray,
        realisation,
        ceiling,
    ) -> None:
        self.shelves = shelves
        self.sections = shelves + peaks
        self.evaluations = 0
        """Members scored so far: scipy's `nfev` counts calls when it is vectorised."""
        self.fs = fs
        self.realisation = realisation
        band = np.asarray(freqs, dtype=np.float64)[mask]
        self.band_fs = _trig(band, fs)
        self.target_inverse = 10.0 ** (
            -np.asarray(target_db, dtype=np.float64)[mask] / 10.0
        )
        self.rate = fs if realisation is None else realisation.fs
        self.band_rate = self.band_fs if self.rate == fs else _trig(band, self.rate)
        self.ceiling = None
        if ceiling is not None:
            self.ceiling = (
                _trig(np.asarray(ceiling[0], dtype=np.float64), self.rate),
                10.0 ** (-np.asarray(ceiling[1], dtype=np.float64) / 10.0),
            )

    def __call__(self, population: np.ndarray) -> np.ndarray:
        rows = np.asarray(population, dtype=np.float64).T.reshape(-1, self.sections, 3)
        self.evaluations += rows.shape[0]
        freq = np.round(rows[..., 0], 2)
        q = np.round(rows[..., 1], 4)
        gain = np.round(rows[..., 2], 3)
        response = _coefficients(freq, q, gain, self.shelves, self.fs)
        if self.realisation is None:
            error, _ = _fit_and_drift(
                response, _NO_SECTIONS, *self.band_fs, self.target_inverse
            )
            worst = error
            realised = response
        else:
            device = (
                response
                if self.rate == self.fs
                else _coefficients(freq, q, gain, self.shelves, self.rate)
            )
            realised = _quantised(device, self.realisation)
            if device is response:
                error, drift = _fit_and_drift(
                    response, realised, *self.band_fs, self.target_inverse
                )
            else:
                error, _ = _fit_and_drift(
                    response, _NO_SECTIONS, *self.band_fs, self.target_inverse
                )
                drift = _worst_ratio(
                    realised,
                    device,
                    *self.band_rate,
                    np.ones(len(self.band_rate[0])),
                    True,
                )
            worst = np.maximum(error, drift)
        cost = 10.0 * np.log10(worst)
        if self.ceiling is None:
            return cost
        over = _worst_ratio(
            realised, _NO_SECTIONS, *self.ceiling[0], self.ceiling[1], False
        )
        lifted = over > 1.0
        cost[lifted] = OVERLIFT_OFFSET_DB + 10.0 * np.log10(over[lifted])
        return cost


_NO_SECTIONS = np.empty((0, 0, 5))
"""A cascade of no sections, whose power is 1 everywhere: the denominator when there is none."""


def _trig(freqs: np.ndarray, fs: float) -> tuple[np.ndarray, ...]:
    w = 2.0 * np.pi * freqs / fs
    return np.cos(w), np.sin(w), np.cos(2.0 * w), np.sin(2.0 * w)


def _coefficients(
    freq: np.ndarray, q: np.ndarray, gain: np.ndarray, shelves: int, fs: float
) -> np.ndarray:
    """`_sos_from_parameters` over a population: `(members, sections, 5)` of b0 b1 b2 a1 a2,
    normalised by a0, the RBJ formulae `biquad.py` documents."""
    A = 10.0 ** (gain / 40.0)
    w0 = 2.0 * np.pi * freq / fs
    cos_w0, sin_w0 = np.cos(w0), np.sin(w0)
    alpha = sin_w0 / (2.0 * q)
    shelf = np.arange(freq.shape[1]) < shelves
    lift = 2.0 * np.sqrt(A) * alpha
    b0 = np.where(shelf, A * ((A + 1) - (A - 1) * cos_w0 + lift), 1.0 + alpha * A)
    b1 = np.where(shelf, 2.0 * A * ((A - 1) - (A + 1) * cos_w0), -2.0 * cos_w0)
    b2 = np.where(shelf, A * ((A + 1) - (A - 1) * cos_w0 - lift), 1.0 - alpha * A)
    a0 = np.where(shelf, (A + 1) + (A - 1) * cos_w0 + lift, 1.0 + alpha / A)
    a1 = np.where(shelf, -2.0 * ((A - 1) + (A + 1) * cos_w0), -2.0 * cos_w0)
    a2 = np.where(shelf, (A + 1) + (A - 1) * cos_w0 - lift, 1.0 - alpha / A)
    return np.ascontiguousarray(
        np.stack([b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0], axis=-1)
    )


def _quantised(coefficients: np.ndarray, realisation) -> np.ndarray:
    """`Realisation.quantise`, for normalised coefficients (a0 is 1, and stays 1 rounded)."""
    step = 2.0 ** (realisation.integer_bits - realisation.coefficient_bits)
    return np.round(coefficients / step) * step


# The kernels. Each exists twice, compiled and numpy, with the same operations in the same order:
# the power of a cascade at a bin is the product, section by section in order, of |numerator|^2
# and, separately, of |denominator|^2, divided once.


def _fit_and_drift_numpy(response, realised, c1, s1, c2, s2, target_inverse):
    members = response.shape[0]
    error = np.empty(members)
    drift = np.ones(members)
    for start in range(0, members, _NUMPY_CHUNK):
        chunk = slice(start, start + _NUMPY_CHUNK)
        r = _power_numpy(response[chunk], c1, s1, c2, s2)
        e = r * target_inverse
        error[chunk] = np.maximum(e, 1.0 / e).max(axis=1)
        if realised.shape[1]:
            d = _power_numpy(realised[chunk], c1, s1, c2, s2) / r
            drift[chunk] = np.maximum(d, 1.0 / d).max(axis=1)
    return error, drift


def _worst_ratio_numpy(numerator, denominator, c1, s1, c2, s2, weight, symmetric):
    members = numerator.shape[0]
    out = np.empty(members)
    for start in range(0, members, _NUMPY_CHUNK):
        chunk = slice(start, start + _NUMPY_CHUNK)
        ratio = _power_numpy(numerator[chunk], c1, s1, c2, s2)
        if denominator.shape[1]:
            ratio = ratio / _power_numpy(denominator[chunk], c1, s1, c2, s2)
        ratio = ratio * weight
        if symmetric:
            ratio = np.maximum(ratio, 1.0 / ratio)
        out[chunk] = ratio.max(axis=1)
    return out


def _power_numpy(coefficients, c1, s1, c2, s2):
    num = np.ones((coefficients.shape[0], len(c1)))
    den = np.ones_like(num)
    for k in range(coefficients.shape[1]):
        b0, b1, b2, a1, a2 = (coefficients[:, k, i, None] for i in range(5))
        nr = b0 + b1 * c1 + b2 * c2
        ni = b1 * s1 + b2 * s2
        dr = 1.0 + a1 * c1 + a2 * c2
        di = a1 * s1 + a2 * s2
        num = num * (nr * nr + ni * ni)
        den = den * (dr * dr + di * di)
    return num / den


def _compiled(function):
    """`numba.njit`, with its on-disk cache when there is somewhere to write one.

    numba caches beside the source, or failing that in the user's cache directory, and refuses
    to compile at all when it can write to neither: an install the running user can't write to,
    with no home of its own, such as the designer image run as another user. The cache only saves
    the compile (~0.7 s a process), so without one the kernel is compiled afresh, to the same
    answer.
    """
    try:
        return numba.njit(cache=True)(function)
    except RuntimeError as e:
        if "cannot cache" not in str(e):
            raise
        return numba.njit(function)


if numba is None:
    _fit_and_drift = _fit_and_drift_numpy
    _worst_ratio = _worst_ratio_numpy
else:

    @_compiled
    def _power_into(
        coefficients, m, c1, s1, c2, s2, out
    ):  # pragma: no cover - compiled
        bins = c1.shape[0]
        num = np.ones(bins)
        den = np.ones(bins)
        for k in range(coefficients.shape[1]):
            b0 = coefficients[m, k, 0]
            b1 = coefficients[m, k, 1]
            b2 = coefficients[m, k, 2]
            a1 = coefficients[m, k, 3]
            a2 = coefficients[m, k, 4]
            for i in range(bins):
                nr = b0 + b1 * c1[i] + b2 * c2[i]
                ni = b1 * s1[i] + b2 * s2[i]
                dr = 1.0 + a1 * c1[i] + a2 * c2[i]
                di = a1 * s1[i] + a2 * s2[i]
                num[i] = num[i] * (nr * nr + ni * ni)
                den[i] = den[i] * (dr * dr + di * di)
        for i in range(bins):
            out[i] = num[i] / den[i]

    @_compiled
    def _fit_and_drift(
        response, realised, c1, s1, c2, s2, target_inverse
    ):  # pragma: no cover - compiled
        members = response.shape[0]
        bins = c1.shape[0]
        error = np.empty(members)
        drift = np.ones(members)
        r = np.empty(bins)
        q = np.empty(bins)
        for m in range(members):
            _power_into(response, m, c1, s1, c2, s2, r)
            worst = 0.0
            for i in range(bins):
                e = r[i] * target_inverse[i]
                e = max(e, 1.0 / e)
                worst = max(worst, e)
            error[m] = worst
            if realised.shape[1]:
                _power_into(realised, m, c1, s1, c2, s2, q)
                worst = 0.0
                for i in range(bins):
                    d = q[i] / r[i]
                    d = max(d, 1.0 / d)
                    worst = max(worst, d)
                drift[m] = worst
        return error, drift

    @_compiled
    def _worst_ratio(
        numerator, denominator, c1, s1, c2, s2, weight, symmetric
    ):  # pragma: no cover - compiled
        members = numerator.shape[0]
        bins = c1.shape[0]
        out = np.empty(members)
        top = np.empty(bins)
        bottom = np.ones(bins)
        for m in range(members):
            _power_into(numerator, m, c1, s1, c2, s2, top)
            if denominator.shape[1]:
                _power_into(denominator, m, c1, s1, c2, s2, bottom)
            worst = 0.0
            for i in range(bins):
                ratio = top[i]
                if denominator.shape[1]:
                    ratio = ratio / bottom[i]
                ratio = ratio * weight[i]
                if symmetric:
                    ratio = max(ratio, 1.0 / ratio)
                worst = max(worst, ratio)
            out[m] = worst
        return out
