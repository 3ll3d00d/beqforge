"""Audio sent by reference: a WAV under a shared root, instead of base64 in the request.

beqdesigner's `design/designer-by-reference.md` §3 (contract 1.2, HTTP binding only; tracked
here as IMPROVEMENT_PLAN R2b). An array may arrive as

    {"dtype": "float64", "shape": [N],
     "file": {"path": "t_1234/multichannel.wav", "channel": 3},
     "sha256": "<hex of the column's little-endian float64 bytes>"}

and this turns it back into the array the caller would otherwise have sent inline — or says
exactly why it cannot, naming the array, so the server answers 422 rather than guessing.
Everything is checked before the array is used: the path stays under the root after resolving
symlinks, the file is a WAV at the request's `fs`, the channel exists, the frame count is
`shape`, and the SHA-256 of the decoded column is the one the caller computed. That last check
is what makes a request by reference identical to the same request inline, and what catches a
file read while ffmpeg is still writing it.

Decoding is defined by arithmetic, not by a library, because the caller's `soundfile` is not
a dependency here: an integer sample `s` of `b` bits is `s / 2**(b-1)`, a float sample is
widened to float64. `scipy.io.wavfile` returns 24-bit PCM left-justified in int32, so both
24- and 32-bit divide by `2**31` — exact, since the scaling is a power of two.
"""

import hashlib
import posixpath
from pathlib import Path

import numpy as np
from scipy.io import wavfile

_SCALE = {np.dtype("int16"): 2.0**15, np.dtype("int32"): 2.0**31}


class UnusableReference(Exception):
    """A well-formed reference the designer cannot honour: HTTP 422, never a decline.

    Deliberately not a `ValueError`: a body that does not parse or fails the schema is the
    caller's malformed request (400); this is a valid request pointing at something wrong —
    a mount, a stale file — and the answer has to say which array and why.
    """

    def __init__(self, array: str, reason: str) -> None:
        super().__init__(f"{array}: {reason}")
        self.array = array
        self.reason = reason


def resolve(root: Path, relative: str, array: str) -> Path:
    """`relative` under `root`, or `UnusableReference` if it is not safely there.

    POSIX-style and relative; no `..` component; and its real path — after symlinks — must
    lie under the root's real path, so a symlink under the root pointing out of it is refused
    as surely as `../../etc/passwd`.
    """
    if not isinstance(relative, str) or not relative:
        raise UnusableReference(array, "file.path must be a non-empty string")
    if relative.startswith("/") or posixpath.isabs(relative) or "\\" in relative:
        raise UnusableReference(
            array, f"file.path {relative!r} must be relative (POSIX)"
        )
    if ".." in relative.split("/"):
        raise UnusableReference(array, f"file.path {relative!r} may not contain '..'")
    base = Path(root).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise UnusableReference(
            array, f"file.path {relative!r} resolves outside the root"
        )
    return target


def read_column(
    path: Path,
    channel: int,
    fs: int,
    array: str,
    opened: dict[Path, tuple[int, np.ndarray]] | None = None,
) -> np.ndarray:
    """One channel of a WAV as float64, by the contract's arithmetic.

    `opened` keeps each file decoded once per request: a request's channels usually all name
    one `multichannel.wav`.
    """
    opened = {} if opened is None else opened
    if path not in opened:
        try:
            opened[path] = wavfile.read(path)
        except FileNotFoundError:
            raise UnusableReference(array, f"{path.name} does not exist") from None
        except (OSError, ValueError) as unreadable:
            raise UnusableReference(
                array, f"{path.name} is not a readable WAV: {unreadable}"
            ) from None
    rate, data = opened[path]
    if rate != fs:
        raise UnusableReference(
            array,
            f"{path.name} is at {rate} Hz, the request's fs is {fs}; not resampled",
        )
    frames = data if data.ndim == 2 else data[:, np.newaxis]
    if (
        not isinstance(channel, int)
        or isinstance(channel, bool)
        or not (0 <= channel < frames.shape[1])
    ):
        raise UnusableReference(
            array, f"channel {channel!r} is not one of {path.name}'s {frames.shape[1]}"
        )
    column = frames[:, channel]
    if column.dtype.kind == "f":
        return column.astype(np.float64)
    scale = _SCALE.get(column.dtype)
    if scale is None:
        raise UnusableReference(
            array,
            f"{path.name} holds {column.dtype} samples; PCM s16/s24/s32 or float only",
        )
    return column.astype(np.float64) / scale


def digest(values: np.ndarray) -> str:
    """The bytes the contract digests: C-contiguous little-endian float64, 1-D."""
    return hashlib.sha256(
        np.ascontiguousarray(values, dtype="<f8").tobytes()
    ).hexdigest()


def array_from_reference(
    array: str,
    encoded: dict,
    root: Path | None,
    fs: int,
    opened: dict[Path, tuple[int, np.ndarray]] | None = None,
) -> np.ndarray:
    """The array a `file` reference names, checked end to end, or `UnusableReference`."""
    if root is None:
        raise UnusableReference(array, "no shared root is configured on this server")
    reference = encoded["file"]
    path = resolve(root, reference.get("path"), array)
    column = read_column(path, reference.get("channel"), fs, array, opened)
    shape = list(encoded.get("shape") or [])
    if shape != [len(column)]:
        raise UnusableReference(
            array, f"shape {shape} does not match {path.name}'s {len(column)} frames"
        )
    found = digest(column)
    if found != str(encoded["sha256"]).lower():
        raise UnusableReference(
            array,
            f"sha256 of {path.name} channel {reference.get('channel')} is {found}, "
            f"not the request's {encoded['sha256']} (a changed or half-written file?)",
        )
    return column
