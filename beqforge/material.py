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


BM_CROSSOVER_HZ = 80.0
"""Bass-management crossover the sub feed is modelled at — beqdesigner's own LR4, at 80 Hz."""


def bass_managed_sum(
    material: "Material", crossover_hz: float = BM_CROSSOVER_HZ
) -> np.ndarray | None:
    """The sub feed a BEQ actually operates on, at the scale a device would see it.

    Returns None when channel decomposition is unavailable.

    A BEQ is applied **post bass management, to the sub channel only** — which is why the
    headroom a filter costs is not a master-volume figure and usually is not a cost at all. To
    measure that cost honestly the signal has to be the sub feed, not the mono mix: mains
    low-passed into the sub bus, LFE 10 dB hotter, and the summed bus low-passed again on the
    way out. Both filters are Linkwitz-Riley 4th order, as `model/signal.py` in beqdesigner
    uses, there applied before and/or after the sum; here both, which is what a receiver does.

    `MAIN_GAIN`/`LFE_GAIN` are the attenuation that keeps the sum inside full scale, and they
    are beqdesigner's worst-case coherent-summation figure — `20*log10(n_mains) + LFE at +10 dB`
    — which for 7 mains is the 20.2 dB they encode. Because that is a *worst* case and real
    content does not sum coherently, the measured sub feed peaks 9 to 46 dB below full scale,
    and a correction of tens of dB at frequencies with no content in them costs nothing.
    """
    # A mono mix cannot reconstruct the separately low-passed channel contributions.
    if not material.channels:
        return None

    from scipy import signal as _signal

    section = _signal.butter(
        2, crossover_hz, btype="low", fs=float(material.fs), output="sos"
    )
    lr4 = np.vstack([section, section])
    total = np.zeros_like(material.mono_mix)
    for name, samples in material.channels.items():
        if name == "LFE":
            total = total + samples * LFE_GAIN
        else:
            total = total + _signal.sosfilt(lr4, samples) * MAIN_GAIN
    return _signal.sosfilt(lr4, total)


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
