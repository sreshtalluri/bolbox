"""Parser for the bolbox composition format. See data/compositions/FORMAT.md.

    text --parse--> Composition --flatten--> [PlacedBol]  --grid--> Pattern
                    (tree, exact               (bol positions,        (stroke
                     durations)                 still rational)        events)

DURATIONS ARE EXACT RATIONALS, ALWAYS

A top-level element is one matra. A group of k children splits its share k ways.
A token that segments into m bols splits its share m ways. All of that is
`Fraction` arithmetic, so `{7, ...}` -- seven strokes in one matra, which no
binary tick grid can represent -- lands exactly, and the cycle still sums to
exactly its matra count after any amount of nesting.

That exactness is what makes the central property test an equality rather than a
tolerance, and it is why a loop still lands on sam after a thousand repetitions.

WHAT THIS FILE DOES NOT DO

It does not expand bols into strokes. A `Token` keeps the surface text you typed
(`trkt`, `dhage`) so unparsing reproduces your file, and stroke expansion is
grid's job. The parser's only lexicon use is validation -- catching an unknown
bol at the line and column where you typed it, rather than three stages later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .errors import ParseError, TokenizeError
from .lexicon import Lexicon
from .tal import Tal, UnknownTalError, get_tal

REST = "-"
ACCENT_SUFFIXES = {"!": "accent", ".": "ghost"}

DEFAULT_LAY = 60.0

_HEADER_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")
_WORD_RE = re.compile(r"[A-Za-z]+")
_INT_RE = re.compile(r"[0-9]+")


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """A leaf: one bol token (possibly multi-bol, like `dhage`) or a rest.

    ``line`` and ``column`` are excluded from equality so that structural
    comparison -- which is what the round-trip property asserts -- is not
    defeated by whitespace differences.
    """

    text: str
    accent: str | None = None
    line: int = field(default=0, compare=False)
    column: int = field(default=0, compare=False)

    @property
    def is_rest(self) -> bool:
        return self.text == REST

    def unparse(self) -> str:
        suffix = next(
            (k for k, v in ACCENT_SUFFIXES.items() if v == self.accent), ""
        )
        return f"{self.text}{suffix}"


@dataclass(frozen=True)
class Group:
    """`{n, e1 ... en}` -- n elements sharing one element's worth of time.

    ``declared`` is redundant with ``len(children)`` on purpose. It is a
    checksum on hand-typed material: a miscounted group is caught at the group
    instead of surfacing as a whole line that fails to sum to the cycle.
    """

    declared: int
    children: tuple["Node", ...]
    line: int = field(default=0, compare=False)
    column: int = field(default=0, compare=False)

    def unparse(self) -> str:
        inner = " ".join(child.unparse() for child in self.children)
        return f"{{{self.declared}, {inner}}}"


Node = Token | Group


@dataclass(frozen=True)
class Avartan:
    """One full cycle. Exactly `tal.matras` top-level elements."""

    elements: tuple[Node, ...]
    vibhags: tuple[int, ...] | None = None
    line: int = field(default=0, compare=False)

    def unparse(self) -> str:
        if not self.vibhags:
            return " ".join(e.unparse() for e in self.elements)
        out, index = [], 0
        for width in self.vibhags:
            out.append(" ".join(e.unparse() for e in self.elements[index : index + width]))
            index += width
        return " | ".join(out)


@dataclass(frozen=True)
class PlacedBol:
    """One bol, positioned and given an exact share of the cycle.

    ``duration`` is what lets grid subdivide further: a compound like
    ``tirakita`` spreads its strokes across exactly this span, while a composite
    like ``dha`` stacks all of its strokes on ``pos``.
    """

    pos: Fraction
    duration: Fraction
    surface: str
    accent: str | None
    matra: int
    variant: str = ""
    line: int = field(default=0, compare=False)
    column: int = field(default=0, compare=False)


@dataclass(frozen=True)
class Composition:
    tal: Tal
    avartans: tuple[Avartan, ...]
    lay: float = DEFAULT_LAY
    title: str = ""
    header: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def total_matras(self) -> int:
        return self.tal.matras * len(self.avartans)

    def unparse(self) -> str:
        lines = [f"tal: {self.tal.name}", f"lay: {self.lay:g}"]
        if self.title:
            lines.append(f"title: {self.title}")
        lines.append("")
        lines.extend(a.unparse() for a in self.avartans)
        return "\n".join(lines) + "\n"

    def flatten(self, lexicon: Lexicon | None = None) -> list[PlacedBol]:
        """Every bol in the composition, positioned in matras from the start.

        Positions are absolute across avartans, so avartan 2 of a tintal
        composition starts at matra 16. Rests are omitted -- they occupy time,
        which is already reflected in their neighbours' positions, and produce
        nothing.
        """
        lexicon = lexicon or Lexicon.load()
        out: list[PlacedBol] = []
        for index, avartan in enumerate(self.avartans):
            offset = Fraction(index * self.tal.matras)
            out.extend(_flatten_avartan(avartan, offset, lexicon))
        return out


# ---------------------------------------------------------------------------
# flatten
# ---------------------------------------------------------------------------


def _flatten_avartan(
    avartan: Avartan, offset: Fraction, lexicon: Lexicon
) -> list[PlacedBol]:
    out: list[PlacedBol] = []
    for matra, element in enumerate(avartan.elements):
        _place(element, offset + matra, Fraction(1), matra, lexicon, out)
    return out


def _place(
    node: Node,
    start: Fraction,
    duration: Fraction,
    matra: int,
    lexicon: Lexicon,
    out: list[PlacedBol],
) -> None:
    if isinstance(node, Group):
        share = duration / len(node.children)
        for index, child in enumerate(node.children):
            _place(child, start + share * index, share, matra, lexicon, out)
        return

    if node.is_rest:
        return

    # A token may carry several bols (`dhage` -> dha, ge). They share the slot.
    segments = lexicon.tokenize(node.text)
    share = duration / len(segments)
    for index, segment in enumerate(segments):
        out.append(
            PlacedBol(
                pos=start + share * index,
                duration=share,
                surface=segment.bol.name,
                accent=node.accent,
                matra=matra,
                variant=segment.variant.name,
                line=node.line,
                column=node.column,
            )
        )


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


def parse_file(path: Path | str, lexicon: Lexicon | None = None) -> Composition:
    path = Path(path)
    return parse(path.read_text(encoding="utf-8"), lexicon=lexicon, source=str(path))


def parse(
    text: str, lexicon: Lexicon | None = None, source: str = "<string>"
) -> Composition:
    lexicon = lexicon or Lexicon.load()
    lines = text.splitlines()

    header, body_start = _parse_header(lines)

    if "tal" not in header:
        raise ParseError(
            "missing required `tal:` header. v1 supports: tintal", 1, 1
        )
    try:
        tal = get_tal(header["tal"])
    except UnknownTalError as exc:
        raise ParseError(str(exc), 1, 1, header["tal"]) from exc

    lay = _parse_lay(header, source)

    avartans: list[Avartan] = []
    for offset, raw in enumerate(lines[body_start:]):
        line_no = body_start + offset + 1
        stripped = _strip_comment(raw)
        if not stripped.strip():
            continue
        avartans.append(_parse_avartan(stripped, line_no, tal, lexicon))

    if not avartans:
        raise ParseError("no avartans found -- the body is empty", body_start + 1, 1)

    return Composition(
        tal=tal,
        avartans=tuple(avartans),
        lay=lay,
        title=header.get("title", ""),
        header=header,
    )


def _strip_comment(line: str) -> str:
    index = line.find("#")
    return line if index < 0 else line[:index]


def _parse_header(lines: list[str]) -> tuple[dict[str, str], int]:
    """Read `key: value` lines. Returns the header and the first body line index.

    Supports YAML-style folded values (`key: >` followed by indented lines) so a
    `source:` note can run to a paragraph without the continuation lines being
    mistaken for bols -- which is exactly what they look like to the body parser.
    """
    header: dict[str, str] = {}
    index = 0
    while index < len(lines):
        raw = lines[index]
        line = _strip_comment(raw).strip()

        if not line:
            index += 1
            if header:
                return header, index
            continue

        match = _HEADER_RE.match(line)
        if not match:
            return header, index

        key, value = match.group(1).lower(), match.group(2).strip()
        index += 1

        if value == ">":
            folded: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                if not candidate.strip():
                    break
                if not candidate[:1].isspace():
                    break
                folded.append(_strip_comment(candidate).strip())
                index += 1
            value = " ".join(folded)

        header[key] = value

    return header, len(lines)


def _parse_lay(header: dict[str, str], source: str) -> float:
    raw = header.get("lay")
    if raw is None:
        return DEFAULT_LAY
    try:
        lay = float(raw)
    except ValueError:
        raise ParseError(f"`lay` must be a number, got {raw!r}", 1, 1, raw) from None
    if lay <= 0:
        raise ParseError(f"`lay` must be positive, got {lay}", 1, 1, raw)
    return lay


# -- one avartan ------------------------------------------------------------


def _parse_avartan(line: str, line_no: int, tal: Tal, lexicon: Lexicon) -> Avartan:
    segments = line.split("|")
    has_bars = len(segments) > 1

    elements: list[Node] = []
    widths: list[int] = []
    column_base = 0
    for segment in segments:
        parsed = _parse_elements(segment, line_no, column_base, lexicon)
        widths.append(len(parsed))
        elements.extend(parsed)
        column_base += len(segment) + 1

    if has_bars and tuple(widths) != tal.vibhags:
        raise ParseError(
            f"vibhag widths {tuple(widths)} do not match {tal.name} {tal.vibhags}",
            line_no,
            1,
            line.strip(),
        )

    if len(elements) != tal.matras:
        raise ParseError(
            f"expected {tal.matras} matras, found {len(elements)}",
            line_no,
            1,
            line.strip(),
        )

    return Avartan(
        elements=tuple(elements),
        vibhags=tal.vibhags if has_bars else None,
        line=line_no,
    )


def _parse_elements(
    segment: str, line_no: int, column_base: int, lexicon: Lexicon
) -> list[Node]:
    """Recursive-descent over one vibhag's worth of text."""
    elements: list[Node] = []
    index = 0
    length = len(segment)

    while index < length:
        char = segment[index]

        if char.isspace():
            index += 1
            continue

        if char == "}":
            raise ParseError(
                "unmatched '}'", line_no, column_base + index + 1, segment.strip()
            )

        if char == "{":
            group, index = _parse_group(
                segment, index, line_no, column_base, lexicon
            )
            elements.append(group)
            continue

        node, index = _parse_token(segment, index, line_no, column_base, lexicon)
        elements.append(node)

    return elements


def _parse_group(
    segment: str, index: int, line_no: int, column_base: int, lexicon: Lexicon
) -> tuple[Group, int]:
    open_column = column_base + index + 1
    index += 1  # past '{'

    match = _INT_RE.match(segment, index)
    if not match:
        raise ParseError(
            "a group must start with a count, as in '{4, te re ki ta}'",
            line_no,
            open_column,
            segment[index : index + 12],
        )
    declared = int(match.group())
    index = match.end()

    while index < len(segment) and segment[index].isspace():
        index += 1
    if index >= len(segment) or segment[index] != ",":
        raise ParseError(
            "expected ',' after the group count",
            line_no,
            column_base + index + 1,
            segment[index : index + 12],
        )
    index += 1

    children: list[Node] = []
    while True:
        while index < len(segment) and segment[index].isspace():
            index += 1
        if index >= len(segment):
            raise ParseError(
                "unclosed group -- expected '}'", line_no, open_column, segment.strip()
            )
        if segment[index] == "}":
            index += 1
            break
        if segment[index] == "{":
            child, index = _parse_group(segment, index, line_no, column_base, lexicon)
        else:
            child, index = _parse_token(segment, index, line_no, column_base, lexicon)
        children.append(child)

    if not children:
        raise ParseError("empty group", line_no, open_column, "{}")

    if declared != len(children):
        raise ParseError(
            f"declared {declared} elements but found {len(children)}",
            line_no,
            open_column,
            _preview_group(declared, children),
        )

    return Group(declared=declared, children=tuple(children), line=line_no,
                 column=open_column), index


def _preview_group(declared: int, children: list[Node]) -> str:
    inner = " ".join(child.unparse() for child in children)
    return f"{{{declared}, {inner}}}"


def _parse_token(
    segment: str, index: int, line_no: int, column_base: int, lexicon: Lexicon
) -> tuple[Token, int]:
    column = column_base + index + 1

    if segment[index] == REST:
        return Token(text=REST, line=line_no, column=column), index + 1

    match = _WORD_RE.match(segment, index)
    if not match:
        raise ParseError(
            "expected a bol, a rest '-', or a group '{...}'",
            line_no,
            column,
            segment[index : index + 12],
        )

    word = match.group()
    index = match.end()

    accent = None
    if index < len(segment) and segment[index] in ACCENT_SUFFIXES:
        accent = ACCENT_SUFFIXES[segment[index]]
        index += 1

    # Validate here so an unknown bol is reported at the column you typed it,
    # not three pipeline stages later with no position information left.
    try:
        lexicon.tokenize(word)
    except TokenizeError as exc:
        raise ParseError(
            f"cannot segment {word!r} at offset {exc.offset}: "
            f"no known bol starts at {exc.offending!r}",
            line_no,
            column,
            word,
        ) from exc

    return Token(text=word, accent=accent, line=line_no, column=column), index
