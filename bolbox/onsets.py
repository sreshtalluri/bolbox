"""Syllable onset detection for pre-labeling. Not a model; a heuristic.

Used by the labeling tool to mark where syllables start on the waveform and to
count them, so a label whose bol count disagrees with what was heard is caught
while the clip is still on screen.

It is deliberately expected to UNDER-count compounds. bolbox.md says why: in
`tirakita` at speed the /r/ is a flap with almost no energy and there is often
no measurable onset between `ti` and `ra`. So the count is a sanity check with
a tolerance, never a constraint, and it never edits a label.

Method: log-magnitude spectral flux (half-wave rectified), smoothed, peak-picked
against a moving-median threshold with a minimum gap.
"""

from __future__ import annotations

import numpy as np

HOP_SEC = 0.005
WIN_SEC = 0.025
# 200 bpm sixteenths are 75 ms apart; a flap inside a compound can be ~40 ms.
MIN_GAP_SEC = 0.045


def _frames(x: np.ndarray, win: int, hop: int) -> np.ndarray:
    if len(x) < win:
        x = np.pad(x, (0, win - len(x)))
    count = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(count)[:, None]
    return x[idx]


def onset_envelope(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    hop = max(1, int(round(HOP_SEC * sample_rate)))
    win = max(hop * 2, int(round(WIN_SEC * sample_rate)))
    frames = _frames(np.asarray(samples, dtype=np.float32), win, hop)
    spec = np.abs(np.fft.rfft(frames * np.hanning(win)[None, :], axis=1))
    # Speech energy for syllable onsets sits mostly below ~4 kHz.
    freqs = np.fft.rfftfreq(win, 1.0 / sample_rate)
    band = (freqs >= 80) & (freqs <= 4000)
    logspec = np.log1p(1000.0 * spec[:, band])
    flux = np.maximum(0.0, np.diff(logspec, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    # Light smoothing (~15 ms) so one consonant burst is one peak.
    k = 3
    flux = np.convolve(flux, np.ones(k) / k, mode="same")
    peak = flux.max()
    return flux / peak if peak > 0 else flux


def detect_onsets(
    samples: np.ndarray,
    sample_rate: int,
    *,
    sensitivity: float = 1.0,
) -> list[float]:
    """Onset times in seconds, ascending."""
    if len(samples) == 0 or sample_rate <= 0:
        return []
    env = onset_envelope(samples, sample_rate)
    if not env.any():
        return []

    # Gate on loudness too, so breath and room noise between phrases do not
    # produce onsets: a frame must be within ~35 dB of the clip's loudest.
    hop = max(1, int(round(HOP_SEC * sample_rate)))
    win = max(hop * 2, int(round(WIN_SEC * sample_rate)))
    rms = np.sqrt((_frames(np.asarray(samples, np.float32), win, hop) ** 2).mean(axis=1))
    rms = np.pad(rms, (0, max(0, len(env) - len(rms))))[: len(env)]
    loud = rms > rms.max() * 10 ** (-35 / 20)

    radius = max(1, int(round(0.15 / HOP_SEC)))
    padded = np.pad(env, radius, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * radius + 1)
    median = np.median(windows, axis=1)[: len(env)]
    threshold = median + (0.08 / max(sensitivity, 1e-3))

    min_gap = int(round(MIN_GAP_SEC / HOP_SEC))
    onsets: list[int] = []
    for i in range(1, len(env) - 1):
        if not (env[i] >= env[i - 1] and env[i] > env[i + 1]):
            continue
        if env[i] < threshold[i] or not loud[min(len(loud) - 1, i + 2)]:
            continue
        if onsets and i - onsets[-1] < min_gap:
            if env[i] > env[onsets[-1]]:
                onsets[-1] = i
            continue
        onsets.append(i)
    # Flux at frame i rises while the attack is still inside the window, which
    # reads ~15 ms early on synthetic bursts; shift by that measured lead.
    lead = 0.6 * WIN_SEC
    return [round(i * HOP_SEC + lead, 4) for i in onsets]

