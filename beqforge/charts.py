"""Peak-vs-average charts, in the shape the BEQ catalogue publishes them.

Debug output, not presentation: the numbers in the report say what a candidate scores, and
these say what it *looks* like. Four of the wrong outputs in §11 were caught by a person
looking at a curve rather than by any metric, so the curve is worth having to hand.

Axes follow the catalogue's convention rather than the analysis grid — linear frequency over
1-160 Hz, -10 to -80 dB — so a chart here can be put beside a published one and read the same
way. Everything else in the system works in log-frequency; this is the one place that does not,
deliberately.

Two charts per candidate. The mono mix is what the filter is judged on and what is listened to;
the per-channel chart says where the mix's low end comes from, and carries only the channels
that clear `min_passband_share` — a channel supplying 0.1% of the passband is noise on a plot
as much as it is in the analysis.

Colours are fixed per channel across every chart in a run (and every run), so a channel is
recognisable without reading the legend, and the same colour never means two things.
"""

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # written to file, never shown; plt.show() blocks a headless run

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

from beqanalyser.design import BiquadSpec  # noqa: E402
from beqanalyser.design.filters import biquad_sos  # noqa: E402
from beqanalyser.design.material import Material  # noqa: E402

logger = logging.getLogger(__name__)

FREQ_LIMITS_HZ = (1.0, 160.0)
LEVEL_LIMITS_DB = (-80.0, -10.0)
NPERSEG = 4096

CHANNEL_COLOURS: dict[str, str] = {
    "L": "#1f77b4",
    "R": "#d62728",
    "C": "#2ca02c",
    "LFE": "#9467bd",
    "Lb": "#8c564b",
    "Rb": "#e377c2",
    "Ls": "#ff7f0e",
    "Rs": "#7f7f7f",
    "M": "#17becf",
    "mono": "#17becf",
}
"""One colour per known channel, everywhere. Unknown names fall back to a stable hash."""

FALLBACK_COLOURS = ("#bcbd22", "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5")


def colour_for(name: str) -> str:
    if name in CHANNEL_COLOURS:
        return CHANNEL_COLOURS[name]
    return FALLBACK_COLOURS[sum(map(ord, name)) % len(FALLBACK_COLOURS)]


def peak_and_average_db(
    samples: np.ndarray, fs: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-bin peak and average level over the programme, in dBFS.

    Peak is the loudest frame each bin reaches, average the mean across all of them — the two
    curves the catalogue plots. The gap between them is how dynamic that bin is, which is why
    both are worth seeing: a bin whose peak and average have converged is carrying something
    stationary.
    """
    frames = np.lib.stride_tricks.sliding_window_view(samples, NPERSEG)[:: NPERSEG // 2]
    window = np.hanning(NPERSEG)
    power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
    freqs = np.fft.rfftfreq(NPERSEG, 1.0 / fs)
    scale = 2.0 / (np.sum(window) ** 2)
    peak = 10.0 * np.log10(power.max(axis=0) * scale + 1e-300)
    average = 10.0 * np.log10(power.mean(axis=0) * scale + 1e-300)
    keep = (freqs >= FREQ_LIMITS_HZ[0]) & (freqs <= FREQ_LIMITS_HZ[1])
    return freqs[keep], peak[keep], average[keep]


def _style(axis, title: str, label_x: bool) -> None:
    axis.set_xlim(*FREQ_LIMITS_HZ)
    axis.set_ylim(*LEVEL_LIMITS_DB)
    if label_x:
        axis.set_xlabel("Hz")
    axis.set_ylabel("dBFS")
    axis.set_title(title, fontsize=10)
    axis.grid(True, which="both", alpha=0.25, linewidth=0.5)
    axis.set_xticks(np.arange(0, FREQ_LIMITS_HZ[1] + 1, 20))


def _plot_pair(
    axis,
    freqs: np.ndarray,
    unfiltered: np.ndarray,
    filtered: np.ndarray,
    colour: str,
    label: str,
) -> None:
    axis.plot(
        freqs, unfiltered, color=colour, linewidth=1.1, alpha=0.6, label=f"{label}"
    )
    axis.plot(
        freqs,
        filtered,
        color=colour,
        linewidth=1.6,
        linestyle="--",
        label=f"{label} filtered",
    )


def render(
    label: str,
    filters: list[BiquadSpec],
    material: Material,
    channels: list[str],
    out_dir: Path,
) -> list[Path]:
    """Write the mono and per-channel PvA charts for one candidate.

    `channels` is the set worth plotting — the caller decides which are relevant, so a channel
    excluded from the analysis is excluded from the picture too.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    fs = float(material.fs)
    sos = biquad_sos(filters, fs)
    written: list[Path] = []

    def chart(name: str, signals: dict[str, np.ndarray], title: str) -> Path:
        figure, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        for axis, which in zip(axes, ("peak", "average")):
            for channel, samples in signals.items():
                freqs, peak, average = peak_and_average_db(samples, fs)
                _, peak_f, average_f = peak_and_average_db(
                    signal.sosfilt(sos, samples), fs
                )
                before = peak if which == "peak" else average
                after = peak_f if which == "peak" else average_f
                _plot_pair(axis, freqs, before, after, colour_for(channel), channel)
            _style(axis, f"{which} — {title}", label_x=which == "average")
            axis.legend(fontsize=7, ncols=2, loc="lower right")
        figure.suptitle(f"{material.name} — {label}", fontsize=11)
        figure.tight_layout()
        path = out_dir / f"{_slug(label)}_{name}.png"
        figure.savefig(path, dpi=110)
        plt.close(figure)
        return path

    written.append(chart("mono", {"mono": material.mono_mix}, "summed mono mix"))
    present = {c: material.channels[c] for c in channels if c in material.channels}
    if present:
        written.append(chart("channels", present, "contributing channels"))
    logger.info(f"  charts: {', '.join(p.name for p in written)}")
    return written


def _slug(label: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
