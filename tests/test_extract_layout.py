"""R3: real ffmpeg decode, extraction and material-load channel identity round trips."""

import shutil
import subprocess
import sys

import numpy as np
import pytest

from beqforge.material import LFE_GAIN, MAIN_GAIN, load
from tools.extract import channel_names, main


# Independent ffmpeg speaker identities, in native order (ffmpeg -layouts).
LAYOUTS = {
    "mono": "FC",
    "stereo": "FL FR",
    "2.1": "FL FR LFE",
    "3.0": "FL FR FC",
    "3.0(back)": "FL FR BC",
    "4.0": "FL FR FC BC",
    "quad": "FL FR BL BR",
    "quad(side)": "FL FR SL SR",
    "3.1": "FL FR FC LFE",
    "4.1": "FL FR FC LFE BC",
    "5.0": "FL FR FC BL BR",
    "5.0(side)": "FL FR FC SL SR",
    "5.1": "FL FR FC LFE BL BR",
    "5.1(side)": "FL FR FC LFE SL SR",
    "6.0": "FL FR FC BC SL SR",
    "6.0(front)": "FL FR FLC FRC SL SR",
    "hexagonal": "FL FR FC BL BR BC",
    "6.1": "FL FR FC LFE BC SL SR",
    "6.1(back)": "FL FR FC LFE BL BR BC",
    "6.1(front)": "FL FR LFE FLC FRC SL SR",
    "7.0": "FL FR FC BL BR SL SR",
    "7.0(front)": "FL FR FC FLC FRC SL SR",
    "7.1": "FL FR FC LFE BL BR SL SR",
    "7.1(wide)": "FL FR FC LFE BL BR FLC FRC",
    "7.1(wide-side)": "FL FR FC LFE FLC FRC SL SR",
}
ALIASES = dict(
    FL="L",
    FR="R",
    FC="C",
    LFE="LFE",
    BL="Lb",
    BR="Rb",
    BC="Cb",
    SL="Ls",
    SR="Rs",
    FLC="Lc",
    FRC="Rc",
)


@pytest.mark.parametrize("layout,identities", LAYOUTS.items())
@pytest.mark.parametrize("fs", [1000, 48000])
def test_extraction_round_trip(tmp_path, monkeypatch, layout, identities, fs):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg and ffprobe required")
    speakers = identities.split()
    names = tuple("M" if layout == "mono" else ALIASES[s] for s in speakers)
    # Distinct tones identify every decoded column, also through the resampler.
    time = np.arange(fs) / fs
    samples = np.column_stack(
        [0.05 * np.sin(2 * np.pi * (20 + 15 * i) * time) for i in range(len(speakers))]
    )
    source = tmp_path / "source.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "f64le",
            "-ar",
            str(fs),
            "-ch_layout",
            layout,
            "-i",
            "-",
            "-c:a",
            "pcm_s24le",
            str(source),
        ],
        input=samples.astype("<f8").tobytes(),
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(sys, "argv", ["extract", str(source), "--out", str(tmp_path)])
    assert main() == 0
    material = load(tmp_path / "source.npz")
    assert material.layout == names
    assert material.source_layout == layout
    assert material.channel_mapping == "ffmpeg_layout_v1"
    assert tuple(material.channels) == names
    expected_mix = np.zeros(1000)
    for i, (speaker, name) in enumerate(zip(speakers, names)):
        expected = 0.05 * np.sin(2 * np.pi * (20 + 15 * i) * np.arange(1000) / 1000)
        np.testing.assert_allclose(
            material.channels[name][200:-200], expected[200:-200], atol=2e-6
        )
        expected_mix += material.channels[name] * (
            LFE_GAIN if speaker == "LFE" else MAIN_GAIN
        )
    np.testing.assert_allclose(material.mono_mix, expected_mix, atol=5e-9)


@pytest.mark.parametrize(
    "count,layout",
    [(3, None), (2, ""), (6, "unknown"), (3, "stereo"), (8, "5.1"), (24, "22.2")],
)
def test_invalid_layout_refused(count, layout):
    with pytest.raises(ValueError, match="layout"):
        channel_names(count, layout)


def test_legacy_material_is_unverified(tmp_path, caplog):
    path = tmp_path / "legacy.npz"
    mix = np.arange(20, dtype=np.float32)
    np.savez(
        path,
        mono_mix=mix,
        fs=1000,
        coverage="complete_programme",
        layout=["L", "R", "LFE"],
        channel_L=mix,
    )
    material = load(path)
    assert material.channel_mapping is None
    assert material.source_layout is None
    np.testing.assert_array_equal(material.mono_mix, mix)
    assert "Relabelling cannot repair" in caplog.text


def test_unknown_layout_fails_before_decode(tmp_path, monkeypatch, capsys):
    from tools import extract

    monkeypatch.setattr(sys, "argv", ["extract", str(tmp_path / "source.wav")])
    monkeypatch.setattr(
        extract, "probe", lambda *args: {"channels": 3, "sample_rate": 1000}
    )

    def unexpected_decode(*args):
        pytest.fail("ambiguous layout reached decoding")

    monkeypatch.setattr(extract, "decode", unexpected_decode)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "ambiguous channel layout" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.npz"))


def test_mono_only_keeps_layout_provenance(tmp_path, monkeypatch):
    from tools import extract

    monkeypatch.setattr(
        sys, "argv", ["extract", "source.wav", "--out", str(tmp_path), "--mono-only"]
    )
    monkeypatch.setattr(
        extract,
        "probe",
        lambda *args: {
            "channels": 3,
            "sample_rate": 1000,
            "channel_layout": "3.0",
        },
    )
    samples = np.eye(3)
    monkeypatch.setattr(extract, "decode", lambda *args: samples)
    assert main() == 0
    material = load(tmp_path / "source.npz")
    assert not material.channels
    assert material.layout == ("L", "R", "C")
    assert material.source_layout == "3.0"
    assert material.channel_mapping == "ffmpeg_layout_v1"
    np.testing.assert_allclose(material.mono_mix, MAIN_GAIN)
