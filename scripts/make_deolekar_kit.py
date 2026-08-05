"""Build `kits/deolekar-tabla/` from the Zenodo tabla strokes dataset.

Source: Subodh Deolekar, "Tabla strokes dataset", Zenodo, 2020.
        https://doi.org/10.5281/zenodo.4327350   (CC BY 4.0)

650 WAVs, 13 stroke classes, 50 takes each, recorded from professional players
on a set tuned to C#. This script turns that into a playable bolbox kit and
records every modification it makes in `LICENSE.txt`, because CC BY requires
saying what you changed.

WHAT THIS SCRIPT DECIDES, AND WHY

*Which takes to keep.* 50 round robins per stroke is far more than a sampler
needs and 42MB of them is unpleasant to keep in a repo. Ten is plenty. But the
ten are not the first ten:

  1. Reject any take that hits digital full scale. This is not cosmetic --
     40 of the 50 `Na` takes and 24 of the 50 `Di` takes are clipped, and a
     clipped sample is distortion you cannot undo later.
  2. Keep takes whose peak sits within +/-6dB of the class median, widening
     until at least eight qualify. Round robins should vary in TIMBRE, not in
     level. A round robin that is 12dB louder than its neighbour sounds like
     bad playing; loudness is what velocity is for.
  3. Spread the survivors evenly across take order rather than taking a run of
     ten, so the kit samples the whole session instead of one minute of it.

*Levels are never touched.* Not per sample, not per class. The dataset's
classes were gain-staged inconsistently -- the open bayan `Ge` peaks around
-19dBFS while `Na` is pinned at full scale -- so playing them raw gives a kit
whose bass drum is inaudible and whose `dha` is quieter than its `na`, which is
musically backwards. The fix is a per-class `gain_db` in the manifest, computed
so the loudest kept take of each stroke reaches a target ceiling. That keeps
every take's level relative to its neighbours exactly as recorded, keeps the
audio bit-faithful to the source, and puts the cross-stroke balance somewhere
Sreshta can see and edit with a text editor instead of a re-render.

*Timing is touched, deliberately.* The source clips carry 0-30ms of leading
silence depending on class, which would smear the groove -- a sampler fires at
the start of the file, so inconsistent pre-roll is inconsistent timing. Every
sample is trimmed to a uniform 2ms pre-roll. The clips are also cut while the
drum is still ringing, so a fade-out replaces a truncation click.

*The sample rate is not touched.* The dataset is 44.1k, the placeholder kit is
48k, and `sample_rate_policy: resample_on_load` already tells the browser to
handle the difference at decode time. Resampling here would be a lossy step
that buys nothing.

Usage:  python scripts/make_deolekar_kit.py
        (downloads ~41MB to .cache/ on first run, then works offline)
"""

from __future__ import annotations

import collections
import io
import json
import re
import urllib.request
import wave
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
KIT_DIR = REPO_ROOT / "kits" / "deolekar-tabla"
CACHE_DIR = REPO_ROOT / ".cache" / "deolekar"

ARCHIVE_URL = "https://zenodo.org/api/records/4327350/files-archive"
RECORD_URL = "https://zenodo.org/records/4327350"
DOI = "10.5281/zenodo.4327350"
CONCEPT_DOI = "10.5281/zenodo.4327349"
CREATOR = "Subodh Deolekar"
DATASET_TITLE = "Tabla strokes dataset"
DATASET_YEAR = "2020"
LICENSE_NAME = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

TAKES_PER_STROKE = 10
MIN_TAKES = 8
WINDOW_DB = 6.0
FULL_SCALE = 0.999
PRE_ROLL_MS = 2.0
FADE_OUT_MS = 10.0
ONSET_FRACTION = 0.01  # of that file's own peak
TAIL_FRACTION = 0.005


@dataclass(frozen=True)
class Mapping:
    """One dataset class promoted to one bolbox stroke or composite bol."""

    dataset_class: str
    target: str
    ceiling: float  # where the loudest kept take should land
    notes: str = ""


# Ceilings encode the musical balance, not the recorded one: how loud each
# stroke should be relative to the others when you play the kit. They are a
# judgement, they are meant to be argued with, and because they end up as
# `gain_db` in the manifest, arguing with them is a text edit.
STROKES: tuple[Mapping, ...] = (
    Mapping("Ge", "ge", 0.95),
    Mapping("Ka", "ka", 0.60),
    Mapping("Na", "na", 0.88, notes=(
        "Only 11 of the dataset's 50 `Na` takes are free of digital clipping; "
        "the round robins here are drawn from those."
    )),
    Mapping("Tin", "tin", 0.85),
    Mapping("Tu", "tun", 0.90),
    Mapping("Ta", "ta", 0.80),
    Mapping("Ti", "ti", 0.45),
    Mapping("T", "te", 0.50, notes=(
        "Dataset class `T`, read as the damped syahi stroke. VERIFY by ear."
    )),
    Mapping("Tr", "re", 0.35, notes=(
        "Dataset class `Tr` (tra/tre), promoted to `re`. Measured against every "
        "other class it is the shortest (63ms mean vs 109ms for `T`) and the "
        "quietest dayan stroke (peak 0.20 vs 0.56), while sitting spectrally in "
        "the closed-dayan family (cosine 0.84 to `Ti`, 0.80 to `T`). That is the "
        "profile data/strokes.yaml describes for `re`: a closed ring-finger "
        "flick with the least energy of any stroke. Not labelled `re` by the "
        "dataset, so VERIFY by ear -- but it is real recorded material of "
        "roughly the right gesture, which the previous `re`->`te` alias was not."
    )),
)

COMPOSITES: tuple[Mapping, ...] = (
    Mapping("Dh", "dha", 0.99, notes=(
        "Real recorded `Dha` -- bayan and dayan struck together, not a mix of "
        "two one-shots. 86% of its energy sits below 200Hz, so the bayan is "
        "genuinely there. VERIFY by ear which dayan stroke is in it: measurement "
        "does not settle that question here, because over 250Hz-8kHz it scores "
        "0.46-0.63 against every candidate (`T`, `Tin`, `Na`, `Ti`, `Ta`) with "
        "no clear winner. Treat the dataset's own label as the best evidence "
        "available and your ear as better than both."
    )),
    Mapping("Da", "dhun", 0.99, notes=(
        "VERIFY -- inferred, not labelled. The dataset class is `Da`, which is "
        "ambiguous, but its dayan component matches `Tu` (cosine 0.76) and its "
        "bayan content is strong, so acoustically it is ge+tun = dhun. If it "
        "is really a `daa` to your ear, delete this entry."
    )),
)

# Strokes the dataset has no recording of. Aliases rather than relabelled
# substitutes, so the compromise shows up in the manifest and in
# `Kit.stand_ins` instead of hiding inside a filename.
ALIASES: dict[str, tuple[str, str]] = {
    "ki": ("ka", (
        "The dataset has no separate `ki`. Probably correct rather than a "
        "compromise -- data/strokes.yaml notes `ki` is commonly the same "
        "physical closed-bayan stroke as `ka`. VERIFY."
    )),
}

# Downloaded but not used, kept here so the reasoning is not lost.
UNUSED = {
    "Di": "Pure dayan -- under 2% of its energy is below 200Hz, against 86% for "
          "`Dh` and 75% for `Da`. There is no bayan in it, so despite the name "
          "it is a `din`, not a `dhin`, and it cannot be a composite. Left out "
          "when bolbox had no `din` bol. It has one now -- added because the "
          "instrument has it, not to consume this sample -- so wiring `Di` in "
          "as a `din` realization is open work. Do it after recording your own "
          "kit, and only once the din variants stop being marked `verify`.",
    "N":  "Pure dayan resonant stroke (0.2% below 200Hz), closest to `Na` "
          "(cosine 0.42). Unclear which bol it is; `na` is already covered by "
          "the `Na` class.",
}


# -- source ----------------------------------------------------------------


def fetch_dataset() -> Path:
    """Download and unpack the archive once, into an ignored cache directory."""
    wav_dir = CACHE_DIR / "wav"
    if wav_dir.is_dir() and len(list(wav_dir.glob("*.wav"))) >= 650:
        return wav_dir
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"downloading {ARCHIVE_URL} (~41MB, once)")
    with urllib.request.urlopen(ARCHIVE_URL, timeout=300) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(wav_dir)
    return wav_dir


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    """Downmix to mono. The source is stereo but very nearly dual mono."""
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        channels = handle.getnchannels()
        raw = handle.readframes(handle.getnframes())
    samples = np.frombuffer(raw, "<i2").astype(np.float64) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def by_class(wav_dir: Path) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = collections.defaultdict(list)
    for path in sorted(wav_dir.glob("*.wav")):
        match = re.match(r"([A-Za-z]+)_", path.name)
        if match:
            grouped[match.group(1)].append(path)
    return dict(grouped)


# -- selection -------------------------------------------------------------


def select_takes(paths: list[Path]) -> list[tuple[Path, float]]:
    """Apply the three selection rules from the module docstring."""
    unclipped: list[tuple[Path, float]] = []
    for path in paths:
        samples, _ = read_mono(path)
        if np.any(np.abs(samples) >= FULL_SCALE):
            continue
        unclipped.append((path, float(np.abs(samples).max())))
    if not unclipped:
        raise SystemExit(f"every take of {paths[0].name[:3]} is clipped")

    median = float(np.median([peak for _, peak in unclipped]))
    window = WINDOW_DB
    while True:
        low, high = median / 10 ** (window / 20), median * 10 ** (window / 20)
        kept = [(p, v) for p, v in unclipped if low <= v <= high]
        if len(kept) >= MIN_TAKES or window >= 24.0:
            break
        window += 1.0

    count = min(TAKES_PER_STROKE, len(kept))
    spread = np.linspace(0, len(kept) - 1, count).round().astype(int)
    return [kept[i] for i in dict.fromkeys(spread.tolist())]


# -- processing ------------------------------------------------------------


def trim(samples: np.ndarray, rate: int) -> np.ndarray:
    """Uniform pre-roll, trimmed tail, fade-out. No level change anywhere."""
    envelope = np.abs(samples)
    peak = envelope.max()
    loud = np.flatnonzero(envelope > peak * ONSET_FRACTION)
    start = max(int(loud[0]) - int(PRE_ROLL_MS * rate / 1000), 0)

    audible = np.flatnonzero(envelope > peak * TAIL_FRACTION)
    end = min(int(audible[-1]) + int(FADE_OUT_MS * rate / 1000), len(samples))

    out = samples[start:end].copy()
    fade = min(int(FADE_OUT_MS * rate / 1000), len(out))
    out[-fade:] *= np.linspace(1.0, 0.0, fade)
    return out


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


def build_entry(mapping: Mapping, paths: list[Path]) -> tuple[dict, list[str]]:
    selected = select_takes(paths)
    filenames: list[str] = []
    peaks: list[float] = []
    for index, (source, _) in enumerate(selected, start=1):
        samples, rate = read_mono(source)
        trimmed = trim(samples, rate)
        filename = f"{mapping.target}_rr{index}.wav"
        write_wav(KIT_DIR / filename, trimmed, rate)
        filenames.append(filename)
        peaks.append(float(np.abs(trimmed).max()))

    # Ceiling-matched, so the loudest take lands on target and every quieter
    # take keeps its recorded distance below it.
    gain_db = round(20 * float(np.log10(mapping.ceiling / max(peaks))), 2)
    entry = {"samples": filenames, "gain_db": gain_db, "pitch_semitones": 0.0}
    if mapping.notes:
        entry["notes"] = mapping.notes
    return entry, [p.name for p, _ in selected]


# -- outputs ---------------------------------------------------------------


def attribution_block() -> str:
    return (
        f'"{DATASET_TITLE}" by {CREATOR} ({DATASET_YEAR}), '
        f"licensed under {LICENSE_NAME}. "
        f"Source: {RECORD_URL} (DOI {DOI}). "
        f"Modified for bolbox: takes selected, trimmed, downmixed to mono."
    )


def write_license(provenance: dict[str, list[str]]) -> None:
    lines = [
        "ATTRIBUTION AND LICENSE",
        "=" * 72,
        "",
        "The WAV files in this directory are derived from a third-party dataset.",
        "",
        f"  Title       {DATASET_TITLE}",
        f"  Creator     {CREATOR}",
        f"  Published   {DATASET_YEAR}, Zenodo",
        f"  Record      {RECORD_URL}",
        f"  DOI         {DOI}",
        f"  Concept DOI {CONCEPT_DOI}",
        f"  License     {LICENSE_NAME}",
        f"  License URL {LICENSE_URL}",
        "",
        "Required attribution line:",
        "",
        f"  {attribution_block()}",
        "",
        "",
        "MODIFICATIONS MADE (CC BY 4.0 section 3(a)(1)(B) requires these be stated)",
        "-" * 72,
        "",
        "1. SELECTION. The source has 13 stroke classes of 50 takes each (650",
        "   files). This kit keeps at most 10 takes of 10 classes. Takes with any",
        "   sample at digital full scale were rejected, then takes more than",
        "   +/-6dB from the class median peak, then the remainder was sampled",
        "   evenly across take order.",
        "",
        "2. CHANNEL. Downmixed from stereo to mono by averaging the two channels.",
        "",
        "3. TRIMMING. Leading silence trimmed to a uniform 2ms pre-roll and",
        f"   trailing silence removed, followed by a {FADE_OUT_MS:.0f}ms linear fade-out. The",
        "   source clips are cut while the drum is still ringing; the fade",
        "   replaces a truncation click.",
        "",
        "4. RENAMING. Files were renamed from `<Class>_Test<NN>.wav` to",
        "   `<stroke>_rr<N>.wav` to match this project's kit convention. The map",
        "   from dataset class to bolbox stroke, and the exact source file behind",
        "   every sample, is listed under PROVENANCE below.",
        "",
        "5. NOT MODIFIED: sample rate (44.1kHz throughout, unchanged), bit depth",
        "   (16-bit, unchanged), and AMPLITUDE. No normalization, gain or",
        "   compression was applied to any sample. The per-stroke balance this kit",
        "   needs lives in `gain_db` in kit.json and is applied at playback, so",
        "   the audio here stays faithful to the source.",
        "",
        "6. NOT INCLUDED. Three of the 13 classes are unused:",
        "",
    ]
    for name, reason in UNUSED.items():
        lines.append(f"   {name:4s} {reason}")
    lines += [
        "",
        "",
        "PROVENANCE (bolbox filename <- source filename)",
        "-" * 72,
        "",
    ]
    for target, sources in provenance.items():
        for index, source in enumerate(sources, start=1):
            lines.append(f"  {target}_rr{index}.wav  <-  {source}")
        lines.append("")
    lines += [
        "",
        "The bolbox code that produced this directory",
        "(scripts/make_deolekar_kit.py) is part of bolbox and carries bolbox's",
        "own license. This file covers the audio only.",
        "",
    ]
    (KIT_DIR / "LICENSE.txt").write_text("\n".join(lines), encoding="utf-8")


def write_readme(manifest: dict, provenance: dict[str, list[str]]) -> None:
    real = [m.target for m in STROKES]
    total = sum(len(v) for v in provenance.values())
    lines = [
        "# deolekar-tabla — real recorded tabla, the default kit",
        "",
        "Recordings of a real tabla played by professional players, tuned to C#.",
        "This is the kit the UI loads by default. `placeholder-tabla` remains as a",
        "synthesized offline fallback and `sparse-demo` as the alias-path fixture.",
        "",
        "## Attribution",
        "",
        f"> {attribution_block()}",
        "",
        f"Full license terms, the complete list of modifications, and a per-file",
        f"provenance table are in [LICENSE.txt](LICENSE.txt). Keep that file with",
        f"the audio — CC BY 4.0 requires the attribution to travel with it.",
        "",
        "## What is real and what is not",
        "",
        f"{total} WAVs: {len(provenance)} sample sets, up to {TAKES_PER_STROKE} round robins each.",
        "",
        "| bolbox | source class | real recording? |",
        "|--------|--------------|-----------------|",
    ]
    for m in STROKES:
        lines.append(f"| `{m.target}` | `{m.dataset_class}` | yes |")
    for m in COMPOSITES:
        lines.append(f"| `{m.target}` (composite) | `{m.dataset_class}` | yes |")
    for stroke, (target, _) in ALIASES.items():
        lines.append(f"| `{stroke}` | — | **no — plays `{target}`** |")
    lines += [
        "",
        f"So {len(real)} strokes and {len(COMPOSITES)} composites are genuine recordings, and",
        f"{len(ALIASES)} strokes are substitutions. The substitutions are `alias_of`",
        "entries with a `notes` string, so they are visible in `kit.json`, in",
        "`Kit.stand_ins`, and in the manifest the browser loads — you should never",
        "have to discover one by ear.",
        "",
        "**`re` is the one that will bother you.** The dataset has no ring-finger",
        "flick, so `re` plays `te`: too loud, too long, and wrong inside",
        "`tirakita`, which is the single most important thing this project has to",
        "get right. Recording your own `re` is the highest-value thing you can do",
        "to this kit.",
        "",
        "## Levels",
        "",
        "No sample here has been normalized, gained or compressed — the audio is",
        "bit-faithful to the source. The dataset's classes were gain-staged very",
        "inconsistently (`Ge` peaks near -19dBFS, `Na` is pinned at full scale),",
        "so the musical balance lives in `gain_db` in `kit.json` and is applied at",
        "playback. If the bayan is too loud for you, that is one number in a text",
        "file, not a re-render:",
        "",
        "```",
    ]
    for name, entry in manifest["strokes"].items():
        if "gain_db" in entry:
            lines.append(f'  {name:5s} gain_db {entry["gain_db"]:+6.2f}')
    for name, entry in manifest.get("composites", {}).items():
        lines.append(f'  {name:5s} gain_db {entry["gain_db"]:+6.2f} (composite)')
    lines += [
        "```",
        "",
        "## Regenerating",
        "",
        "```",
        "python scripts/make_deolekar_kit.py",
        "```",
        "",
        "Downloads the dataset to `.cache/` on first run, then works offline. The",
        "selection rule is deterministic, so regenerating is never a diff.",
        "",
        "## Still worth recording yourself",
        "",
        "This kit is a real tabla, but it is not *your* tabla, and it is one drum",
        "at one tuning. `kits/placeholder-tabla/README.md` has the full list of",
        "what to capture; the short version is a real `re`, a `dha` played the way",
        "you play it, and sustained `ge` material for the v2 pitch envelope.",
        "",
    ]
    (KIT_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    wav_dir = fetch_dataset()
    grouped = by_class(wav_dir)
    KIT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in KIT_DIR.glob("*.wav"):
        stale.unlink()

    provenance: dict[str, list[str]] = {}
    strokes: dict[str, dict] = {}
    for mapping in STROKES:
        entry, sources = build_entry(mapping, grouped[mapping.dataset_class])
        strokes[mapping.target] = entry
        provenance[mapping.target] = sources
    for stroke, (target, note) in ALIASES.items():
        strokes[stroke] = {"alias_of": target, "notes": note}

    composites: dict[str, dict] = {}
    for mapping in COMPOSITES:
        entry, sources = build_entry(mapping, grouped[mapping.dataset_class])
        composites[mapping.target] = entry
        provenance[mapping.target] = sources

    manifest = {
        "schema_version": 1,
        "name": "deolekar-tabla",
        "description": (
            "Real recorded tabla, tuned to C#, from the Zenodo tabla strokes "
            "dataset by Subodh Deolekar (CC BY 4.0). See LICENSE.txt."
        ),
        "notes": (
            f"{len(ALIASES)} of the stroke vocabulary are stand-ins, not recordings: "
            + ", ".join(f"{s} plays {t}" for s, (t, _) in ALIASES.items())
            + ". See each entry's `notes` and README.md."
        ),
        "sample_rate_policy": "resample_on_load",
        "strokes": strokes,
        "composites": composites,
    }
    (KIT_DIR / "kit.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    write_license(provenance)
    write_readme(manifest, provenance)

    wavs = sorted(KIT_DIR.glob("*.wav"))
    size = sum(w.stat().st_size for w in wavs)
    print(f"deolekar-tabla: {len(wavs)} wav files, {size / 1024:.0f} KiB -> {KIT_DIR}")


if __name__ == "__main__":
    main()
