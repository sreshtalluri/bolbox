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
class Variant:
    """One physical realization of a bol.

    This holds what `Bol` used to hold. It exists because a bol does not have
    *a* realization -- `din` is struck full-handed or with one finger on the
    edge, and you SAY it identically either way. The choice is not in the audio,
    so it cannot be the acoustic model's problem; it is a rendering decision
    that lives here and is overridable in the notation.

    ``name`` is `""` for the implicit default of a bare `strokes:` entry.
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
        """How many sequential sub-slots this realization occupies."""
        return 1 if self.simultaneous else len(self.strokes)


@dataclass(frozen=True)
class Bol:
    """One spoken syllable or word, and the realizations it can take.

    ``variants`` is ordered with the default first. The strokes/simultaneous
    properties delegate to it, which is what lets grid.py, midi.py and every
    existing test keep working untouched.
    """

    name: str
    variants: tuple[Variant, ...]

    @property
    def default(self) -> Variant:
        return self.variants[0]

    def variant(self, name: str) -> Variant:
        if not name:
            return self.default
        for candidate in self.variants:
            if candidate.name == name:
                return candidate
        known = ", ".join(v.name for v in self.variants if v.name) or "(none)"
        raise LexiconError(
            f"bol {self.name!r} has no variant {name!r}; known variants: {known}"
        )

    # -- delegating to the default ----------------------------------------

    @property
    def strokes(self) -> tuple[str, ...]:
        return self.default.strokes

    @property
    def simultaneous(self) -> bool:
        return self.default.simultaneous

    @property
    def is_composite(self) -> bool:
        return self.default.is_composite

    @property
    def slot_count(self) -> int:
        return self.default.slot_count

    @property
    def description(self) -> str:
        return self.default.description

    @property
    def verify(self) -> bool:
        """True if ANY realization needs a player's ear."""
        return any(v.verify for v in self.variants)


VARIANT_SEP = "@"


@dataclass(frozen=True)
class Segment:
    """One bol occurrence inside a token, with the realization chosen for it."""

    bol: Bol
    variant: Variant


def _parse_variants(
    bol: str, raw: object, vocab: Vocabulary, source: str
) -> tuple[Variant, ...]:
    """Parse a `variants:` mapping. Exactly one entry must be the default.

    The default is returned FIRST, because every delegating property on `Bol`
    reads `variants[0]`.
    """
    if not isinstance(raw, dict) or not raw:
        raise LexiconError(f"{source}: bol {bol!r} `variants` must be a non-empty mapping")

    parsed: list[Variant] = []
    defaults: list[str] = []
    for name, body in raw.items():
        if not isinstance(name, str) or not name:
            raise LexiconError(f"{source}: bol {bol!r} has an empty variant name")
        if name != name.lower():
            raise LexiconError(
                f"{source}: bol {bol!r} variant {name!r} must be lowercase"
            )
        if "@" in name or any(c.isspace() for c in name):
            raise LexiconError(
                f"{source}: bol {bol!r} variant {name!r} may not contain "
                "'@' or whitespace -- '@' is the notation's variant separator"
            )
        if not isinstance(body, dict):
            raise LexiconError(
                f"{source}: bol {bol!r} variant {name!r} must map to a mapping"
            )
        if body.get("default"):
            defaults.append(name)
        parsed.append(_parse_variant(bol, name, body, vocab, source))

    if len(defaults) != 1:
        raise LexiconError(
            f"{source}: bol {bol!r} must mark exactly one variant `default: true`; "
            f"found {len(defaults)} ({', '.join(defaults) or 'none'})"
        )

    ordered = sorted(parsed, key=lambda v: v.name != defaults[0])
    return tuple(ordered)


def _parse_variant(
    bol: str, name: str, body: dict, vocab: Vocabulary, source: str
) -> Variant:
    where = f"{source}: bol {bol!r}" + (f" variant {name!r}" if name else "")

    strokes = body.get("strokes")
    if not isinstance(strokes, list) or not strokes:
        raise LexiconError(f"{where} needs a non-empty `strokes`")
    if not all(isinstance(s, str) for s in strokes):
        raise LexiconError(f"{where} strokes must be strings")

    # The single-source-of-truth check: every target must be a real stroke.
    vocab.require(strokes, source=where)

    simultaneous = bool(body.get("simultaneous", False))
    if simultaneous and len(strokes) < 2:
        raise LexiconError(f"{where} is marked simultaneous but has one stroke")

    return Variant(
        name=name,
        strokes=tuple(s.lower() for s in strokes),
        simultaneous=simultaneous,
        description=str(body.get("description", "")).strip(),
        verify=bool(body.get("verify", False)),
    )


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
            if VARIANT_SEP in name or any(c.isspace() for c in name):
                raise LexiconError(
                    f"{source}: bol {name!r} may not contain '@' or whitespace -- "
                    "'@' is the notation's variant separator and whitespace "
                    "separates matras"
                )
            if not isinstance(body, dict):
                raise LexiconError(f"{source}: bol {name!r} must map to a mapping")

            has_strokes = "strokes" in body
            has_variants = "variants" in body
            if has_strokes and has_variants:
                raise LexiconError(
                    f"{source}: bol {name!r} declares both `strokes` and "
                    "`variants`; use one or the other"
                )

            if has_variants:
                variants = _parse_variants(name, body["variants"], vocab, source)
            else:
                variants = (_parse_variant(name, "", body, vocab, source),)

            bols[name] = Bol(name=name, variants=variants)

        raw_aliases = raw.get("aliases") or {}
        if not isinstance(raw_aliases, dict):
            raise LexiconError(f"{source}: `aliases` must be a mapping")

        aliases: dict[str, str] = {}
        for alias, target in raw_aliases.items():
            if not isinstance(alias, str) or not isinstance(target, str):
                raise LexiconError(f"{source}: aliases must be string -> string")
            alias, target = alias.lower(), target.lower()
            if VARIANT_SEP in alias or any(c.isspace() for c in alias):
                raise LexiconError(
                    f"{source}: alias {alias!r} may not contain '@' or whitespace -- "
                    "'@' is the notation's variant separator and whitespace "
                    "separates matras"
                )
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

    def tokenize(self, token: str) -> tuple[Segment, ...]:
        """Segment one whitespace-delimited token into bols by longest match.

        A bol may be followed by `@name` to select a non-default realization.
        The suffix binds to the bol match immediately before it and the scan
        resumes after the variant name, which is unambiguous because `@` can
        never appear inside a surface form.

        The variant name itself is resolved by the same LONGEST MATCH rule as
        bol surfaces, scanned against that bol's own variant names: if a bol
        ever had variants `ka` and `kana`, `x@kana` resolves to `kana`, not
        `ka` followed by a trailing `na`. Only if none of the bol's variant
        names prefix the alpha run does the whole run get used as-is, so an
        unknown name like `din@edge` still fails with that exact name rather
        than a truncated, misleading one.

        Raises TokenizeError naming the exact offset and substring that failed.
        Never drops characters and never guesses.
        """
        text = token.strip().lower()
        if not text:
            raise TokenizeError(token, 0, "")

        out: list[Segment] = []
        i = 0
        while i < len(text):
            match = self._longest_at(text, i)
            if match is None:
                raise TokenizeError(token, i, text[i:])
            bol = self.resolve(match)
            i += len(match)

            variant_name = ""
            if i < len(text) and text[i] == VARIANT_SEP:
                start = i + 1
                end = start
                while end < len(text) and text[end].isalpha():
                    end += 1
                if end == start:
                    raise TokenizeError(token, i, text[i:])
                run = text[start:end]
                # A trailing bol can immediately follow the variant name with
                # no separator (`din@fullge` -> full, ge), so prefer the
                # longest of THIS bol's own variant names that prefixes the
                # alpha run over swallowing the whole run. If none of the
                # bol's variants match, fall back to the full run so an
                # unknown name (`din@edge`) still fails with that exact name
                # rather than a truncated, misleading one.
                known = sorted(
                    (v.name for v in bol.variants if v.name and run.startswith(v.name)),
                    key=len,
                    reverse=True,
                )
                variant_name = known[0] if known else run
                i = start + len(variant_name)

            out.append(Segment(bol=bol, variant=bol.variant(variant_name)))
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
        return tuple(s for seg in self.tokenize(token) for s in seg.variant.strokes)
