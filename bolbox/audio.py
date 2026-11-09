"""Reading recitation WAVs, and converting other formats on import.

This is offline tooling for labeling and training. It is NOT part of the
runtime audio path, which stays in the browser (bolbox.md: "Avoid Python in
the runtime audio path").

The stdlib `wave` module cannot read float WAVs, and the browser's `encodeWav`
or a DAW export may well produce them, so the RIFF parsing is done here.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np

from .errors import RecordingError

_PCM = 1
_FLOAT = 3
_EXTENSIBLE = 0xFFFE


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Decode a WAV to mono float32 in [-1, 1]. Returns (samples, sample_rate)."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RecordingError("not a WAV file (no RIFF/WAVE header)")

    fmt: tuple[int, int, int, int] | None = None
    pcm: bytes | None = None
    pos = 12
    while pos + 8 <= len(data):
        cid, size = data[pos : pos + 4], struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + size]
        if cid == b"fmt ":
            tag, channels, rate = struct.unpack("<HHI", body[:8])
            bits = struct.unpack("<H", body[14:16])[0]
            if tag == _EXTENSIBLE and len(body) >= 26:
                tag = struct.unpack("<H", body[24:26])[0]
            fmt = (tag, channels, rate, bits)
        elif cid == b"data":
            pcm = body
        pos += 8 + size + (size & 1)

    if fmt is None or pcm is None:
        raise RecordingError("WAV has no fmt or data chunk")
    tag, channels, rate, bits = fmt
    if channels < 1:
        raise RecordingError("WAV declares zero channels")

    width = bits // 8
    usable = len(pcm) - len(pcm) % (width * channels)
    pcm = pcm[:usable]
    if tag == _FLOAT and bits == 32:
        x = np.frombuffer(pcm, dtype="<f4").astype(np.float32)
    elif tag == _FLOAT and bits == 64:
        x = np.frombuffer(pcm, dtype="<f8").astype(np.float32)
    elif tag == _PCM and bits == 16:
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    elif tag == _PCM and bits == 32:
        x = np.frombuffer(pcm, dtype="<i4").astype(np.float32) / 2147483648.0
    elif tag == _PCM and bits == 8:
        x = (np.frombuffer(pcm, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif tag == _PCM and bits == 24:
        raw = np.frombuffer(pcm, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
        ints = np.where(ints & 0x800000, ints - 0x1000000, ints)
        x = ints.astype(np.float32) / 8388608.0
    else:
        raise RecordingError(f"unsupported WAV encoding: format {tag}, {bits}-bit")

    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(x, dtype=np.float32), int(rate)


def encode_wav16(samples: np.ndarray, sample_rate: int) -> bytes:
    """Mono 16-bit PCM WAV. Used by tests and by the converter fallback."""
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, _PCM, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", len(pcm),
    )
    return header + pcm


def load_as_wav(path: Path) -> bytes:
    """Bytes of a WAV for `path`, converting non-WAV input with ffmpeg.

    A readable WAV is stored byte-for-byte: no resampling, no re-encoding,
    because every conversion is a chance to lose a transient. Anything else
    (m4a voice memos, mp3, webm) goes through ffmpeg to 16-bit PCM at its
    original sample rate.
    """
    data = path.read_bytes()
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        read_wav(data)  # fail at import time, not at labeling time
        return data
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RecordingError(
            f"{path.name}: not a WAV, and ffmpeg is not installed to convert it"
        )
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-ac", "1", "-c:a", "pcm_s16le",
         "-f", "wav", "-"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise RecordingError(
            f"{path.name}: ffmpeg could not convert it: "
            f"{result.stderr.decode(errors='replace').strip()[:200]}"
        )
    # ffmpeg streaming to a pipe cannot seek back to fill in the chunk sizes,
    # so they read 0xFFFFFFFF. Re-wrap with real sizes; already 16-bit mono,
    # so this is lossless.
    samples, rate = read_wav(result.stdout)
    return encode_wav16(samples, rate)
