"""The onset detector is a pre-labeling aid. These pin that it finds clear,
separated syllable-like bursts within 20 ms and stays quiet on silence."""

from __future__ import annotations

import numpy as np

from bolbox.onsets import detect_onsets


def bursts(times: list[float], rate: int = 48000, seconds: float = 4.0) -> np.ndarray:
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.001, int(seconds * rate)).astype(np.float32)
    n = int(0.06 * rate)
    env = np.exp(-np.arange(n) / (0.012 * rate))
    for t in times:
        burst = (np.sin(2 * np.pi * 400 * np.arange(n) / rate) + 0.5 * rng.normal(0, 1, n)) * env * 0.5
        i = int(t * rate)
        x[i : i + n] += burst
    return x


def test_finds_each_burst_within_20ms() -> None:
    times = [0.3, 0.55, 0.8, 1.05, 1.5, 1.62, 1.74, 1.86, 2.4, 3.0]
    found = detect_onsets(bursts(times), 48000)
    assert len(found) == len(times)
    assert max(abs(a - b) for a, b in zip(found, times)) < 0.02


def test_silence_has_no_onsets() -> None:
    assert detect_onsets(np.zeros(48000, dtype=np.float32), 48000) == []
    assert detect_onsets(np.zeros(0, dtype=np.float32), 48000) == []


def test_sample_rate_does_not_matter() -> None:
    times = [0.2, 0.6, 1.0]
    assert len(detect_onsets(bursts(times, rate=16000, seconds=1.5), 16000)) == 3
