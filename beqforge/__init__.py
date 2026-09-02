"""Automated BEQ filter design — deriving a filter from content.

A separate capability from the clustering pipeline; see AUTOMATED_DESIGN.md. Nothing here
imports from the catalogue side of the package beyond the RBJ biquad classes.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Literal

BIQUAD_BUDGET = 10
"""Maximum biquad sections a published filter may contain (designer-interface.md v1.0 §5)."""

BiquadType = Literal["peaking_eq", "low_shelf", "high_shelf"]


class Alignment(Enum):
    """Filter alignments a mastering high-pass plausibly uses.

    Values match beqdesigner's `FilterType` so the two can be reconciled without a lookup.
    """

    BUTTERWORTH = "BW"
    LINKWITZ_RILEY = "LR"
    BESSEL_PHASE = "BESP"
    BESSEL_MAG3 = "BESM3"

    @property
    def is_linkwitz_riley(self) -> bool:
        return self is Alignment.LINKWITZ_RILEY


@dataclass(frozen=True, slots=True)
class HighPass:
    """A high-pass characterised the way a mastering filter is: alignment, order, corner."""

    alignment: Alignment
    order: int
    corner_hz: float

    def __post_init__(self) -> None:
        if self.order < 1:
            raise ValueError(f"order must be >= 1, got {self.order}")
        if self.corner_hz <= 0:
            raise ValueError(f"corner_hz must be > 0, got {self.corner_hz}")
        if self.alignment.is_linkwitz_riley and self.order % 2:
            raise ValueError(f"Linkwitz-Riley order must be even, got {self.order}")

    def __str__(self) -> str:
        return f"{self.alignment.value}{self.order}@{self.corner_hz:g}Hz"


@dataclass(frozen=True, slots=True)
class BiquadSpec:
    """One publishable biquad section — designer-interface.md v1.0 §3.

    Deliberately carries no sample rate: `freq_hz`/`gain_db`/`q` fully determine an RBJ
    section independent of the rate it is eventually realised at. `gain_db` follows the RBJ
    convention `A = 10 ** (gain_db / 40)`, not `/20`.
    """

    type: BiquadType
    freq_hz: float
    gain_db: float
    q: float

    def __post_init__(self) -> None:
        if self.freq_hz <= 0:
            raise ValueError(f"freq_hz must be > 0, got {self.freq_hz}")
        if self.q <= 0:
            raise ValueError(f"q must be > 0, got {self.q}")
        if not math.isfinite(self.gain_db):
            raise ValueError(f"gain_db must be finite, got {self.gain_db}")


@dataclass(frozen=True, slots=True)
class PolePair:
    """A conjugate pole pair, as the natural frequency and Q of its second-order section."""

    freq_hz: float
    q: float


class ExactInversionUnavailable(Exception):
    """Raised when the closed-form shelf decomposition does not apply.

    The caller should fall back to a numerical fit against the same target.
    """
