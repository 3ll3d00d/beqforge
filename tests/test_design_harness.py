"""The synthetic ground truth of AUTOMATED_DESIGN.md §6.1.

The harness has to be trustworthy before anything scored against it means much, so these
check the two properties the plan actually relies on: that a constructed negative really does
carry content to DC, and that an injected rolloff really is the one that lands in the signal.
"""

import numpy as np
import pytest
from scipy import signal

from beqanalyser.design import Alignment, HighPass
from beqanalyser.design.filters import high_pass_sos, magnitude_db
from beqanalyser.design.harness import (
    SyntheticProfile,
    apply_high_pass,
    injection_sweep,
    synthesise,
)

FS = 1000.0


def _welch_db(samples: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    freqs, psd = signal.welch(samples, fs=fs, nperseg=2048, noverlap=1024)
    keep = freqs > 0
    return freqs[keep], 10.0 * np.log10(psd[keep] + 1e-300)


def test_constructed_negative_is_flat_to_the_bottom_of_the_band() -> None:
    """The point of a negative: nothing was removed, so nothing should look removed."""
    samples = synthesise(SyntheticProfile(duration_s=300.0), FS, seed=1)
    freqs, db = _welch_db(samples, FS)
    bottom = np.median(db[(freqs >= 5.0) & (freqs <= 15.0)])
    top = np.median(db[(freqs >= 100.0) & (freqs <= 400.0)])
    assert abs(bottom - top) < 1.5


def test_synthesis_is_deterministic() -> None:
    profile = SyntheticProfile(duration_s=60.0)
    assert np.array_equal(
        synthesise(profile, FS, seed=7), synthesise(profile, FS, seed=7)
    )
    assert not np.array_equal(
        synthesise(profile, FS, seed=7), synthesise(profile, FS, seed=8)
    )


def test_rumble_lifts_only_the_bottom_of_the_band() -> None:
    """§3.3's quiet envelope exists to cancel this, so the harness must be able to add it."""
    clean = SyntheticProfile(duration_s=300.0)
    rumbly = SyntheticProfile(duration_s=300.0, rumble_db=-25.0, rumble_hz=12.0)
    freqs, clean_db = _welch_db(synthesise(clean, FS, seed=2), FS)
    _, rumble_db = _welch_db(synthesise(rumbly, FS, seed=2), FS)

    below = (freqs >= 5.0) & (freqs <= 10.0)
    above = (freqs >= 100.0) & (freqs <= 400.0)
    assert np.median(rumble_db[below] - clean_db[below]) > 10.0
    assert abs(np.median(rumble_db[above] - clean_db[above])) < 1.0


@pytest.mark.parametrize(
    "hp",
    [
        HighPass(Alignment.BUTTERWORTH, 2, 25.0),
        HighPass(Alignment.LINKWITZ_RILEY, 4, 30.0),
        HighPass(Alignment.BUTTERWORTH, 8, 20.0),
    ],
)
def test_injection_puts_exactly_the_named_rolloff_into_the_signal(hp: HighPass) -> None:
    """Ground truth is only ground truth if the signal really carries it."""
    source = synthesise(SyntheticProfile(duration_s=600.0), FS, seed=3)
    filtered = apply_high_pass(source, hp, FS)

    freqs, source_db = _welch_db(source, FS)
    _, filtered_db = _welch_db(filtered, FS)
    band = (freqs >= 8.0) & (freqs <= 400.0)
    measured = (filtered_db - source_db)[band]
    # a PSD ratio in dB is 10*log10(|H|^2), i.e. magnitude_db as it stands
    expected = magnitude_db(high_pass_sos(hp, FS), freqs[band], FS)

    assert np.max(np.abs(measured - expected)) < 3.0


def test_sweep_yields_the_baseline_first_and_skips_impossible_orders() -> None:
    source = synthesise(SyntheticProfile(duration_s=30.0), FS, seed=4)
    cases = list(
        injection_sweep(
            source,
            FS,
            corners_hz=(20.0, 30.0),
            alignments=(Alignment.BUTTERWORTH, Alignment.LINKWITZ_RILEY),
            orders=(2, 3, 4),
        )
    )
    assert cases[0].is_negative
    assert sum(c.is_negative for c in cases) == 1
    # Butterworth 2/3/4 and Linkwitz-Riley 2/4, at two corners each
    assert len(cases) == 1 + (3 + 2) * 2
    assert all(
        c.injected.order % 2 == 0
        for c in cases[1:]
        if c.injected.alignment.is_linkwitz_riley
    )


def test_material_round_trips_through_the_extractor(tmp_path) -> None:
    """`tools/extract.py` is how material arrives; the loader must reproduce §2's shapes."""
    import subprocess

    from beqanalyser.design.material import load

    source = tmp_path / "probe.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=d=10:c=pink:r=48000",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=30:duration=10:sample_rate=48000",
            "-filter_complex",
            "[0:a][1:a][0:a][1:a][0:a][1:a]amerge=inputs=6[a]",
            "-map",
            "[a]",
            "-c:a",
            "pcm_s24le",
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "tools/extract.py",
            str(source),
            "--out",
            str(tmp_path),
        ],
        check=True,
    )

    material = load(tmp_path / "probe.npz")
    assert material.fs == 1000
    assert material.coverage == "complete_programme"
    assert material.mono_mix.dtype == np.float64
    assert set(material.channels) == {"L", "R", "C", "LFE", "Ls", "Rs"}
    assert all(len(c) == len(material.mono_mix) for c in material.channels.values())
    assert material.duration_s == pytest.approx(10.0, abs=0.1)
