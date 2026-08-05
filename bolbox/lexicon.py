"""Spoken bols -> physical strokes, and the tokenizer that segments them.

THE TOKENIZATION RULE (the one that closes the critical gap)

Whitespace in a composition separates matra slots. It does NOT separate bols.
Inside a single whitespace-delimited token, bols are found by LONGEST MATCH,
scanning left to right, case-insensitively, over every surface form in the
lexicon including aliases.

    "tirakita"  -> [tirakita]        one compound bol, four strokes, one matra
    "dhage"     -> [dha, ge]         two bols sharing one matra
    "tete"      -> [te, te]          two bols sharing one matra
    "dha ge"    -> two separate matras (the space did that, not this function)

Longest match is what makes `tirakita` resolve as one word rather than as
[ti, ra, ki, ta]. It also means an incomplete alias table silently changes
meaning rather than erroring -- if `tirakita` were missing from the lexicon,
"tirakita" would still segment, just into four one-stroke bols. That is why
every contraction you use in practice belongs in data/lexicon.yaml.

If no known bol starts at some position, tokenization fails loudly with the
offset and the offending substring. It never drops characters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml

from .errors import LexiconError, TokenizeError
from .vocab import Vocabulary

DEFAULT_LEXICON_PATH = Path(__file__).resolve().parent.parent / "data" / "lexicon.yaml"


@dataclass(frozen=True)
class Bol:
    """One spoken syllable or word, and the strokes it produces.

    ``simultaneous`` is the load-bearing flag. When true the strokes sound on the
    same instant (``dha`` = ``ge`` + ``na``) and MIDI emits them on one tick.
    When false they are sequential and divide the bol's share of the matra.
    """

    name: str
    strokes: tuple[str, ...]
    simultaneous: bool = False
    description: str = ""
    verify: bool = False

    @property
    def is_composite(self) -> bool:
        return self.simultaneous and len(self.strokes) > 1

    @property
    def slot_count(self) -> int:
        """How many sequential sub-slots this bol occupies within its share.

        A composite is one slot no matter how many strokes it stacks; a compound
        is one slot per stroke.
        """
        return 1 if self.simultaneous else len(self.strokes)


class Lexicon:
    def __init__(
        self,
        bols: dict[str, Bol],
        aliases: dict[str, str],
        *,
        version: int = 1,
    ) -> None:
        self._bols = dict(bols)
        self._aliases = dict(aliases)
        # Longest first so a plain left-to-right scan is a longest match.
        self._surfaces = sorted(
            [*self._bols, *self._aliases], key=len, reverse=True
        )
        self._max_surface = len(self._surfaces[0]) if self._surfaces else 0

    # -- construction ------------------------------------------------------

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        vocab: Vocabulary | None = None,
    ) -> "Lexicon":
        path = Path(path) if path is not None else DEFAULT_LEXICON_PATH
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise LexiconError(f"lexicon not found at {path}") from exc
        except yaml.YAMLError as exc:
            raise LexiconError(f"{path}: invalid YAML: {exc}") from exc
        return cls.from_dict(raw, vocab or Vocabulary.load(), source=str(path))

    @classmethod
    def from_dict(
        cls, raw: object, vocab: Vocabulary, *, source: str = "<dict>"
    ) -> "Lexicon":
        if not isinstance(raw, dict):
            raise LexiconError(f"{source}: expected a mapping at the top level")

        version = raw.get("version", 1)
        entries = raw.get("bols")
        if not isinstance(entries, dict) or not entries:
            raise LexiconError(f"{source}: `bols` must be a non-empty mapping")

        bols: dict[str, Bol] = {}
        for name, body in entries.items():
            if not isinstance(name, str) or not name.islower():
                raise LexiconError(f"{source}: bol names must be lowercase strings")
            if not isinstance(body, dict):
                raise LexiconError(f"{source}: bol {name!r} must map to a mapping")

            strokes = body.get("strokes")
            if not isinstance(strokes, list) or not strokes:
                raise LexiconError(f"{source}: bol {name!r} needs a non-empty `strokes`")
            if not all(isinstance(s, str) for s in strokes):
                raise LexiconError(f"{source}: bol {name!r} strokes must be strings")

            # The single-source-of-truth check: every target must be a real stroke.
            vocab.require(strokes, source=f"{source}: bol {name!r}")

            simultaneous = bool(body.get("simultaneous", False))
            if simultaneous and len(strokes) < 2:
                raise LexiconError(
                    f"{source}: bol {name!r} is marked simultaneous but has one stroke"
                )

            bols[name] = Bol(
                name=name,
                strokes=tuple(s.lower() for s in strokes),
                simultaneous=simultaneous,
                description=str(body.get("description", "")).strip(),
                verify=bool(body.get("verify", False)),
            )

        raw_aliases = raw.get("aliases") or {}
        if not isinstance(raw_aliases, dict):
            raise LexiconError(f"{source}: `aliases` must be a mapping")

        aliases: dict[str, str] = {}
        for alias, target in raw_aliases.items():
            if not isinstance(alias, str) or not isinstance(target, str):
                raise LexiconError(f"{source}: aliases must be string -> string")
            alias, target = alias.lower(), target.lower()
            if alias in bols:
                raise LexiconError(
                    f"{source}: alias {alias!r} shadows a real bol of the same name"
                )
            if target not in bols:
                raise LexiconError(
                    f"{source}: alias {alias!r} points at {target!r}, which is not a bol"
                )
            aliases[alias] = target

        return cls(bols, aliases, version=version)

    # -- read ---------------------------------------------------------------

    @property
    def surface_forms(self) -> list[str]:
        """Every spelling the tokenizer accepts, longest first."""
        return list(self._surfaces)

    @property
    def canonical_names(self) -> list[str]:
        return list(self._bols)

    def __len__(self) -> int:
        return len(self._bols)

    def __iter__(self) -> Iterator[Bol]:
        return iter(self._bols.values())

    def __contains__(self, surface: object) -> bool:
        if not isinstance(surface, str):
            return False
        s = surface.lower()
        return s in self._bols or s in self._aliases

    @property
    def needs_verification(self) -> list[Bol]:
        return [b for b in self._bols.values() if b.verify]

    def resolve(self, surface: str) -> Bol:
        """Resolve one spelling to its canonical bol. Follows aliases."""
        s = surface.lower()
        if s in self._bols:
            return self._bols[s]
        if s in self._aliases:
            return self._bols[self._aliases[s]]
        raise TokenizeError(surface, 0, surface)

    # -- tokenize -----------------------------------------------------------

    def tokenize(self, token: str) -> tuple[Bol, ...]:
        """Segment one whitespace-delimited token into bols by longest match.

        Raises TokenizeError naming the exact offset and substring that failed.
        Never drops characters and never guesses.
        """
        text = token.strip().lower()
        if not text:
            raise TokenizeError(token, 0, "")

        out: list[Bol] = []
        i = 0
        while i < len(text):
            match = self._longest_at(text, i)
            if match is None:
                raise TokenizeError(token, i, text[i:])
            out.append(self.resolve(match))
            i += len(match)
        return tuple(out)

    def _longest_at(self, text: str, start: int) -> str | None:
        limit = min(self._max_surface, len(text) - start)
        for length in range(limit, 0, -1):
            candidate = text[start : start + length]
            if candidate in self._bols or candidate in self._aliases:
                return candidate
        return None

    def strokes_for(self, token: str) -> tuple[str, ...]:
        """Flat stroke sequence for a token. Convenience for tests and tooling."""
        return tuple(s for bol in self.tokenize(token) for s in bol.strokes)
