"""Loading extracted analysis material — the input side of designer-interface.md v1.0 §2.

`tools/extract.py` writes these; this reads them back into the shapes the contract names.
Stored as float32 to halve the file, widened to float64 here.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

Coverage = Literal["complete_programme", "excerpt"]

MAIN_GAIN = 10.0 ** (-20.2 / 20.0)
LFE_GAIN = 10.0 ** (-10.2 / 20.0)
"""Gains `tools/extract.py` mixes with — beqdesigner's `MAIN`/`LFE` (model/ffmpeg.py:26).

20.2 dB of headroom, LFE +10 dB on top. Here rather than in the extractor because anything
decomposing the mix back into contributions has to use the same numbers, and two copies of
them is one too many.
"""


@dataclass(frozen=True, slots=True)
class Material:
    """One title's analysis signals.

    `coverage` is not decoration. An excerpt of loud scenes has no quiet frames, so the quiet
    envelope of §3.3 and the noise ceiling of §4.1 are unavailable and confidence must say so.
    Key off this rather than trying to infer it.
    """

    name: str
    fs: int
    mono_mix: np.ndarray
    channels: dict[str, np.ndarray]
    coverage: Coverage

    @property
    def duration_s(self) -> float:
        return len(self.mono_mix) / self.fs

    def __str__(self) -> str:
        channels = ",".join(self.channels) if self.channels else "none"
        return (
            f"{self.name} ({self.duration_s / 60:.1f} min at {self.fs} Hz, "
            f"{self.coverage}, channels: {channels})"
        )


def load(path: Path | str) -> Material:
    """Read one `.npz` written by `tools/extract.py`."""
    path = Path(path)
    with np.load(path, allow_pickle=False) as data:
        channels = {
            key.removeprefix("channel_"): np.asarray(data[key], dtype=np.float64)
            for key in data.files
            if key.startswith("channel_")
        }
        material = Material(
            name=path.stem,
            fs=int(data["fs"]),
            mono_mix=np.asarray(data["mono_mix"], dtype=np.float64),
            channels=channels,
            coverage=str(data["coverage"]),  # type: ignore[arg-type]
        )
    logger.info(f"Loaded {material}")
    return material


def load_all(directory: Path | str) -> list[Material]:
    """Every `.npz` in a directory, sorted by name."""
    return [load(p) for p in sorted(Path(directory).glob("*.npz"))]
