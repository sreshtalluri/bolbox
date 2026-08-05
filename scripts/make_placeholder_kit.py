"""Generate the placeholder kits so bolbox makes a sound on day one.

There is no CC0 tabla one-shot library. Waiting for real recordings would mean
the sequencer, the scheduler and the round-robin logic all get written against
silence, and every timing bug would be indistinguishable from a missing sample.
So this script synthesizes a kit: physically plausible enough to hear whether a
`tirakita` landed where it should, deliberately not good enough to keep.

WHAT IS BEING MODELLED

A tabla dayan is famous for being nearly harmonic -- the syahi loads the
membrane so the first several modes fall close to integer ratios of the
fundamental, which is why it has a definite pitch at all. So the resonant dayan
strokes here are a small stack of near-harmonic partials with per-mode decay,
and the difference between `na`, `tin`, `tun` and `ta` is which modes get the
energy and how fast it leaves. The damped strokes (`te`, `ti`, `re`, `ki`) are
mostly a click plus filtered noise with a 50-100ms decay -- there is no pitch to
model because the hand is on the drum.

The bayan `ge` gets a glide: the fundamental starts high and falls, which is a
crude stand-in for the heel-pressure bend that gives `ge` its voice. Modelling
it here rather than as a playback-time pitch envelope keeps the v1 sampler dumb.

`dha` is rendered as the SUM of the `ge` and `na` renders at the same round
robin index. That makes the composite path demonstrable end to end -- a real
`dha` one-shot exists, so `Kit.resolve_composite("dha")` returns something and
the sampler fires one voice instead of two.

REPRODUCIBILITY

One fixed seed for everything. Re-running this script produces byte-identical
WAVs, so regenerating the kit is never a diff.

Usage:  python scripts/make_placeholder_kit.py
"""

from __future__ import annotations

import json
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
KITS_DIR = REPO_ROOT / "kits"

SAMPLE_RATE = 48_000
ROUND_ROBINS = 6
SEED = 0xB01B0

# Dayan tuned to C#4, which is where the one openly-licensed tabla stroke
# dataset we found is tuned, so a future swap lands in roughly the same place.
DAYAN_F0 = 277.18
BAYAN_F0 = 82.0


@dataclass(frozen=True)
class StrokeRecipe:
    """How to synthesize one stroke. Field meanings are in `render` below."""

    partials: tuple[tuple[float, float, float], ...] = ()  # (ratio, amp, decay_s)
    f0: float = DAYAN_F0
    duration: float = 0.5
    noise_amp: float = 0.0
    noise_decay: float = 0.03
    noise_band: tuple[float, float] = (200.0, 6000.0)  # Hz, the noise passband
    click_amp: float = 0.0
    bend: float = 0.0  # fractional pitch rise at t=0, decaying away
    bend_decay: float = 0.1
    attack: float = 0.0015


# Mode ratios are pulled slightly off integers on purpose. A perfectly harmonic
# stack sounds like an organ; the small stretch is what reads as a drum head.
#
# Every decay is kept near duration/4.5, so each render is already 40dB down
# before the file ends. A tail cut off mid-ring is a click, and a kit full of
# clicks is one you stop trusting your ears about.
RECIPES: dict[str, StrokeRecipe] = {
    # --- bayan ------------------------------------------------------------
    "ge": StrokeRecipe(
        f0=BAYAN_F0,
        partials=((1.0, 1.0, 0.125), (2.4, 0.22, 0.070), (3.7, 0.08, 0.040)),
        duration=0.55,
        noise_amp=0.10,
        noise_decay=0.012,
        noise_band=(40.0, 700.0),
        click_amp=0.25,
        bend=0.45,
        bend_decay=0.10,
    ),
    "ka": StrokeRecipe(
        f0=BAYAN_F0 * 1.15,
        partials=((1.0, 1.0, 0.035), (2.3, 0.30, 0.022)),
        duration=0.16,
        noise_amp=0.35,
        noise_decay=0.020,
        noise_band=(70.0, 1600.0),
        click_amp=0.55,
    ),
    "ki": StrokeRecipe(
        f0=BAYAN_F0 * 1.30,
        partials=((1.0, 0.85, 0.021), (2.3, 0.25, 0.014)),
        duration=0.10,
        noise_amp=0.45,
        noise_decay=0.014,
        noise_band=(140.0, 2800.0),
        click_amp=0.60,
    ),
    # --- dayan, resonant --------------------------------------------------
    "tun": StrokeRecipe(
        # Centre of the syahi: fundamental strongest, longest ring of the four.
        partials=(
            (1.0, 1.0, 0.130),
            (2.01, 0.55, 0.100),
            (2.99, 0.30, 0.070),
            (4.02, 0.16, 0.045),
        ),
        duration=0.60,
        noise_amp=0.08,
        noise_band=(200.0, 3000.0),
        noise_decay=0.006,
        click_amp=0.20,
    ),
    "na": StrokeRecipe(
        # Rim stroke: the fundamental is weaker and the upper modes carry it.
        partials=(
            (1.0, 0.45, 0.100),
            (2.01, 1.0, 0.090),
            (2.99, 0.55, 0.060),
            (4.02, 0.28, 0.040),
        ),
        duration=0.45,
        noise_amp=0.14,
        noise_decay=0.008,
        noise_band=(400.0, 6000.0),
        click_amp=0.30,
    ),
    "tin": StrokeRecipe(
        partials=(
            (1.0, 0.30, 0.090),
            (2.01, 0.80, 0.085),
            (2.99, 1.0, 0.060),
            (4.02, 0.40, 0.038),
        ),
        duration=0.42,
        noise_amp=0.12,
        noise_decay=0.007,
        noise_band=(500.0, 7000.0),
        click_amp=0.28,
    ),
    "ta": StrokeRecipe(
        # Kept audibly distinct from `na` only so a mis-mapped kit is obvious.
        partials=(
            (1.0, 0.50, 0.075),
            (2.01, 1.0, 0.070),
            (2.99, 0.45, 0.050),
            (4.02, 0.22, 0.032),
        ),
        duration=0.35,
        noise_amp=0.16,
        noise_decay=0.007,
        noise_band=(500.0, 7000.0),
        click_amp=0.35,
    ),
    # --- dayan, damped ----------------------------------------------------
    "te": StrokeRecipe(
        f0=DAYAN_F0 * 1.6,
        partials=((1.0, 0.35, 0.020), (1.9, 0.18, 0.014)),
        duration=0.10,
        noise_amp=0.85,
        noise_decay=0.018,
        noise_band=(800.0, 6000.0),
        click_amp=0.70,
    ),
    "ti": StrokeRecipe(
        f0=DAYAN_F0 * 1.9,
        partials=((1.0, 0.30, 0.016), (1.9, 0.15, 0.011)),
        duration=0.085,
        noise_amp=0.85,
        noise_decay=0.014,
        noise_band=(1200.0, 8000.0),
        click_amp=0.75,
    ),
    "re": StrokeRecipe(
        # The ring-finger flick: least energy of any stroke, and the one that
        # will disappear first at speed. Rendered quiet on purpose.
        f0=DAYAN_F0 * 1.7,
        partials=((1.0, 0.20, 0.012),),
        duration=0.065,
        noise_amp=0.70,
        noise_decay=0.010,
        noise_band=(1000.0, 7000.0),
        click_amp=0.45,
    ),
}

# Composites are summed from their component renders rather than synthesized
# fresh, so the one-shot really is the two strokes together.
COMPOSITES: dict[str, tuple[str, ...]] = {
    "dha": ("ge", "na"),
    "dhin": ("ge", "tin"),
    "dhun": ("ge", "tun"),
}

# Peak level per stroke after normalization. Damped strokes sit lower because on
# a real drum they are quieter, and a kit where `re` matches `tun` sounds wrong
# in a way no amount of sequencing accuracy fixes.
PEAK: dict[str, float] = {
    "ge": 0.90,
    "ka": 0.55,
    "ki": 0.42,
    "tun": 0.85,
    "na": 0.80,
    "tin": 0.78,
    "ta": 0.72,
    "te": 0.45,
    "ti": 0.40,
    "re": 0.28,
}


# -- synthesis --------------------------------------------------------------


def render(recipe: StrokeRecipe, rng: np.random.Generator, *, detune: float) -> np.ndarray:
    """One stroke render. Returns float32 in roughly [-1, 1], not normalized."""
    n = int(recipe.duration * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    out = np.zeros(n, dtype=np.float64)

    f0 = recipe.f0 * detune
    # Integrate instantaneous frequency so the glide has continuous phase; a
    # per-sample sin(2*pi*f(t)*t) would phase-jump and click.
    bend = 1.0 + recipe.bend * np.exp(-t / recipe.bend_decay)
    for ratio, amp, decay in recipe.partials:
        phase = 2 * np.pi * np.cumsum(f0 * ratio * bend) / SAMPLE_RATE
        out += amp * np.sin(phase) * np.exp(-t / max(decay, 1e-4))

    # Band-limited noise, not white. Unfiltered noise has its energy spread over
    # the whole spectrum and every damped stroke comes out as the same `tss`;
    # the passband is most of what distinguishes `ka` from `ti` by ear.
    low, high = recipe.noise_band
    noise = rng.standard_normal(n)
    # Two poles on the top, one on the bottom. A single pole is a 6dB/octave
    # slope, which leaves so much energy above the corner that every stroke
    # still reads as hiss.
    passband = _lowpass(_lowpass(noise, high), high)
    band = passband - _lowpass(passband, low)
    band /= max(float(np.max(np.abs(band))), 1e-9)

    if recipe.noise_amp > 0:
        out += recipe.noise_amp * band * np.exp(-t / max(recipe.noise_decay, 1e-4))
    if recipe.click_amp > 0:
        # The attack transient rides the same band, so a bayan does not get a
        # bright hi-hat tick stapled to the front of it.
        out += recipe.click_amp * band * np.exp(-t / 0.0012)

    attack = max(int(recipe.attack * SAMPLE_RATE), 1)
    out[:attack] *= np.linspace(0.0, 1.0, attack)
    return _fade_out(out).astype(np.float32)


def _lowpass(signal: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """One-pole lowpass by convolution. numpy only -- no scipy for a fixture."""
    tau = SAMPLE_RATE / (2 * np.pi * cutoff_hz)
    kernel = np.exp(-np.arange(int(tau * 6) + 2) / tau)
    return np.convolve(signal, kernel / kernel.sum(), mode="same")


def _fade_out(signal: np.ndarray, ms: float = 4.0) -> np.ndarray:
    """Taper the tail. A truncated decay is a click, and clicks read as bugs."""
    n = min(int(ms * SAMPLE_RATE / 1000), len(signal))
    signal[-n:] *= np.linspace(1.0, 0.0, n)
    return signal


def normalize(signal: np.ndarray, peak: float) -> np.ndarray:
    magnitude = float(np.max(np.abs(signal)))
    return signal if magnitude == 0 else signal * (peak / magnitude)


def write_wav(path: Path, signal: np.ndarray) -> None:
    """48kHz mono 16-bit. stdlib `wave` only -- no audio dependency for a test fixture."""
    clipped = np.clip(signal, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())


def render_all(round_robins: int) -> dict[str, list[np.ndarray]]:
    """Every stroke and composite, `round_robins` variants each.

    Variation is small and deliberate: a fresh noise seed per take plus a touch
    of detune and level. Enough that four `te`s in a row stop machine-gunning,
    not so much that the kit sounds untuned.
    """
    rng = np.random.default_rng(SEED)
    takes: dict[str, list[np.ndarray]] = {}

    for name, recipe in RECIPES.items():
        variants = []
        for _ in range(round_robins):
            detune = float(rng.uniform(0.995, 1.005))
            level = float(rng.uniform(0.88, 1.0))
            variants.append(normalize(render(recipe, rng, detune=detune), PEAK[name] * level))
        takes[name] = variants

    for name, parts in COMPOSITES.items():
        variants = [
            normalize(_mix([takes[p][i] for p in parts]), 0.95)
            for i in range(round_robins)
        ]
        takes[name] = variants

    return takes


def _mix(signals: list[np.ndarray]) -> np.ndarray:
    """Sum renders of unequal length, zero-padded to the longest.

    The bayan rings longer than the dayan, so a `dha` is as long as its `ge`.
    """
    length = max(len(s) for s in signals)
    out = np.zeros(length, dtype=np.float32)
    for signal in signals:
        out[: len(signal)] += signal
    return out


# -- kit assembly -----------------------------------------------------------


@dataclass(frozen=True)
class KitPlan:
    """What to write where. Keeps the two kits from drifting apart by hand."""

    directory: str
    name: str
    description: str
    round_robins: int
    sample_strokes: tuple[str, ...]
    sample_composites: tuple[str, ...] = ()
    aliases: dict[str, str] = field(default_factory=dict)
    midi_map: dict[str, int] = field(default_factory=dict)


PLACEHOLDER = KitPlan(
    directory="placeholder-tabla",
    name="placeholder-tabla",
    description=(
        "Synthesized stand-in tabla. Not recordings. Replace with your own drum "
        "-- see README.md in this folder."
    ),
    round_robins=ROUND_ROBINS,
    sample_strokes=tuple(RECIPES),
    sample_composites=tuple(COMPOSITES),
)

# Four sample sets covering ten strokes. This is the shape a bought sample pack
# arrives in, and the shape a bol -> drum-machine mapping needs, so it is worth
# having one in the repo that is exercised by the tests.
SPARSE = KitPlan(
    directory="sparse-demo",
    name="sparse-demo",
    description=(
        "Four sample sets covering the whole stroke vocabulary through alias_of. "
        "Proves the many-to-one path and gives the tests a real sparse fixture."
    ),
    round_robins=2,
    sample_strokes=("ge", "ka", "na", "te"),
    aliases={
        "ki": "ka",
        "tin": "na",
        "tun": "na",
        "ta": "na",
        "ti": "te",
        # A two-hop chain on purpose: re -> ti -> te. If chain resolution ever
        # regresses, this kit stops loading rather than quietly playing nothing.
        "re": "ti",
    },
    # A partial override, which is the whole point of the field: `ge` moves onto
    # a 909-ish kick and everything else keeps the canonical note from midi.py.
    midi_map={"ge": 36, "ka": 37},
)


def write_kit(plan: KitPlan, takes: dict[str, list[np.ndarray]]) -> Path:
    root = KITS_DIR / plan.directory
    root.mkdir(parents=True, exist_ok=True)
    for stale in root.glob("*.wav"):
        stale.unlink()

    strokes: dict[str, dict] = {}
    for stroke in plan.sample_strokes:
        strokes[stroke] = {
            "samples": _write_takes(root, stroke, takes[stroke][: plan.round_robins]),
            "gain_db": 0.0,
            "pitch_semitones": 0.0,
        }
    for alias, target in plan.aliases.items():
        strokes[alias] = {"alias_of": target}

    composites: dict[str, dict] = {}
    for bol in plan.sample_composites:
        composites[bol] = {
            "samples": _write_takes(root, bol, takes[bol][: plan.round_robins]),
            "gain_db": 0.0,
            "pitch_semitones": 0.0,
        }

    manifest: dict = {
        "schema_version": 1,
        "name": plan.name,
        "description": plan.description,
        "sample_rate_policy": "resample_on_load",
        "strokes": strokes,
    }
    if composites:
        manifest["composites"] = composites
    if plan.midi_map:
        manifest["midi_map"] = plan.midi_map

    (root / "kit.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return root


def _write_takes(root: Path, name: str, variants: list[np.ndarray]) -> list[str]:
    filenames = []
    for i, signal in enumerate(variants, start=1):
        filename = f"{name}_rr{i}.wav"
        write_wav(root / filename, signal)
        filenames.append(filename)
    return filenames


def main() -> None:
    takes = render_all(ROUND_ROBINS)
    for plan in (PLACEHOLDER, SPARSE):
        root = write_kit(plan, takes)
        wavs = sorted(root.glob("*.wav"))
        size = sum(w.stat().st_size for w in wavs)
        print(f"{plan.name}: {len(wavs)} wav files, {size / 1024:.0f} KiB -> {root}")


if __name__ == "__main__":
    main()
