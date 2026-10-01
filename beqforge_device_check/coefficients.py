"""Published RBJ cascades and explicitly labelled storage hypotheses."""

import numpy as np

from beqforge import BiquadSpec
from beqforge.biquad import HighShelf, LowShelf, PeakingEQ
from beqforge.filters import publication_filters


def coefficients(filters: list[BiquadSpec], rate: int) -> np.ndarray:
    constructors = {
        "peaking_eq": PeakingEQ,
        "low_shelf": LowShelf,
        "high_shelf": HighShelf,
    }
    if any(section.freq_hz >= rate / 2 for section in filters):
        raise ValueError(
            "filter frequency must be below the internal Nyquist frequency"
        )
    return np.array(
        [
            constructors[section.type](
                rate, section.freq_hz, section.q, section.gain_db
            ).get_sos()[0]
            for section in filters
        ],
        dtype=np.float64,
    ).reshape(-1, 6)


def published(filters: list[BiquadSpec]) -> list[BiquadSpec]:
    return publication_filters(filters)


def rounded(sos: np.ndarray, model: str) -> np.ndarray:
    values = np.array(sos, dtype=np.float64, copy=True)
    if model == "float32":
        values = values.astype(np.float32).astype(np.float64)
    elif model == "fixed5.23":
        if np.any(values < -16) or np.any(values >= 16):
            raise ValueError("coefficient exceeds signed 5.23 range")
        values = np.rint(values * 2**23) / 2**23
    elif model != "float64":
        raise ValueError(f"no coefficient prediction for {model}")
    return values


def stable(sos: np.ndarray) -> bool:
    sections = np.asarray(sos, dtype=np.float64)
    if sections.ndim != 2 or sections.shape[1] != 6:
        return False
    return bool(
        np.all(np.isfinite(sections))
        and np.all(sections[:, 3] == 1)
        and np.all(1 + sections[:, 4] + sections[:, 5] > 0)
        and np.all(1 - sections[:, 4] + sections[:, 5] > 0)
        and np.all(1 - sections[:, 5] > 0)
    )


def response(sos: np.ndarray, frequencies: np.ndarray, rate: int) -> np.ndarray:
    """Extended precision evaluation avoids losing near-DC cancellation to FFT bins."""
    frequencies = np.asarray(frequencies, dtype=np.longdouble)
    if (
        np.any(~np.isfinite(frequencies))
        or np.any(frequencies <= 0)
        or np.any(frequencies >= rate / 2)
    ):
        raise ValueError("response frequencies must lie strictly inside (0, Nyquist)")
    z = np.exp(-2j * np.longdouble(np.pi) * frequencies / rate).astype(np.clongdouble)
    result = np.ones(z.shape, dtype=np.clongdouble)
    for b0, b1, b2, a0, a1, a2 in np.asarray(sos, dtype=np.longdouble):
        result *= (b0 + z * (b1 + z * b2)) / (a0 + z * (a1 + z * a2))
    return np.asarray(result, dtype=np.complex128)


def settling_seconds(sos: np.ndarray, rate: int, decay_db: float = 120) -> float:
    radius = max((max(abs(np.roots(section[3:]))) for section in sos), default=0)
    if radius >= 1:
        raise ValueError("unstable cascade has no finite settling time")
    return (
        float(-decay_db * np.log(10) / (20 * rate * np.log(radius)))
        if radius > 0
        else 0.0
    )


def minidsp_text(sos: np.ndarray) -> str:
    """miniDSP uses additive feedback; SciPy/RBJ denominator uses subtraction."""
    lines = []
    for index, section in enumerate(sos, 1):
        b0, b1, b2, _, a1, a2 = section
        lines.append(f"biquad{index},")
        lines.extend(
            f"{name}={value:.17g},"
            for name, value in zip(
                ("b0", "b1", "b2", "a1", "a2"), (b0, b1, b2, -a1, -a2), strict=True
            )
        )
    return "\n".join(lines) + "\n"
