"""Peak-vs-average charts, in the shape the BEQ catalogue publishes them.

Debug output, not presentation: the numbers in the report say what a candidate scores, and
these say what it *looks* like. Four of the wrong outputs in §11 were caught by a person
looking at a curve rather than by any metric, so the curve is worth having to hand.

Axes follow the catalogue's convention rather than the analysis grid — linear frequency over
1-160 Hz, -10 to -80 dB — so a chart here can be put beside a published one and read the same
way. Everything else in the system works in log-frequency; this is the one place that does not,
deliberately.

Two diagnostic charts per candidate. The mono mix is the full-band target-construction domain;
final verification measures the sub output and retains its raw spectra in the candidate record.
The per-channel chart shows the component spectra. Spectral level alone cannot decide
whether a quiet channel would matter after restoration.

The peak panel carries a third curve the catalogue does not plot: the loudest second of the
programme. The peak envelope is a per-bin maximum over every frame, so it is a hull assembled
from many different moments and no instant of the film is ever shaped like it — which makes it
easy to read as an event when it is not one. Worse, a maximum over that many chi-squared bins
carries ~9 dB of pure estimator bias, so part of the hull's height is the statistic and not the
signal. The loudest second is one real moment, measured with a statistic that has neither
problem.

Colours are fixed per channel across every chart in a run (and every run), so a channel is
recognisable without reading the legend, and the same colour never means two things.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # written to file, never shown; plt.show() blocks a headless run

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from beqanalyser.design import BiquadSpec  # noqa: E402
from beqanalyser.design.filters import Realisation, unstable_sections  # noqa: E402
from beqanalyser.design.verify import device_waveform  # noqa: E402
from beqanalyser.design.material import Material  # noqa: E402

logger = logging.getLogger(__name__)

FREQ_LIMITS_HZ = (1.0, 160.0)
LEVEL_LIMITS_DB = (-80.0, -10.0)
NPERSEG = 4096

LOUDEST_SPAN_S = 1.0
"""Width of the "moment" the loudest-second curve is taken over, in seconds.

A perceptual number rather than an analytical one. Loudness integrates over ~100-200 ms, but
at 20 Hz a cycle is 50 ms and a level means nothing under about ten of them, so half a second
is the floor; LFE events run 0.5-2 s. `NPERSEG` is 4.1 s at the analysis rate, which averages
an impact together with its decay.
"""

LOUDEST_HOP = 128
"""Frame step within the span. Fine enough for ~8 frames per second at the analysis rate."""

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


@dataclass(slots=True)
class ProgrammeLevels:
    """The three curves the peak panel draws, plus which moment the third one is."""

    freqs: np.ndarray
    peak: np.ndarray
    average: np.ndarray
    loudest_second: np.ndarray
    loudest_index: int


_WINDOW = np.hanning(NPERSEG)
_SCALE = 2.0 / (np.sum(_WINDOW) ** 2)


def _periodograms(samples: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Windowed power spectra of the frames beginning at `starts`."""
    frames = np.lib.stride_tricks.sliding_window_view(samples, NPERSEG)[starts]
    return np.abs(np.fft.rfft(frames * _WINDOW, axis=1)) ** 2


def programme_levels_db(
    samples: np.ndarray, fs: float, frame_index: int | None = None
) -> ProgrammeLevels:
    """Per-bin peak and average level over the programme, and over its loudest second.

    Peak is the loudest frame each bin reaches, average the mean across all of them — the two
    curves the catalogue plots. The gap between them is how dynamic that bin is, which is why
    both are worth seeing: a bin whose peak and average have converged is carrying something
    stationary.

    `loudest_second` is the per-bin maximum over the frames centred within `LOUDEST_SPAN_S` of
    the highest-energy frame. **It is the only one of the three that is unbiased.** A bin is
    chi-squared with two degrees of freedom, so a lone periodogram sits `10*log10(exp(-gamma))`
    = −2.5 dB under its own mean and a maximum over N of them sits at `10*log10(ln N + gamma)`
    above it — +9.3 dB for a two-hour title, on stationary noise carrying no events at all.
    Over the ~8 frames in a second that term is ~0.0 dB, so what the curve shows is the moment
    rather than the estimator. `peak` keeps its bias deliberately — TODO.md has the open question
    of whether a high percentile should replace it, and why nothing has yet.

    Found in two passes because the first is the expensive one. The coarse hop locates the
    loudest frame over the whole programme; only its neighbourhood is re-framed at
    `LOUDEST_HOP`. Fine-hopping a whole title would be ~50k frames of 2049 bins — 820 MB to
    hold — for eight of them that are wanted.

    Each frame still spans `NPERSEG` samples, so the curve is localised to a second in its
    *centres* and to ~5 s in its support. It is a second's resolution on a longer event, not a
    second-long event.

    `frame_index` pins the choice to a moment picked elsewhere. The caller uses it to show the
    same moment before and after correction: re-choosing on the filtered signal would find
    whichever event the boost happened to favour, and two curves drawn from different moments
    say nothing about what the filter did to either.
    """
    coarse_hop = NPERSEG // 2
    coarse = np.arange(0, len(samples) - NPERSEG + 1, coarse_hop)
    power = _periodograms(samples, coarse)
    freqs = np.fft.rfftfreq(NPERSEG, 1.0 / fs)
    peak = 10.0 * np.log10(power.max(axis=0) * _SCALE + 1e-300)
    average = 10.0 * np.log10(power.mean(axis=0) * _SCALE + 1e-300)

    index = int(power.sum(axis=1).argmax()) if frame_index is None else frame_index
    anchor = int(coarse[index])
    half = int(round(LOUDEST_SPAN_S * fs / 2.0))
    fine = np.arange(
        max(0, anchor - half),
        min(len(samples) - NPERSEG, anchor + half) + 1,
        LOUDEST_HOP,
    )
    span = _periodograms(samples, fine) if len(fine) else power[index : index + 1]
    loudest = 10.0 * np.log10(span.max(axis=0) * _SCALE + 1e-300)

    keep = (freqs >= FREQ_LIMITS_HZ[0]) & (freqs <= FREQ_LIMITS_HZ[1])
    return ProgrammeLevels(
        freqs=freqs[keep],
        peak=peak[keep],
        average=average[keep],
        loudest_second=loudest[keep],
        loudest_index=index,
    )


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


def _plot_loudest(
    axis,
    before: ProgrammeLevels,
    after: ProgrammeLevels,
    colour: str,
    label: str,
) -> None:
    """One real moment, before and after, drawn subordinate to the hull it sits under.

    Both curves are the same moment — `after` was measured at `before`'s index — so the pair
    reads as what the correction did to it, and the vertical gap to the peak curve reads as
    how much of the hull no single moment accounts for. Read that gap net of the ~9 dB the
    hull carries as estimator bias (`programme_levels_db`), not as all signal.
    """
    axis.plot(
        before.freqs,
        before.loudest_second,
        color=colour,
        linewidth=0.7,
        linestyle=":",
        alpha=0.5,
        label=f"{label} loudest second",
    )
    axis.plot(
        after.freqs,
        after.loudest_second,
        color=colour,
        linewidth=0.7,
        linestyle="-.",
        alpha=0.5,
        label=f"{label} loudest second filtered",
    )


def render(
    label: str,
    filters: list[BiquadSpec],
    material: Material,
    channels: list[str],
    out_dir: Path,
    realisation: Realisation | None = None,
) -> list[Path]:
    """Write the mono and per-channel PvA charts for one candidate.

    `channels` is the set worth plotting — the caller decides which are relevant, so a channel
    excluded from the analysis is excluded from the picture too.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    fs = float(material.fs)
    device = realisation or Realisation()
    if filters and unstable_sections(filters, device):
        logger.warning(f"No waveform chart for {label}: unstable publication")
        return []
    written: list[Path] = []

    def chart(name: str, signals: dict[str, np.ndarray], title: str) -> Path:
        figure, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        # once per signal per state, not once per panel: the framing is the expensive part
        # and both panels read the same frames. The filtered levels are pinned to the
        # unfiltered signal's loudest frame so the dotted pair is one moment, not two.
        levels: dict[str, tuple[ProgrammeLevels, ProgrammeLevels]] = {}
        for channel, samples in signals.items():
            unfiltered = programme_levels_db(samples, fs)
            levels[channel] = (
                unfiltered,
                programme_levels_db(
                    device_waveform(filters, samples, fs, device),
                    fs,
                    frame_index=unfiltered.loudest_index,
                ),
            )
        for axis, which in zip(axes, ("peak", "average")):
            for channel, (before, after) in levels.items():
                colour = colour_for(channel)
                if which == "peak":
                    _plot_pair(
                        axis, before.freqs, before.peak, after.peak, colour, channel
                    )
                    _plot_loudest(axis, before, after, colour, channel)
                else:
                    _plot_pair(
                        axis,
                        before.freqs,
                        before.average,
                        after.average,
                        colour,
                        channel,
                    )
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


def render_cached(document: dict, out_dir: Path) -> list[Path]:
    """Redraw a run's charts from its record, with no material and no filtering.

    The curves were computed during the run and stored, so this is the same picture rather
    than an approximation of it. Applying a magnitude response to a stored curve would be the
    approximation — it is what beqdesigner shows, and it is not what `peak` means here, since
    each bin's loudest frame moves once the signal is filtered.
    """
    curves = document.get("curves")
    if not curves:
        raise ValueError("the record carries no curves; rerun with recording enabled")
    out_dir.mkdir(parents=True, exist_ok=True)
    freqs = np.asarray(curves["freqs"], dtype=np.float64)
    title = document["material"]["name"]
    channels = [n for n in curves["unfiltered"] if n != "mono"]
    written: list[Path] = []

    def chart(name: str, names: list[str], label: str, subtitle: str) -> Path:
        figure, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        for axis, which in zip(axes, ("peak", "average")):
            for channel in names:
                before = curves["unfiltered"][channel]
                after = curves["filtered"][label][channel]
                colour = colour_for(channel)
                _plot_pair(
                    axis,
                    freqs,
                    np.asarray(before[which]),
                    np.asarray(after[which]),
                    colour,
                    channel,
                )
                if which == "peak":
                    _plot_loudest(
                        axis,
                        ProgrammeLevels(
                            freqs,
                            np.asarray(before["peak"]),
                            np.asarray(before["average"]),
                            np.asarray(before["loudest_second"]),
                            int(before["loudest_index"]),
                        ),
                        ProgrammeLevels(
                            freqs,
                            np.asarray(after["peak"]),
                            np.asarray(after["average"]),
                            np.asarray(after["loudest_second"]),
                            int(before["loudest_index"]),
                        ),
                        colour,
                        channel,
                    )
            _style(axis, f"{which} — {subtitle}", label_x=which == "average")
            axis.legend(fontsize=7, ncols=2, loc="lower right")
        figure.suptitle(f"{title} — {label}", fontsize=11)
        figure.tight_layout()
        path = out_dir / f"{_slug(label)}_{name}.png"
        figure.savefig(path, dpi=110)
        plt.close(figure)
        return path

    for label in curves["filtered"]:
        written.append(chart("mono", ["mono"], label, "summed mono mix"))
        if channels:
            written.append(chart("channels", channels, label, "contributing channels"))
    logger.info(f"  redrawn: {', '.join(p.name for p in written)}")
    return written


def _slug(label: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
