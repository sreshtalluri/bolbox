"""The canonical stroke vocabulary.

Loads data/strokes.yaml and validates every other surface that names a stroke
against it. The point is that the stroke list exists exactly once:

    data/strokes.yaml  (source of truth)
        |
        +--> lexicon.yaml   targets validated by Lexicon.load
        +--> midi.py        note map keys validated at import
        +--> kit.json       sample keys validated at kit load
        +--> vocab.json     CTC vocabulary generated, never hand-written

Before this file existed the list was maintained in four places, and the way it
failed was silent: a kit missing a stroke played nothing, which reads as a
sequencing bug rather than a missing WAV. `require()` turns that into an error
that names the stroke and the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import yaml

from .errors import UnknownStrokeError, VocabError

DEFAULT_STROKES_PATH = Path(__file__).resolve().parent.parent / "data" / "strokes.yaml"

_VALID_DRUMS = frozenset({"dayan", "bayan"})


@dataclass(frozen=True)
class Stroke:
    """One physical stroke on one of the two drums."""

    name: str
    drum: str
    damped: bool
    description: str = ""
    verify: bool = False

    @property
    def resonant(self) -> bool:
        return not self.damped


class Vocabulary:
    """An immutable, ordered set of the strokes bolbox knows about.

    Ordering is file order, which matters for the generated CTC vocabulary:
    reordering strokes.yaml would silently invalidate trained weights, so the
    order is treated as part of the contract.
    """

    def __init__(self, strokes: dict[str, Stroke], *, version: int = 1) -> None:
        self._strokes = dict(strokes)
        self.version = version

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Vocabulary":
        path = Path(path) if path is not None else DEFAULT_STROKES_PATH
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise VocabError(f"stroke vocabulary not found at {path}") from exc
        except yaml.YAMLError as exc:
            raise VocabError(f"{path}: invalid YAML: {exc}") from exc
        return cls.from_dict(raw, source=str(path))

    @classmethod
    def from_dict(cls, raw: object, *, source: str = "<dict>") -> "Vocabulary":
        if not isinstance(raw, dict):
            raise VocabError(f"{source}: expected a mapping at the top level")

        version = raw.get("version", 1)
        if not isinstance(version, int):
            raise VocabError(f"{source}: `version` must be an integer")

        entries = raw.get("strokes")
        if not isinstance(entries, dict) or not entries:
            raise VocabError(f"{source}: `strokes` must be a non-empty mapping")

        strokes: dict[str, Stroke] = {}
        for name, body in entries.items():
            if not isinstance(name, str) or not name:
                raise VocabError(f"{source}: stroke names must be non-empty strings")
            if name != name.lower():
                # Tokenization is case-insensitive; storing a capitalised key
                # would make `require()` reject a name the tokenizer accepts.
                raise VocabError(f"{source}: stroke {name!r} must be lowercase")
            if not isinstance(body, dict):
                raise VocabError(f"{source}: stroke {name!r} must map to a mapping")

            drum = body.get("drum")
            if drum not in _VALID_DRUMS:
                raise VocabError(
                    f"{source}: stroke {name!r} has drum {drum!r}; "
                    f"expected one of {sorted(_VALID_DRUMS)}"
                )
            damped = body.get("damped")
            if not isinstance(damped, bool):
                raise VocabError(f"{source}: stroke {name!r} needs a boolean `damped`")

            strokes[name] = Stroke(
                name=name,
                drum=drum,
                damped=damped,
                description=str(body.get("description", "")).strip(),
                verify=bool(body.get("verify", False)),
            )

        return cls(strokes, version=version)

    # -- read ---------------------------------------------------------------

    @property
    def names(self) -> list[str]:
        """Stroke names in file order. Order is part of the contract."""
        return list(self._strokes)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.lower() in self._strokes

    def __iter__(self) -> Iterator[Stroke]:
        return iter(self._strokes.values())

    def __len__(self) -> int:
        return len(self._strokes)

    def __getitem__(self, name: str) -> Stroke:
        try:
            return self._strokes[name.lower()]
        except KeyError:
            raise UnknownStrokeError([name], "vocabulary lookup", self.names) from None

    def on_drum(self, drum: str) -> list[Stroke]:
        return [s for s in self._strokes.values() if s.drum == drum]

    @property
    def needs_verification(self) -> list[Stroke]:
        """Strokes flagged `verify: true` -- mappings that need a player's ear."""
        return [s for s in self._strokes.values() if s.verify]

    # -- validate -----------------------------------------------------------

    def require(self, names: Iterable[str], *, source: str) -> None:
        """Assert every name is a known stroke, or raise naming all that are not.

        Reports every unknown name at once. Fixing them one error per run is the
        kind of small friction that makes people stop running the validator.
        """
        unknown = [n for n in dict.fromkeys(names) if n.lower() not in self._strokes]
        if unknown:
            raise UnknownStrokeError(unknown, source, self.names)

    def missing_from(self, names: Iterable[str]) -> list[str]:
        """Strokes in the vocabulary that `names` does not cover.

        The coverage direction `require()` does not check. A kit that supplies
        every stroke it mentions can still be missing strokes entirely, and that
        is the case that plays silence. Used by the kit validator (T7).
        """
        supplied = {n.lower() for n in names}
        return [n for n in self._strokes if n not in supplied]
