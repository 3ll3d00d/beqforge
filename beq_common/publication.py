"""Canonical published parameter precision, shared across workflows."""

from .types import BiquadSpec


def publication_filters(filters: list[BiquadSpec]) -> list[BiquadSpec]:
    """Canonical text parameters: Hz to 2 decimals, dB to 3, Q to 4.

    Independent of the device coefficient format and the hypothetical jitter diagnostic.
    Both judging and external export must use these same parameters.
    """
    return [
        BiquadSpec(
            s.type,
            round(float(s.freq_hz), 2),
            round(float(s.gain_db), 3),
            round(float(s.q), 4),
        )
        for s in filters
    ]
