"""Kit manifests -- which sample plays for which stroke.

A kit is a directory with a `kit.json` and some WAVs. The manifest is versioned
because it is the one file in this project that outlives the code: kits get
recorded once, shared, and loaded by whatever bolbox looks like in a year.

THE RULE THIS FILE EXISTS TO ENFORCE

Every stroke in data/strokes.yaml must resolve to a sample set, or loading
fails. Not a warning, not a fallback to silence -- a load error that names the
strokes you left out.

The failure mode this prevents is the expensive one. A kit missing `re` plays
nothing where `re` should be. Nothing is not an error message; it reads as a
sequencing bug, or a velocity bug, or a scheduler bug, and you can lose an
evening to it before you think to check the kit. Making the check total means
that if a kit loads, the sampler is audible for every stroke the notation can
produce. There is no third state.

WHY `alias_of` IS MANY-TO-ONE

    ki: { alias_of: ka }

Several strokes may resolve to one sample set, and this single mechanism covers
three quite different situations:

  - You have not recorded `ti` separately yet, and for you it is `te` anyway.
  - You bought a Splice pack with six usable tabla sounds and want to play
    fourteen strokes with it.
  - You want the notation to drive a 909, where `ge` is a kick and everything
    damped is a closed hat.

Without aliasing, each of those needs either its own duplicated WAVs or its own
special case in the loader. With it, a sparse kit is a complete kit that says so
out loud. Chains resolve (a -> b -> c); cycles raise, because a cycle means the
manifest asserts a sound exists without ever supplying it.

WHY COMPOSITES ARE KEYED BY BOL, NOT BY STROKE

`dha` is two simultaneous strokes, so by the time a Pattern reaches the sampler
it is a `ge` event and a `na` event. Two one-shots fired together do not sound
like a `dha` -- the bayan and dayan couple, and every tabla library worth using
records the combination. `Event.source_bol` survives that decomposition
precisely so this file can be asked "do you have a real `dha`?" and answer yes.
MIDI export is unaffected and still emits two notes.

WHY `midi_map` IS AN OVERRIDE AND NOT A MAP

The canonical stroke -> note map lives in midi.py. A kit that targets a specific
drum machine needs to move some notes, but it should not have to restate the
whole map to move one -- a partial map that looks total is how notes go missing.
So a kit supplies overrides only, `midi_override()` returns None for the rest,
and midi.py does the merging in one place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import BolboxError
from .lexicon import Lexicon
from .vocab import Vocabulary

SCHEMA_VERSION = 1

MANIFEST_FILENAME = "kit.json"

# Declared rather than inferred: the browser decodes into an AudioContext with a
# fixed sample rate, so a 44.1k pack loaded into a 48k context has to resample.
# The kit says which it wants instead of the loader guessing per file.
_SAMPLE_RATE_POLICIES = frozenset({"resample_on_load", "reject_on_mismatch"})

_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "name",
        "description",
        "sample_rate_policy",
        "strokes",
        "composites",
        "midi_map",
        "notes",
    }
)
_ENTRY_KEYS = frozenset({"samples", "gain_db", "pitch_semitones", "alias_of", "notes"})

_MIN_MIDI_NOTE = 0
_MAX_MIDI_NOTE = 127


class KitError(BolboxError):
    """A kit manifest is malformed, incomplete, or points at files that are not there."""


@dataclass(frozen=True)
class SampleSet:
    """The recordings one stroke (or one composite bol) plays, plus its trim.

    ``owner`` is the manifest key that actually declared the samples. Aliased
    strokes share a single SampleSet, and ``owner`` is how you tell that `ki` is
    playing `ka`'s recordings rather than its own -- which is the difference
    between a kit that is deliberately sparse and one that is accidentally so.
    """

    owner: str
    samples: tuple[str, ...]
    gain_db: float = 0.0
    pitch_semitones: float = 0.0
    notes: str = ""

    def round_robin(self, index: int) -> str:
        """The sample for the ``index``-th hit. Cycles; never raises.

        Deterministic on purpose. The browser owns the counter -- it is the only
        thing that knows how many times a stroke has fired this session -- but
        the selection itself has to be a pure function of that counter or it
        cannot be tested at all.
        """
        return self.samples[index % len(self.samples)]


class Kit:
    """A validated kit: every stroke in the vocabulary resolves to a SampleSet.

    Construct through :meth:`load` or :meth:`from_dict`. Both validate, and a Kit
    that exists has already been proven total against the stroke vocabulary --
    so nothing downstream needs a "what if the sample is missing" branch.
    """

    def __init__(
        self,
        *,
        name: str,
        root: Path,
        strokes: dict[str, SampleSet],
        composites: dict[str, SampleSet],
        composite_surfaces: dict[str, str],
        midi_map: dict[str, int],
        alias_targets: dict[str, str],
        alias_notes: dict[str, str] | None = None,
        notes: str = "",
        description: str = "",
        sample_rate_policy: str = "resample_on_load",
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        self.name = name
        self.root = root
        self.description = description
        self.sample_rate_policy = sample_rate_policy
        self.schema_version = schema_version
        self._strokes = dict(strokes)
        self._composites = dict(composites)
        self._composite_surfaces = dict(composite_surfaces)
        self._midi_map = dict(midi_map)
        self._alias_targets = dict(alias_targets)
        self._alias_notes = dict(alias_notes or {})
        self.notes = notes

    # -- construction ------------------------------------------------------

    @classmethod
    def load(
        cls,
        path: Path | str,
        vocab: Vocabulary | None = None,
        lexicon: Lexicon | None = None,
    ) -> "Kit":
        """Load a kit from its directory, or from the kit.json inside it."""
        path = Path(path)
        manifest = path / MANIFEST_FILENAME if path.is_dir() else path
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KitError(f"kit manifest not found at {manifest}") from exc
        except json.JSONDecodeError as exc:
            raise KitError(f"{manifest}: invalid JSON: {exc}") from exc

        vocab = vocab or Vocabulary.load()
        return cls.from_dict(
            raw,
            vocab,
            lexicon=lexicon or Lexicon.load(vocab=vocab),
            root=manifest.parent,
            source=str(manifest),
        )

    @classmethod
    def from_dict(
        cls,
        raw: object,
        vocab: Vocabulary,
        *,
        lexicon: Lexicon | None = None,
        root: Path | str = ".",
        source: str = "<dict>",
    ) -> "Kit":
        root = Path(root)
        if not isinstance(raw, dict):
            raise KitError(f"{source}: expected a mapping at the top level")

        _reject_unknown_keys(raw, _MANIFEST_KEYS, source=source, what="manifest key")
        _check_schema_version(raw, source=source)

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise KitError(f"{source}: `name` must be a non-empty string")

        policy = raw.get("sample_rate_policy", "resample_on_load")
        if policy not in _SAMPLE_RATE_POLICIES:
            raise KitError(
                f"{source}: sample_rate_policy {policy!r} is not one of "
                f"{sorted(_SAMPLE_RATE_POLICIES)}"
            )

        entries = raw.get("strokes")
        if not isinstance(entries, dict) or not entries:
            raise KitError(f"{source}: `strokes` must be a non-empty mapping")

        # Every key must name a real stroke before anything else is checked --
        # a typo here would otherwise surface as a missing-coverage error about
        # the stroke it was meant to be, which points at the wrong line.
        vocab.require(entries, source=f"{source}: kit {name!r} strokes")

        declared: dict[str, SampleSet] = {}
        aliases: dict[str, str] = {}
        alias_notes: dict[str, str] = {}
        for key, body in entries.items():
            key = key.lower()
            if not isinstance(body, dict):
                raise KitError(f"{source}: stroke {key!r} must map to a mapping")
            _reject_unknown_keys(
                body, _ENTRY_KEYS, source=source, what=f"key in stroke {key!r}"
            )
            if "alias_of" in body:
                # `notes` is allowed here and nowhere else in an alias entry:
                # a substitution that is a compromise has to be able to say so.
                extra = sorted(set(body) - {"alias_of", "notes"})
                if extra:
                    raise KitError(
                        f"{source}: stroke {key!r} has `alias_of` alongside "
                        f"{extra} -- an alias plays the target's samples and "
                        f"cannot carry its own"
                    )
                target = body["alias_of"]
                if not isinstance(target, str) or not target:
                    raise KitError(
                        f"{source}: stroke {key!r}: `alias_of` must be a stroke name"
                    )
                aliases[key] = target.lower()
                alias_notes[key] = _text(
                    body.get("notes", ""), owner=key, field="notes", source=source
                )
            else:
                declared[key] = _sample_set(body, owner=key, source=source)

        resolved = _resolve_aliases(declared, aliases, source=source, kit_name=name)

        # The whole point of the file. Checked after alias resolution so a kit
        # that covers a stroke indirectly counts as covering it.
        missing = vocab.missing_from(resolved)
        if missing:
            raise KitError(
                f"{source}: kit {name!r} does not supply "
                f"{', '.join(repr(m) for m in missing)}. "
                f"Every stroke in data/strokes.yaml must resolve to a sample set; "
                f"add samples or an `alias_of` for each. A kit that loads is a "
                f"kit that makes a sound for every stroke."
            )

        composites, composite_surfaces = _parse_composites(
            raw.get("composites"), vocab, lexicon, source=source
        )
        midi_map = _parse_midi_map(raw.get("midi_map"), vocab, source=source)

        _check_files_exist(root, [*resolved.values(), *composites.values()], source=source)

        return cls(
            name=name,
            root=root,
            strokes=resolved,
            composites=composites,
            composite_surfaces=composite_surfaces,
            midi_map=midi_map,
            alias_targets=aliases,
            alias_notes=alias_notes,
            notes=_text(raw.get("notes", ""), owner=name, field="notes", source=source),
            description=str(raw.get("description", "")).strip(),
            sample_rate_policy=policy,
            schema_version=int(raw["schema_version"]),
        )

    # -- read ---------------------------------------------------------------

    @property
    def stroke_names(self) -> list[str]:
        return list(self._strokes)

    @property
    def composite_names(self) -> list[str]:
        """Bols this kit has a dedicated one-shot for. Usually `dha`, `dhin`."""
        return list(self._composites)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        key = name.lower()
        return key in self._strokes or key in self._composites

    def __iter__(self) -> Iterator[SampleSet]:
        return iter(self._strokes.values())

    def __len__(self) -> int:
        return len(self._strokes)

    def resolve_stroke(self, stroke: str) -> SampleSet:
        """The sample set for a stroke. Total -- never returns None."""
        try:
            return self._strokes[stroke.lower()]
        except KeyError:
            raise KitError(
                f"kit {self.name!r} has no stroke {stroke!r}. "
                f"Known strokes: {', '.join(self.stroke_names)}"
            ) from None

    def resolve_composite(self, source_bol: str) -> SampleSet | None:
        """The one-shot for a composite bol, or None to play its strokes separately.

        None is a legitimate answer here, unlike for strokes: a kit without a
        recorded `dha` still sounds, it just sounds like `ge` and `na` at once.
        The caller reads ``Event.source_bol`` and asks this once per group.

        Alternate spellings resolve. `grid.py` canonicalizes ``source_bol``
        today, so this is defence in depth rather than a live requirement -- but
        a lookup that missed on `dhaa` would quietly drop back to two voices,
        and a silent downgrade is the exact failure this module exists to stop.
        It costs one dict lookup to not depend on a guarantee made elsewhere.
        """
        if not source_bol:
            return None
        key = source_bol.lower()
        key = self._composite_surfaces.get(key, key)
        return self._composites.get(key)

    def alias_target(self, stroke: str) -> str | None:
        """What ``stroke`` borrows its samples from, or None if it has its own."""
        owner = self.resolve_stroke(stroke).owner
        return None if owner == stroke.lower() else owner

    def note_for(self, name: str) -> str:
        """Whatever this kit says about a stroke or composite, or "".

        This is where a substitution admits to being one. `re: {alias_of: te}`
        is a kit saying "I have no `re`" -- structurally visible, but only if
        something surfaces it, so the note rides along to the browser too.
        """
        key = name.lower()
        if key in self._alias_notes:
            return self._alias_notes[key]
        key = self._composite_surfaces.get(key, key)
        entry = self._strokes.get(key) or self._composites.get(key)
        return entry.notes if entry is not None else ""

    @property
    def stand_ins(self) -> dict[str, str]:
        """Strokes this kit does not really have, mapped to what plays instead.

        An empty dict means every stroke is its own recording. Anything in here
        is a compromise the player should be told about rather than discover.
        """
        return {
            stroke: self.resolve_stroke(stroke).owner
            for stroke in self._alias_targets
        }

    def round_robin(self, name: str, index: int) -> str:
        """Filename for the ``index``-th hit of a stroke or composite bol.

        Composite keys are validated never to collide with stroke names, so one
        lookup covers both and the caller does not have to know which it holds.
        """
        key = name.lower()
        sample_set = self._strokes.get(key) or self._composites.get(key)
        if sample_set is None:
            raise KitError(
                f"kit {self.name!r} has no stroke or composite {name!r}. "
                f"Strokes: {', '.join(self.stroke_names)}. "
                f"Composites: {', '.join(self.composite_names) or '(none)'}"
            )
        return sample_set.round_robin(index)

    def sample_path(self, name: str, index: int) -> Path:
        """Absolute path to the file :meth:`round_robin` picked."""
        return self.root / self.round_robin(name, index)

    def midi_override(self, stroke: str) -> int | None:
        """This kit's note for ``stroke``, or None to use the canonical map.

        midi.py owns the merge. Returning None rather than a default keeps the
        fallback in exactly one place.
        """
        return self._midi_map.get(stroke.lower())

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        """Fully resolved, JSON-safe form for the browser.

        Aliases are already followed and coverage is already proven, so the
        client loads a flat stroke -> samples table and never re-implements any
        of the resolution rules above.
        """
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "description": self.description,
            "sample_rate_policy": self.sample_rate_policy,
            "notes": self.notes,
            "strokes": {
                k: {**_sample_set_dict(v), "notes": self.note_for(k)}
                for k, v in self._strokes.items()
            },
            "composites": {k: _sample_set_dict(v) for k, v in self._composites.items()},
            "midi_map": dict(self._midi_map),
        }


# -- validation helpers ----------------------------------------------------


def _reject_unknown_keys(
    body: dict, allowed: frozenset[str], *, source: str, what: str
) -> None:
    """Unknown keys are errors, not noise.

    kit.json is hand-authored. A misspelled `pitch_semitone` that is silently
    ignored is a tuning setting that mysteriously does nothing.
    """
    unknown = [k for k in body if k not in allowed]
    if unknown:
        raise KitError(
            f"{source}: unknown {what}(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )


def _check_schema_version(raw: dict, *, source: str) -> None:
    version = raw.get("schema_version")
    if version is None:
        raise KitError(
            f"{source}: no `schema_version`. Kits outlive the code that reads "
            f"them; an unversioned manifest cannot be migrated. Add "
            f"\"schema_version\": {SCHEMA_VERSION}."
        )
    if not isinstance(version, int) or isinstance(version, bool):
        raise KitError(f"{source}: `schema_version` must be an integer, got {version!r}")
    if version != SCHEMA_VERSION:
        raise KitError(
            f"{source}: kit schema_version {version}, but this build of bolbox "
            f"reads version {SCHEMA_VERSION}."
        )


def _sample_set(body: dict, *, owner: str, source: str) -> SampleSet:
    samples = body.get("samples")
    if not isinstance(samples, list) or not samples:
        raise KitError(
            f"{source}: {owner!r} needs a non-empty `samples` list "
            f"(or an `alias_of` pointing at something that has one)"
        )
    for entry in samples:
        if not isinstance(entry, str) or not entry.strip():
            raise KitError(f"{source}: {owner!r}: sample filenames must be strings")
        _check_contained(entry, owner=owner, source=source)
    return SampleSet(
        owner=owner,
        samples=tuple(samples),
        gain_db=_number(body.get("gain_db", 0.0), owner=owner, field="gain_db", source=source),
        pitch_semitones=_number(
            body.get("pitch_semitones", 0.0),
            owner=owner,
            field="pitch_semitones",
            source=source,
        ),
        notes=_text(body.get("notes", ""), owner=owner, field="notes", source=source),
    )


def _text(value: object, *, owner: str, field: str, source: str) -> str:
    if not isinstance(value, str):
        raise KitError(f"{source}: {owner!r}: `{field}` must be a string, got {value!r}")
    return value.strip()


def _number(value: object, *, owner: str, field: str, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KitError(f"{source}: {owner!r}: `{field}` must be a number, got {value!r}")
    return float(value)


def _check_contained(filename: str, *, owner: str, source: str) -> None:
    """Sample paths stay inside the kit directory.

    Kits are shared files. One that reaches out of its own folder is either a
    mistake or something worse, and either way it will not survive being copied.
    """
    candidate = Path(filename)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise KitError(
            f"{source}: {owner!r}: sample {filename!r} must be a relative path "
            f"inside the kit directory"
        )


def _resolve_aliases(
    declared: dict[str, SampleSet],
    aliases: dict[str, str],
    *,
    source: str,
    kit_name: str,
) -> dict[str, SampleSet]:
    """Follow each alias to a declared sample set. Chains resolve, cycles raise."""
    resolved = dict(declared)
    for start in aliases:
        seen = [start]
        current = start
        while current in aliases:
            current = aliases[current]
            if current in seen:
                cycle = " -> ".join([*seen[seen.index(current) :], current])
                raise KitError(
                    f"{source}: kit {kit_name!r} has an alias cycle: {cycle}. "
                    f"A cycle claims a sound exists without ever supplying it."
                )
            seen.append(current)
        if current not in declared:
            raise KitError(
                f"{source}: kit {kit_name!r}: stroke {start!r} aliases {current!r}, "
                f"which declares no samples. Declared: "
                f"{', '.join(sorted(declared)) or '(none)'}"
            )
        resolved[start] = declared[current]
    return resolved


def _parse_composites(
    raw: object, vocab: Vocabulary, lexicon: Lexicon | None, *, source: str
) -> tuple[dict[str, SampleSet], dict[str, str]]:
    """Returns the composites, plus every spelling that reaches one of them."""
    if raw is None:
        return {}, {}
    if not isinstance(raw, dict):
        raise KitError(f"{source}: `composites` must be a mapping of bol -> samples")

    out: dict[str, SampleSet] = {}
    for key, body in raw.items():
        if not isinstance(key, str) or not key:
            raise KitError(f"{source}: composite names must be non-empty strings")
        key = key.lower()
        if key in vocab:
            raise KitError(
                f"{source}: composite {key!r} is a stroke, not a composite bol. "
                f"Single strokes belong under `strokes`."
            )
        if lexicon is not None:
            if key not in lexicon:
                raise KitError(
                    f"{source}: composite {key!r} is not a bol in data/lexicon.yaml"
                )
            bol = lexicon.resolve(key)
            if not bol.is_composite:
                raise KitError(
                    f"{source}: composite {key!r} resolves to bol {bol.name!r}, "
                    f"which is not simultaneous. Only bols whose strokes sound at "
                    f"one instant can be replaced by a single recording."
                )
            # Store canonically so `dhaa` and `dha` are one entry, matching what
            # Event.source_bol carries.
            key = bol.name
        if not isinstance(body, dict):
            raise KitError(f"{source}: composite {key!r} must map to a mapping")
        _reject_unknown_keys(
            body, _ENTRY_KEYS - {"alias_of"}, source=source, what=f"key in composite {key!r}"
        )
        out[key] = _sample_set(body, owner=key, source=source)

    surfaces: dict[str, str] = {}
    if lexicon is not None:
        for surface in lexicon.surface_forms:
            canonical = lexicon.resolve(surface).name
            if canonical in out:
                surfaces[surface] = canonical
    return out, surfaces


def _parse_midi_map(raw: object, vocab: Vocabulary, *, source: str) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise KitError(f"{source}: `midi_map` must be a mapping of stroke -> note")

    vocab.require(raw, source=f"{source}: midi_map")
    out: dict[str, int] = {}
    for stroke, note in raw.items():
        if isinstance(note, bool) or not isinstance(note, int):
            raise KitError(
                f"{source}: midi_map[{stroke!r}] must be an integer note, got {note!r}"
            )
        if not _MIN_MIDI_NOTE <= note <= _MAX_MIDI_NOTE:
            raise KitError(
                f"{source}: midi_map[{stroke!r}] = {note} is outside "
                f"{_MIN_MIDI_NOTE}..{_MAX_MIDI_NOTE}"
            )
        out[stroke.lower()] = note
    return out


def _check_files_exist(root: Path, sets: list[SampleSet], *, source: str) -> None:
    """Every referenced WAV is on disk, and all the missing ones are named at once."""
    missing: list[str] = []
    for sample_set in sets:
        for filename in sample_set.samples:
            if not (root / filename).is_file():
                missing.append(f"{filename} (for {sample_set.owner!r})")
    if missing:
        raise KitError(
            f"{source}: missing sample file(s) under {root}: {'; '.join(missing)}"
        )


def _sample_set_dict(sample_set: SampleSet) -> dict:
    return {
        "owner": sample_set.owner,
        "samples": list(sample_set.samples),
        "gain_db": sample_set.gain_db,
        "pitch_semitones": sample_set.pitch_semitones,
        "notes": sample_set.notes,
    }
