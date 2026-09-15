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
    layout: tuple[str, ...] = ()
    source_layout: str | None = None
    channel_mapping: str | None = None
    """Extraction provenance; None means historical or caller-supplied, not verified."""

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


@dataclass(frozen=True, slots=True)
class PlaybackParams:
    """Declared sub-feed model, not a claim about an arbitrary receiver or room."""

    crossover_hz: float = BM_CROSSOVER_HZ
    """LR4 mains low-pass before summing; a playback setting, not a target/reference band."""

    sub_lowpass_hz: float | Literal["crossover"] | None = "crossover"
    """LR4 on the summed bus: follow the crossover, use a separate corner, or None to omit."""

    main_gain_db: float = -20.2
    lfe_gain_db: float = -10.2
    """Assumed gains from extracted channel samples to the sub bus, relative to unity."""

    sub_gain_db: float = 0.0
    """Assumed output gain after summing/filtering; full scale remains a peak of 1."""

    def __post_init__(self) -> None:
        if not np.isfinite(self.crossover_hz) or self.crossover_hz <= 0:
            raise ValueError("playback crossover must be finite and positive")
        lowpass = self.bus_lowpass_hz
        if lowpass is not None and (not np.isfinite(lowpass) or lowpass <= 0):
            raise ValueError(
                "sub low-pass must be finite and positive, crossover, or None"
            )
        if not all(
            np.isfinite(g)
            for g in (self.main_gain_db, self.lfe_gain_db, self.sub_gain_db)
        ):
            raise ValueError("playback gains must be finite")

    @property
    def bus_lowpass_hz(self) -> float | None:
        return (
            self.crossover_hz
            if self.sub_lowpass_hz == "crossover"
            else self.sub_lowpass_hz
        )

    def description(self) -> str:
        bus = (
            "disabled"
            if self.bus_lowpass_hz is None
            else f"LR4 {self.bus_lowpass_hz:g} Hz"
        )
        return (
            f"assumed sub output: mains LR4 low-pass {self.crossover_hz:g} Hz; "
            f"sub-bus low-pass {bus}; gains mains {self.main_gain_db:+g} dB, "
            f"LFE {self.lfe_gain_db:+g} dB, sub {self.sub_gain_db:+g} dB; "
            "no room/speaker response"
        )


def bass_managed_sum(
    material: "Material",
    crossover_hz: float = BM_CROSSOVER_HZ,
    *,
    playback: PlaybackParams | None = None,
) -> np.ndarray | None:
    """Sub output under the declared model, in units where a peak of 1 is full scale.

    The positional crossover is retained for callers of the original model. `playback`
    supplies the complete configuration when given. Defaults reproduce the historical
    mains-LR4/sum/bus-LR4 arrangement and -20.2/-10.2 dB gains. Those are assumptions, not
    calibrated receiver levels. Bass-management filters run at the extraction sample rate;
    BEQ verification separately applies the declared device's published realisation.
    Missing channel decomposition cannot establish this signal and returns None.
    """
    if not material.channels:
        return None
    from scipy import signal as _signal

    model = playback or PlaybackParams(crossover_hz=crossover_hz)

    def lowpass(samples: np.ndarray, corner: float) -> np.ndarray:
        section = _signal.butter(
            2, corner, btype="low", fs=float(material.fs), output="sos"
        )
        return _signal.sosfilt(np.vstack([section, section]), samples)

    total = np.zeros_like(material.mono_mix)
    for name, samples in material.channels.items():
        if name == "LFE":
            total = total + samples * 10.0 ** (model.lfe_gain_db / 20.0)
        else:
            total = total + lowpass(samples, model.crossover_hz) * 10.0 ** (
                model.main_gain_db / 20.0
            )
    if model.bus_lowpass_hz is not None:
        total = lowpass(total, model.bus_lowpass_hz)
    return total * 10.0 ** (model.sub_gain_db / 20.0)


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
            layout=tuple(str(n) for n in data["layout"]) if "layout" in data else (),
            source_layout=str(data["source_layout"])
            if "source_layout" in data
            else None,
            channel_mapping=str(data["extraction_mapping"])
            if "extraction_mapping" in data
            else None,
            name=path.stem,
            fs=int(data["fs"]),
            mono_mix=np.asarray(data["mono_mix"], dtype=np.float64),
            channels=channels,
            coverage=str(data["coverage"]),  # type: ignore[arg-type]
        )
    if material.channel_mapping != "ffmpeg_layout_v1":
        logger.warning(
            f"{path}: unverified channel-layout provenance; re-extract or verify against "
            "the original source layout. Relabelling cannot repair a wrongly weighted mono_mix."
        )
    logger.info(f"Loaded {material}")
    return material


def load_all(directory: Path | str) -> list[Material]:
    """Every `.npz` in a directory, sorted by name."""
    return [load(p) for p in sorted(Path(directory).glob("*.npz"))]
