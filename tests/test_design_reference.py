"""R2b: audio by reference — a WAV under a shared root decodes to exactly what inline sends.

The contract (beqdesigner `design/designer-by-reference.md` §3) defines the decoded array by
arithmetic; these tests write WAVs byte by byte so each sample format is exercised without a
WAV library, including the WAVE_FORMAT_EXTENSIBLE header ffmpeg writes for 24-bit
multichannel.
"""

import base64
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from beqforge import cache as C
from beqforge.designer import request_from_json
from beqforge.material import Material
from beqforge.reference import (
    UnusableReference,
    array_from_reference,
    digest,
    read_column,
    resolve,
)

FS = 1000


def write_wav(path: Path, frames: np.ndarray, fmt: str, fs: int = FS, extensible=False):
    """`frames` (n, channels) of raw sample values in `fmt`: s16, s24, s32, f32 or u8."""
    frames = np.atleast_2d(frames.T).T if frames.ndim == 1 else frames
    n, channels = frames.shape
    width = {"s16": 2, "s24": 3, "s32": 4, "f32": 4, "u8": 1}[fmt]
    if fmt == "s24":
        raw = b"".join(
            int(v).to_bytes(3, "little", signed=True) for v in frames.reshape(-1)
        )
    else:
        dtype = {"s16": "<i2", "s32": "<i4", "f32": "<f4", "u8": "u1"}[fmt]
        raw = frames.astype(dtype).tobytes()
    tag = 3 if fmt == "f32" else 1
    bits = width * 8
    block = width * channels
    if extensible:
        guid = (
            struct.pack("<H", tag)
            + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        )
        body = struct.pack("<HHIIHH", 0xFFFE, channels, fs, fs * block, block, bits)
        body += struct.pack("<HHI", 22, bits, 0) + guid
    else:
        body = struct.pack("<HHIIHH", tag, channels, fs, fs * block, block, bits)
    chunks = b"fmt " + struct.pack("<I", len(body)) + body
    chunks += b"data" + struct.pack("<I", len(raw)) + raw
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)
    return path


@pytest.mark.parametrize(
    "fmt, scale, extensible",
    [
        ("s16", 2.0**15, False),
        ("s24", 2.0**23, False),
        ("s24", 2.0**23, True),
        ("s32", 2.0**31, False),
    ],
)
def test_integer_pcm_decodes_as_s_over_two_to_the_bits_minus_one(
    tmp_path, fmt, scale, extensible
) -> None:
    rng = np.random.default_rng(0)
    top = int(scale)
    raw = rng.integers(-top, top, size=(500, 3))
    raw[0] = [-top, top - 1, 0]  # the extremes and zero
    path = write_wav(tmp_path / "x.wav", raw, fmt, extensible=extensible)
    for channel in range(3):
        decoded = read_column(path, channel, FS, "x")
        assert decoded.dtype == np.float64
        assert np.array_equal(decoded, raw[:, channel] / scale)


def test_float_samples_are_widened(tmp_path) -> None:
    raw = np.random.default_rng(1).uniform(-1, 1, size=(300, 2)).astype(np.float32)
    path = write_wav(tmp_path / "f.wav", raw, "f32")
    assert np.array_equal(read_column(path, 1, FS, "x"), raw[:, 1].astype(np.float64))


def test_unsigned_eight_bit_is_refused(tmp_path) -> None:
    path = write_wav(tmp_path / "u.wav", np.full((10, 1), 128), "u8")
    with pytest.raises(UnusableReference, match="PCM s16/s24/s32 or float"):
        read_column(path, 0, FS, "mono_mix")


@pytest.mark.parametrize(
    "bad, why",
    [
        ("/etc/passwd", "relative"),
        ("a/../../x.wav", "'..'"),
        ("..\\x.wav", "relative"),
        ("", "non-empty"),
    ],
)
def test_paths_that_leave_the_root_lexically_are_refused(tmp_path, bad, why) -> None:
    with pytest.raises(UnusableReference, match=why):
        resolve(tmp_path, bad, "LFE")


def test_a_symlink_out_of_the_root_is_refused(tmp_path) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    write_wav(outside / "secret.wav", np.zeros((10, 1), dtype=int), "s16")
    os.symlink(outside, root / "link")
    with pytest.raises(UnusableReference, match="outside the root"):
        resolve(root, "link/secret.wav", "LFE")


def test_a_path_under_the_root_resolves(tmp_path) -> None:
    (tmp_path / "t_1").mkdir()
    assert resolve(tmp_path, "t_1/mono.wav", "mono_mix") == (
        tmp_path / "t_1" / "mono.wav"
    )


def _reference(path: str, channel: int, column: np.ndarray, **overrides) -> dict:
    encoded = {
        "dtype": "float64",
        "shape": [len(column)],
        "file": {"path": path, "channel": channel},
        "sha256": digest(column),
    }
    encoded.update(overrides)
    return encoded


@pytest.fixture
def title(tmp_path):
    rng = np.random.default_rng(2)
    raw = rng.integers(-(2**23), 2**23, size=(800, 3))
    (tmp_path / "t_1").mkdir()
    write_wav(tmp_path / "t_1" / "multichannel.wav", raw, "s24", extensible=True)
    write_wav(tmp_path / "t_1" / "mono.wav", raw[:, :1], "s24")
    return tmp_path, raw / 2.0**23


@pytest.mark.parametrize(
    "override, why",
    [
        ({"file": {"path": "t_1/multichannel.wav", "channel": 3}}, "channel 3"),
        ({"file": {"path": "t_1/multichannel.wav", "channel": -1}}, "channel -1"),
        ({"shape": [799]}, "shape"),
        ({"sha256": "0" * 64}, "sha256"),
        ({"file": {"path": "t_1/missing.wav", "channel": 0}}, "does not exist"),
    ],
)
def test_each_check_refuses_with_the_array_named(title, override, why) -> None:
    root, columns = title
    encoded = _reference("t_1/multichannel.wav", 1, columns[:, 1], **override)
    with pytest.raises(UnusableReference, match=why) as refused:
        array_from_reference("LFE", encoded, root, FS)
    assert refused.value.array == "LFE"


def test_a_rate_mismatch_is_refused_never_resampled(title) -> None:
    root, columns = title
    encoded = _reference("t_1/multichannel.wav", 1, columns[:, 1])
    with pytest.raises(UnusableReference, match="not resampled"):
        array_from_reference("LFE", encoded, root, 2000)


def test_a_file_that_is_not_a_wav_is_refused(title) -> None:
    root, columns = title
    (root / "t_1" / "junk.wav").write_bytes(b"not a wav at all")
    encoded = _reference("t_1/junk.wav", 0, columns[:, 0])
    with pytest.raises(UnusableReference, match="not a readable WAV"):
        array_from_reference("mono_mix", encoded, root, FS)


def test_without_a_shared_root_a_reference_is_refused(title) -> None:
    _, columns = title
    encoded = _reference("t_1/mono.wav", 0, columns[:, 0])
    with pytest.raises(UnusableReference, match="no shared root"):
        array_from_reference("mono_mix", encoded, None, FS)


def _inline(values: np.ndarray) -> dict:
    as_f64 = np.ascontiguousarray(values, dtype="<f8")
    return {
        "dtype": "float64",
        "shape": list(as_f64.shape),
        "data_base64": base64.b64encode(as_f64.tobytes()).decode("ascii"),
    }


def _body(mono, channels) -> dict:
    return {
        "contract_version": "1.2",
        "fs": FS,
        "coverage": "complete_programme",
        "mono_mix": mono,
        "channels": channels,
        "bass_management": None,
    }


def test_a_request_by_reference_is_the_same_request_inline(title) -> None:
    """Same arrays, bit for bit, so the same cache key and the same record. Mixed forms too."""
    root, columns = title
    inline = request_from_json(
        _body(
            _inline(columns[:, 0]),
            {"L": _inline(columns[:, 1]), "R": _inline(columns[:, 2])},
        )
    )
    by_reference = request_from_json(
        _body(
            _reference("t_1/mono.wav", 0, columns[:, 0]),
            {
                "L": _reference("t_1/multichannel.wav", 1, columns[:, 1]),
                "R": _inline(columns[:, 2]),  # a request may mix the two
            },
        ),
        shared_root=root,
    )
    assert np.array_equal(inline.mono_mix, by_reference.mono_mix)
    for name in ("L", "R"):
        assert np.array_equal(inline.channels[name], by_reference.channels[name])

    def key(request):
        return C.material_fingerprint(
            Material(
                "designer-request",
                request.fs,
                request.mono_mix,
                request.channels,
                request.coverage,
            )
        )

    assert key(inline) == key(by_reference)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(data_base64="AAAA"),  # both forms
        lambda e: e.pop("sha256"),  # a reference without its digest
        lambda e: e.update(file="t_1/mono.wav"),  # file not an object
    ],
)
def test_malformed_references_are_bad_requests_not_unusable_ones(title, mutate) -> None:
    """400, not 422: the body itself is wrong."""
    root, columns = title
    encoded = _reference("t_1/mono.wav", 0, columns[:, 0])
    mutate(encoded)
    with pytest.raises(ValueError):
        request_from_json(_body(encoded, None), shared_root=root)


def test_an_unusable_reference_is_not_a_value_error() -> None:
    """The server's 400 handler catches ValueError; a 422 must not fall into it."""
    assert not issubclass(UnusableReference, ValueError)
