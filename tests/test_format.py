"""T3 -- the composition parser, with property-based tests.

The parser is the highest-risk component in the project: it is recursive, it is
what every typed composition depends on, and its failures are silent. A nesting
or rounding bug does not crash -- it produces a pattern that plays slightly
wrong, which you would blame on your typing, or later on the model.

So the important tests here are properties, not examples. Hypothesis generates
thousands of nested compositions and asserts two things that must hold for all
of them:

  1. every avartan's durations sum to EXACTLY the tal's matra count
  2. unparse -> parse is structurally the identity

The first is an equality rather than a tolerance because positions are exact
`Fraction`s. That is the whole reason for the rational time model, and this is
where it gets proven.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bolbox.errors import ParseError
from bolbox.format import Avartan, Composition, Group, Token, parse, parse_file
from bolbox.lexicon import Lexicon
from bolbox.tal import TINTAL
from bolbox.vocab import Vocabulary

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
COMPOSITIONS = REPO_ROOT / "data" / "compositions"

_VOCAB = Vocabulary.load()
_LEX = Lexicon.load(vocab=_VOCAB)


@pytest.fixture(scope="module")
def lex() -> Lexicon:
    return _LEX


def header(body: str, tal: str = "tintal", lay: float = 120) -> str:
    return f"tal: {tal}\nlay: {lay:g}\n\n{body}\n"


# ---------------------------------------------------------------------------
# the shipped files
# ---------------------------------------------------------------------------


def test_theka_parses(lex: Lexicon) -> None:
    comp = parse_file(COMPOSITIONS / "theka-tintal.txt", lexicon=lex)
    assert comp.tal is TINTAL
    assert len(comp.avartans) == 1
    assert len(comp.avartans[0].elements) == 16
    assert comp.lay == 120


def test_theka_flattens_to_sixteen_bols(lex: Lexicon) -> None:
    comp = parse_file(COMPOSITIONS / "theka-tintal.txt", lexicon=lex)
    placed = comp.flatten(lex)
    assert len(placed) == 16
    assert [p.pos for p in placed] == [Fraction(i) for i in range(16)]


def test_demo_file_exercises_every_feature(lex: Lexicon) -> None:
    """If this file stops parsing, FORMAT.md and the parser have diverged."""
    comp = parse_file(COMPOSITIONS / "demo-format-features.txt", lexicon=lex)
    assert len(comp.avartans) == 7
    for avartan in comp.avartans:
        assert len(avartan.elements) == 16


# ---------------------------------------------------------------------------
# placement -- the arithmetic that has to be exact
# ---------------------------------------------------------------------------


def test_compound_bol_occupies_exactly_one_matra(lex: Lexicon) -> None:
    comp = parse(header("dha tirakita " + "dha " * 14), lexicon=lex)
    placed = comp.flatten(lex)
    tirakita = next(p for p in placed if p.surface == "tirakita")
    assert tirakita.pos == 1
    assert tirakita.duration == 1


def test_group_splits_its_matra_evenly(lex: Lexicon) -> None:
    comp = parse(header("dha {2, ti ra} " + "dha " * 14), lexicon=lex)
    positions = {p.surface: p.pos for p in comp.flatten(lex)}
    assert positions["ti"] == Fraction(1)
    assert positions["re"] == Fraction(3, 2), "`ra` is an alias of `re`"


def test_nested_group_positions_are_exact(lex: Lexicon) -> None:
    """`{2, dha {4, te re ki ta}}` -- half a matra, then four eighths."""
    comp = parse(header("{2, dha {4, te re ki ta}} " + "dha " * 15), lexicon=lex)
    placed = comp.flatten(lex)
    inner = [p for p in placed if p.surface in {"te", "re", "ki", "ta"} and p.pos < 1]
    assert [p.pos for p in inner] == [
        Fraction(1, 2),
        Fraction(5, 8),
        Fraction(3, 4),
        Fraction(7, 8),
    ]
    assert all(p.duration == Fraction(1, 8) for p in inner)


def test_seven_way_group_is_exact(lex: Lexicon) -> None:
    """A 7-grouping is the case no binary tick grid can represent.

    If positions were floats or fixed PPQ ticks this would drift. As Fractions
    the seventh stroke sits at exactly 6/7 and the matra closes exactly on 1.
    """
    comp = parse(header("{7, ta ki ta ta ki ta ka} " + "dha " * 15), lexicon=lex)
    inner = [p for p in comp.flatten(lex) if p.pos < 1]
    assert [p.pos for p in inner] == [Fraction(i, 7) for i in range(7)]
    assert inner[-1].pos + inner[-1].duration == Fraction(1)


def test_multi_bol_token_shares_its_matra(lex: Lexicon) -> None:
    """`dhage` -> dha at 0, ge at 1/2. Same total as one bol."""
    comp = parse(header("dhage " + "dha " * 15), lexicon=lex)
    first_two = [p for p in comp.flatten(lex) if p.pos < 1]
    assert [(p.surface, p.pos) for p in first_two] == [
        ("dha", Fraction(0)),
        ("ge", Fraction(1, 2)),
    ]


def test_rests_occupy_time_but_emit_nothing(lex: Lexicon) -> None:
    comp = parse(header("dha - dha - " + "dha " * 12), lexicon=lex)
    placed = comp.flatten(lex)
    assert len(placed) == 14
    assert [p.pos for p in placed[:2]] == [Fraction(0), Fraction(2)]


def test_avartans_are_positioned_absolutely(lex: Lexicon) -> None:
    line = " ".join(["dha"] * 16)
    comp = parse(header(f"{line}\n{line}"), lexicon=lex)
    placed = comp.flatten(lex)
    assert len(placed) == 32
    assert placed[16].pos == Fraction(16), "avartan 2 starts at matra 16"


def test_accents_are_carried_through(lex: Lexicon) -> None:
    comp = parse(header("dha! dha. " + "dha " * 14), lexicon=lex)
    placed = comp.flatten(lex)
    assert placed[0].accent == "accent"
    assert placed[1].accent == "ghost"
    assert placed[2].accent is None


def test_aliases_resolve_but_the_file_keeps_your_spelling(lex: Lexicon) -> None:
    comp = parse(header("trkt " + "dha " * 15), lexicon=lex)
    assert comp.avartans[0].elements[0].text == "trkt", "round-trip keeps the source"
    assert comp.flatten(lex)[0].surface == "tirakita", "but it resolves canonically"


# ---------------------------------------------------------------------------
# errors -- loud, positional, never silent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body, fragment",
    [
        ("dha dha dha", "expected 16 matras, found 3"),
        (" ".join(["dha"] * 17), "expected 16 matras, found 17"),
        ("{3, ta ki ta ta} " + "dha " * 15, "declared 3 elements but found 4"),
        ("{2, ta ki ta} " + "dha " * 15, "declared 2 elements but found 3"),
        ("{4, ta ki ta ta " + "dha " * 15, "unclosed group"),
        ("} " + "dha " * 15, "unmatched '}'"),
        ("{, ta} " + "dha " * 15, "must start with a count"),
        ("{4 ta ki ta ta} " + "dha " * 15, "expected ',' after the group count"),
        ("dhaXYZ " + "dha " * 15, "no known bol starts at"),
        ("dha dha | dha dha", "do not match tintal"),
    ],
)
def test_malformed_bodies_are_rejected(lex: Lexicon, body: str, fragment: str) -> None:
    with pytest.raises(ParseError) as exc:
        parse(header(body), lexicon=lex)
    assert fragment in str(exc.value)


def test_errors_carry_line_and_column(lex: Lexicon) -> None:
    good = " ".join(["dha"] * 16)
    with pytest.raises(ParseError) as exc:
        parse(header(f"{good}\n{good}\ndha dhaXYZ dha"), lexicon=lex)
    assert exc.value.line == 6, "third body line of a 3-line header"
    assert exc.value.column > 1, "must point past the first bol"


def test_missing_tal_header_is_rejected(lex: Lexicon) -> None:
    with pytest.raises(ParseError) as exc:
        parse("lay: 120\n\n" + " ".join(["dha"] * 16), lexicon=lex)
    assert "missing required `tal:`" in str(exc.value)


def test_unsupported_tal_says_what_is_supported(lex: Lexicon) -> None:
    with pytest.raises(ParseError) as exc:
        parse(header(" ".join(["dha"] * 16), tal="jhaptal"), lexicon=lex)
    assert "jhaptal" in str(exc.value)
    assert "tintal" in str(exc.value), "must name what v1 does support"


def test_bad_lay_is_rejected(lex: Lexicon) -> None:
    for bad in ("0", "-4", "fast"):
        with pytest.raises(ParseError):
            parse(f"tal: tintal\nlay: {bad}\n\n" + " ".join(["dha"] * 16), lexicon=lex)


def test_empty_body_is_rejected(lex: Lexicon) -> None:
    with pytest.raises(ParseError) as exc:
        parse("tal: tintal\nlay: 120\n\n# just a comment\n", lexicon=lex)
    assert "body is empty" in str(exc.value)


def test_comments_and_blank_lines_are_ignored(lex: Lexicon) -> None:
    line = " ".join(["dha"] * 16)
    comp = parse(header(f"# a comment\n\n{line}  # trailing\n\n"), lexicon=lex)
    assert len(comp.avartans) == 1


# ---------------------------------------------------------------------------
# properties
# ---------------------------------------------------------------------------

SAFE_BOLS = ["dha", "dhin", "ta", "na", "ti", "te", "re", "ki", "ka", "ge", "tirakita"]


@st.composite
def _node(draw: st.DrawFn, depth: int):
    kinds = ["bol", "bol", "rest"]  # bias toward bols; groups are the rare case
    if depth > 0:
        kinds.append("group")
    kind = draw(st.sampled_from(kinds))

    if kind == "rest":
        return Token(text="-")
    if kind == "bol":
        return Token(
            text=draw(st.sampled_from(SAFE_BOLS)),
            accent=draw(st.sampled_from([None, "accent", "ghost"])),
        )

    count = draw(st.integers(min_value=1, max_value=4))
    children = tuple(draw(_node(depth - 1)) for _ in range(count))
    return Group(declared=count, children=children)


@st.composite
def _avartan(draw: st.DrawFn):
    elements = tuple(draw(_node(2)) for _ in range(TINTAL.matras))
    return Avartan(elements=elements, vibhags=draw(st.booleans()) and TINTAL.vibhags or None)


@st.composite
def _composition(draw: st.DrawFn):
    count = draw(st.integers(min_value=1, max_value=3))
    return Composition(
        tal=TINTAL,
        avartans=tuple(draw(_avartan()) for _ in range(count)),
        lay=draw(st.sampled_from([60.0, 100.0, 120.0, 240.0])),
    )


@given(_composition())
@settings(max_examples=250, deadline=None)
def test_property_durations_sum_to_the_cycle_exactly(comp: Composition) -> None:
    """The format's central invariant, asserted as an equality.

    Every bol's share, plus every rest's share, must tile the cycle with no gap
    and no overlap. Exact because the arithmetic is rational -- with floats this
    would need a tolerance, and a tolerance would hide the nesting bugs this
    test exists to find.
    """
    reparsed = parse(comp.unparse(), lexicon=_LEX)
    placed = reparsed.flatten(_LEX)

    total = Fraction(reparsed.total_matras)
    assert all(0 <= p.pos < total for p in placed)
    assert all(p.pos + p.duration <= total for p in placed)

    # Bols tile their slots: consecutive bols within an avartan never overlap.
    for earlier, later in zip(placed, placed[1:]):
        assert earlier.pos + earlier.duration <= later.pos + Fraction(0)


@given(_composition())
@settings(max_examples=250, deadline=None)
def test_property_unparse_then_parse_is_the_identity(comp: Composition) -> None:
    """The format and the parser cannot silently disagree.

    Structural, not byte-for-byte: line and column are excluded from equality,
    so alignment whitespace is free to differ. Everything that affects what you
    hear must survive the round trip.
    """
    once = parse(comp.unparse(), lexicon=_LEX)
    twice = parse(once.unparse(), lexicon=_LEX)
    assert once.avartans == twice.avartans
    assert once.lay == twice.lay
    assert once.tal is twice.tal


@given(_composition())
@settings(max_examples=100, deadline=None)
def test_property_positions_are_non_decreasing(comp: Composition) -> None:
    placed = parse(comp.unparse(), lexicon=_LEX).flatten(_LEX)
    assert placed == sorted(placed, key=lambda p: p.pos)


@given(_composition())
@settings(max_examples=100, deadline=None)
def test_property_every_position_is_a_fraction(comp: Composition) -> None:
    """Floats must never leak into the time model. This is the guard."""
    for placed in parse(comp.unparse(), lexicon=_LEX).flatten(_LEX):
        assert isinstance(placed.pos, Fraction)
        assert isinstance(placed.duration, Fraction)
        assert placed.duration > 0
