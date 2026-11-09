"""Labels -> training targets, coverage, and importing recordings.

A label is the bol text you recited, in composition notation: whitespace
between matras, `|` between vibhags, `-` rests, `!`/`.` accents, `{n, ...}`
groups, `bol@variant`. Unlike a composition file, a label may be a FRAGMENT:
a clip does not have to fill a whole avartan, because you do not always
recite one.

CTC UNITS (see STATUS.md section 5). The output vocabulary is the set of
non-compound bols. A compound is expanded into its component syllables; a
variant is dropped, because the choice of realization is not in the audio;
accents, rests and bar lines are dropped because they are not syllables.

    "dha tirakita dhin@x! | -"  ->  dha te re ki ta dhin

Today compounds are expanded through their STROKES, since the lexicon has no
separate spoken form. For `tirakita` that writes `te re ki ta` although it is
said "ti ra ki ta" -- an open decision recorded in STATUS.md. Change it here,
once, by adding a `spoken:` field to the lexicon and reading it below.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .audio import load_as_wav, read_wav
from .errors import BolboxError, RecordingError, TokenizeError
from .lexicon import Lexicon
from .recordings import RecordingMeta, RecordingStore, sha256

AUDIO_SUFFIXES = {".wav", ".m4a", ".mp3", ".aac", ".flac", ".ogg", ".webm", ".opus", ".aiff", ".aif", ".caf"}

_GROUP_OPEN = re.compile(r"\{\s*\d+\s*,")
_ACCENTS = "!."

# Floors from STATUS.md for a first CTC run. The coverage report measures
# against these so "record more" becomes "record more of THIS".
UNIT_FLOOR = 50
COMPOUND_FLOOR = 60


class LabelError(BolboxError):
    """A label does not tokenize. Carries the offending token and its column."""

    def __init__(self, message: str, token: str, column: int) -> None:
        self.token = token
        self.column = column
        super().__init__(message)


@dataclass(frozen=True)
class ParsedLabel:
    bols: tuple[str, ...]      # canonical bol names, compounds intact
    units: tuple[str, ...]     # CTC target sequence
    slots: int                 # sequential stroke slots (for onset comparison)


def unit_vocabulary(lexicon: Lexicon) -> list[str]:
    """CTC output labels, excluding blank. Stable order: lexicon file order."""
    return [b.name for b in lexicon if not _is_sequence(b)]


def _is_sequence(bol) -> bool:
    return any(len(v.strokes) > 1 and not v.simultaneous for v in bol.variants)


def _units_for(segment, lexicon: Lexicon) -> list[str]:
    variant = segment.variant
    if len(variant.strokes) > 1 and not variant.simultaneous:
        out = []
        for stroke in variant.strokes:
            # The stroke names of every current compound are also bol names.
            # If that ever stops being true, fail rather than invent a unit.
            if stroke not in lexicon:
                raise LabelError(
                    f"compound {segment.bol.name!r} expands to stroke {stroke!r}, "
                    f"which is not a bol, so it has no CTC unit",
                    segment.bol.name, 0,
                )
            out.append(lexicon.resolve(stroke).name)
        return out
    return [segment.bol.name]


def parse_label(text: str, lexicon: Lexicon) -> ParsedLabel:
    bols: list[str] = []
    units: list[str] = []
    slots = 0
    for line in text.splitlines():
        line = line.split("#", 1)[0]
        cleaned = _GROUP_OPEN.sub(lambda m: " " * len(m.group()), line)
        cleaned = cleaned.replace("}", " ").replace("|", " ")
        for match in re.finditer(r"\S+", cleaned):
            raw = match.group()
            word = raw.rstrip(_ACCENTS)
            if word in ("", "-"):
                continue
            try:
                segments = lexicon.tokenize(word)
            except TokenizeError as exc:
                raise LabelError(
                    f"unknown bol in {word!r} at {exc.offending!r} -- add it to "
                    f"data/lexicon.yaml or fix the spelling",
                    word, match.start() + exc.offset,
                ) from exc
            except BolboxError as exc:  # unknown @variant
                raise LabelError(str(exc), word, match.start()) from exc
            for seg in segments:
                bols.append(seg.bol.name)
                seg_units = _units_for(seg, lexicon)
                units.extend(seg_units)
                slots += seg.variant.slot_count
    return ParsedLabel(tuple(bols), tuple(units), slots)


def ctc_targets(text: str, lexicon: Lexicon) -> list[str]:
    return list(parse_label(text, lexicon).units)


# -- coverage -----------------------------------------------------------------


@dataclass
class Coverage:
    takes: int
    labelled: int
    skipped: int
    invalid: int
    minutes: float
    labelled_minutes: float
    units: Counter
    compounds: Counter

    def to_dict(self, lexicon: Lexicon) -> dict:
        compound_names = [b.name for b in lexicon if _is_sequence(b)]
        return {
            "takes": self.takes,
            "labelled": self.labelled,
            "unlabelled": self.takes - self.labelled - self.skipped,
            "skipped": self.skipped,
            "invalid": self.invalid,
            "minutes": round(self.minutes, 2),
            "labelled_minutes": round(self.labelled_minutes, 2),
            "unit_floor": UNIT_FLOOR,
            "compound_floor": COMPOUND_FLOOR,
            "units": {u: self.units.get(u, 0) for u in unit_vocabulary(lexicon)},
            "compounds": {c: self.compounds.get(c, 0) for c in compound_names},
        }


def coverage(store: RecordingStore, lexicon: Lexicon) -> Coverage:
    cov = Coverage(0, 0, 0, 0, 0.0, 0.0, Counter(), Counter())
    compound_names = {b.name for b in lexicon if _is_sequence(b)}
    for meta in store.list():
        cov.takes += 1
        cov.minutes += meta.duration_sec / 60
        if meta.skipped:
            cov.skipped += 1
            continue
        if not meta.labelled:
            continue
        try:
            parsed = parse_label(meta.bols, lexicon)
        except LabelError:
            cov.invalid += 1
            continue
        cov.labelled += 1
        cov.labelled_minutes += meta.duration_sec / 60
        cov.units.update(parsed.units)
        cov.compounds.update(b for b in parsed.bols if b in compound_names)
    return cov


def format_coverage(cov: Coverage, lexicon: Lexicon) -> str:
    d = cov.to_dict(lexicon)
    lines = [
        f"{d['minutes']:.1f} min across {d['takes']} takes "
        f"({d['labelled']} labelled = {d['labelled_minutes']:.1f} min, "
        f"{d['unlabelled']} unlabelled, {d['skipped']} skipped"
        + (f", {d['invalid']} with labels that no longer tokenize" if d["invalid"] else "")
        + ")",
        "",
        f"CTC units (floor {UNIT_FLOOR} for a first run):",
    ]
    for name, n in d["units"].items():
        lines.append(f"  {name:<9}{n:>6}{'' if n >= UNIT_FLOOR else '   << thin'}")
    lines += ["", f"compounds (floor {COMPOUND_FLOOR}):"]
    for name, n in d["compounds"].items():
        lines.append(f"  {name:<9}{n:>6}{'' if n >= COMPOUND_FLOOR else '   << thin'}")
    return "\n".join(lines)


def manifest_rows(store: RecordingStore, lexicon: Lexicon) -> list[dict]:
    """One row per trainable take: the shape the 1c training code will read."""
    rows = []
    for meta in sorted(store.list(), key=lambda m: m.id):
        if meta.skipped or not meta.labelled:
            continue
        try:
            parsed = parse_label(meta.bols, lexicon)
        except LabelError:
            continue
        rows.append({
            "id": meta.id,
            "wav": str(store.wav_path(meta.id)),
            "duration_sec": meta.duration_sec,
            "sample_rate": meta.sample_rate,
            "speaker": meta.speaker,
            "lay": meta.lay,
            "bols": meta.bols,
            "units": list(parsed.units),
        })
    return rows


# -- import -------------------------------------------------------------------


@dataclass
class ImportResult:
    imported: list[RecordingMeta]
    duplicates: list[str]
    failed: list[tuple[str, str]]


def import_directory(
    directory: Path, store: RecordingStore, lexicon: Lexicon, *, speaker: str = "self"
) -> ImportResult:
    """Copy every audio file under `directory` into the store, unlabelled.

    Idempotent: a file whose bytes were imported before is skipped by hash.
    If `name.txt` sits next to `name.wav`, its text becomes the label -- the
    "free labels" case from bolbox.md, where you recited from written notation
    and already have the notation. A .txt that does not tokenize is kept in
    `notes` instead, so nothing is lost and nothing wrong reaches training.
    Never guesses a label from a filename.
    """
    result = ImportResult([], [], [])
    known = store.known_hashes()
    files = sorted(
        p for p in Path(directory).rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES
    )
    for path in files:
        rel = str(path.relative_to(directory))
        try:
            original = path.read_bytes()
            digest = sha256(original)
            if digest in known:
                result.duplicates.append(rel)
                continue
            wav = load_as_wav(path)
            samples, rate = read_wav(wav)
        except (RecordingError, OSError) as exc:
            result.failed.append((rel, str(exc)))
            continue

        bols, notes = "", ""
        sidecar_txt = path.with_suffix(".txt")
        if sidecar_txt.is_file():
            text = sidecar_txt.read_text(encoding="utf-8").strip()
            try:
                parse_label(text, lexicon)
                bols = text
            except LabelError as exc:
                notes = f"imported label did not tokenize ({exc}): {text}"

        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        meta = store.save(
            wav,
            {
                "duration_sec": round(len(samples) / rate, 3),
                "sample_rate": rate,
                "bols": bols,
                "notes": notes,
                "speaker": speaker,
            },
            source={"name": rel, "sha256": digest},
            recorded_at=mtime,
        )
        known.add(digest)
        result.imported.append(meta)
    return result


def write_manifest(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
