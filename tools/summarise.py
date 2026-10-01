#!/usr/bin/env python3
"""Sanity-check extracted material before it goes anywhere.

    uv run python tools/summarise.py data/FILM.npz

Structural facts and an average spectrum — enough to tell a good extraction from a broken one.
Deliberately *not* the estimator: no scene selection, no envelopes, no rolloff identification.
Those are what the material is for, and a diagnostic that pre-empted them would be assuming
the answer it is supposed to help find.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy import signal

# the package is not installed into the venv, and tools/ rather than the repo root is what
# lands on sys.path when this is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beqforge.material import Material, load  # noqa: E402

BARS = " ▁▂▃▄▅▆▇█"


def spectrum_db(samples: np.ndarray, fs: int) -> tuple[np.ndarray, np.ndarray]:
    freqs, psd = signal.welch(samples, fs=fs, nperseg=4096, noverlap=2048)
    keep = (freqs >= 4.0) & (freqs <= 450.0)
    return freqs[keep], 10.0 * np.log10(psd[keep] + 1e-300)


def sparkline(freqs: np.ndarray, db: np.ndarray, columns: int = 60) -> str:
    edges = np.logspace(np.log10(freqs[0]), np.log10(freqs[-1]), columns + 1)
    binned = np.array(
        [
            db[(freqs >= lo) & (freqs < hi)].mean()
            if ((freqs >= lo) & (freqs < hi)).any()
            else np.nan
            for lo, hi in zip(edges[:-1], edges[1:], strict=True)
        ]
    )
    finite = binned[np.isfinite(binned)]
    lo, hi = finite.min(), finite.max()
    scale = (hi - lo) or 1.0
    return "".join(
        " "
        if not np.isfinite(v)
        else BARS[int(round((v - lo) / scale * (len(BARS) - 1)))]
        for v in binned
    )


def report(material: Material) -> None:
    print(f"\n{material}")
    peak = float(np.max(np.abs(material.mono_mix)))
    rms = float(np.sqrt(np.mean(material.mono_mix**2)))
    print(
        f"  peak {20 * np.log10(peak + 1e-300):+7.2f} dBFS    rms {20 * np.log10(rms + 1e-300):+7.2f} dBFS"
    )

    problems = []
    if material.duration_s < 600:
        problems.append(
            f"only {material.duration_s / 60:.1f} min — is this the whole programme?"
        )
    if peak >= 0.999:
        problems.append("mono mix reaches full scale — check for clipping upstream")
    if rms < 1e-5:
        problems.append("signal is essentially silent — wrong stream?")
    if "LFE" not in material.channels and material.channels:
        problems.append("no LFE channel — is this the right audio stream?")
    silent = [n for n, c in material.channels.items() if np.sqrt(np.mean(c**2)) < 1e-6]
    if silent:
        problems.append(f"silent channels: {', '.join(silent)}")

    freqs, db = spectrum_db(material.mono_mix, material.fs)
    print(
        f"\n  average spectrum, {freqs[0]:.0f}-{freqs[-1]:.0f} Hz (log), {db.min():.0f} to {db.max():.0f} dB"
    )
    print(f"  |{sparkline(freqs, db)}|")
    ticks = [5, 10, 20, 50, 100, 200, 400]
    positions = np.searchsorted(
        np.logspace(np.log10(freqs[0]), np.log10(freqs[-1]), 61), ticks
    )
    line = [" "] * 62
    for tick, pos in zip(ticks, positions, strict=True):
        label = str(tick)
        start = min(max(pos - len(label) // 2, 0), 62 - len(label))
        line[start : start + len(label)] = label
    print("   " + "".join(line).rstrip() + "  Hz")

    for name in ("LFE", "C", "L"):
        if name in material.channels:
            channel_freqs, channel_db = spectrum_db(
                material.channels[name], material.fs
            )
            print(f"  {name:>3} |{sparkline(channel_freqs, channel_db)}|")

    if problems:
        print("\n  worth a look:")
        for problem in problems:
            print(f"    - {problem}")
    else:
        print("\n  nothing looks wrong")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    for path in parser.parse_args().paths:
        report(load(path))
    print()
    return 0


if __name__ == "__main__":
    # Windows defaults a redirected/piped stdout to the system codepage rather than
    # UTF-8, which crashes on any non-ASCII output; force UTF-8 so a print never dies
    # on the encoding rather than the content.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
