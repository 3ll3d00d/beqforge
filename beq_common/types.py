"""Rate-independent published filter descriptions."""

import math
from dataclasses import dataclass
from typing import Literal

BiquadType = Literal["peaking_eq", "low_shelf", "high_shelf"]


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
