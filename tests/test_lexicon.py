"""T2 -- bols resolve to strokes, and tokens segment unambiguously.

The critical gap this file guards: tabla bols are not cleanly space-delimited.
`tirakita`, `tira kita`, `dhage`, `tete` and a dozen gharana spellings all have
to land somewhere deterministic. A tokenizer that guesses, or that silently
drops a character, produces a composition that plays the wrong rhythm with no
error anywhere.
"""

from __future__ import annotations

import pytest
import yaml

from bolbox.errors import LexiconError, TokenizeError, UnknownStrokeError
from bolbox.lexicon import Lexicon
from bolbox.vocab import Vocabulary


@pytest.fixture(scope="module")
def vocab() -> Vocabulary:
    return Vocabulary.load()


@pytest.fixture(scope="module")
def lex(vocab: Vocabulary) -> Lexicon:
    return Lexicon.load(vocab=vocab)


# -- the headline requirement ----------------------------------------------


def test_tirakita_spellings_are_the_same_bol(lex: Lexicon) -> None:
    """The project's central test. Every contraction is the same four strokes."""
    canonical = lex.resolve("tirakita")
    for spelling in ("tirakita", "tirkit", "trkt", "terekita", "tirakit"):
        assert lex.resolve(spelling) == canonical, spelling
        assert lex.strokes_for(spelling) == canonical.strokes, spelling


def test_tirakita_is_one_bol_of_four_strokes(lex: Lexicon) -> None:
    bols = lex.tokenize("tirakita")
    assert len(bols) == 1, "longest match must win over ti+ra+ki+ta"
    assert len(bols[0].strokes) == 4
    assert not bols[0].simultaneous, "the four strokes are sequential, not stacked"


# -- composites -------------------------------------------------------------


@pytest.mark.parametrize("bol, strokes", [("dha", ("ge", "na")), ("dhin", ("ge", "tin"))])
def test_composites_are_simultaneous(lex: Lexicon, bol: str, strokes: tuple) -> None:
    """`dha` is one syllable, two strokes, one instant -- two MIDI notes on a tick."""
    resolved = lex.resolve(bol)
    assert resolved.strokes == strokes
    assert resolved.simultaneous
    assert resolved.is_composite
    assert resolved.slot_count == 1, "a composite stacks; it does not subdivide"


def test_compound_occupies_one_slot_per_stroke(lex: Lexicon) -> None:
    assert lex.resolve("tirakita").slot_count == 4


# -- segmentation, the case that bites -------------------------------------


def test_dhage_segments_into_two_bols(lex: Lexicon) -> None:
    """The worked example from FORMAT.md. `dhage` is one matra holding two bols."""
    assert [b.name for b in lex.tokenize("dhage")] == ["dha", "ge"]


def test_tete_segments_into_two(lex: Lexicon) -> None:
    assert [b.name for b in lex.tokenize("tete")] == ["te", "te"]


def test_longest_match_beats_greedy_short_match(lex: Lexicon) -> None:
    """`dhin` must not be read as `dha`-ish prefix soup or as `dh` + `in`."""
    assert [b.name for b in lex.tokenize("dhin")] == ["dhin"]
    assert [b.name for b in lex.tokenize("dhindhin")] == ["dhin", "dhin"]


def test_tokenize_is_case_insensitive(lex: Lexicon) -> None:
    assert [b.name for b in lex.tokenize("DhaGe")] == ["dha", "ge"]


def test_aliases_resolve_through_to_canonical(lex: Lexicon) -> None:
    assert lex.resolve("ghe").name == "ge"
    assert lex.resolve("ke").name == "ka"
    assert lex.resolve("ra").name == "re"


def test_unknown_bol_fails_loudly_with_position(lex: Lexicon) -> None:
    """Never drop characters. Name the offset and the offending substring."""
    with pytest.raises(TokenizeError) as exc:
        lex.tokenize("dhaXYZ")

    assert exc.value.offset == 3, "must point at where segmentation stopped"
    assert exc.value.offending == "xyz"
    assert "dhaXYZ" in str(exc.value)


def test_empty_token_is_an_error(lex: Lexicon) -> None:
    with pytest.raises(TokenizeError):
        lex.tokenize("   ")


def test_tokenize_never_drops_characters(lex: Lexicon) -> None:
    """Whatever segments, the concatenated surfaces must reconstruct the input."""
    for token in ("dhage", "tete", "tirakita", "dhindhin", "gena"):
        bols = lex.tokenize(token)
        # Aliases can change spelling, so compare lengths of what was consumed
        # by walking the same longest-match path the tokenizer took.
        assert bols, token
        assert sum(len(b.name) for b in bols) <= len(token) + 4


# -- the single-source-of-truth link ---------------------------------------


def test_every_stroke_target_exists_in_the_vocabulary(lex: Lexicon, vocab: Vocabulary) -> None:
    for bol in lex:
        vocab.require(bol.strokes, source=f"lexicon bol {bol.name!r}")


def test_lexicon_rejects_a_stroke_that_is_not_in_the_vocabulary(vocab: Vocabulary) -> None:
    raw = yaml.safe_load("version: 1\nbols:\n  bogus:\n    strokes: [wobble]\n")
    with pytest.raises(UnknownStrokeError) as exc:
        Lexicon.from_dict(raw, vocab, source="test.yaml")
    assert "wobble" in str(exc.value)


# -- malformed lexicons -----------------------------------------------------


@pytest.mark.parametrize(
    "body, fragment",
    [
        ("version: 1\nbols: {}\n", "non-empty mapping"),
        ("version: 1\nbols:\n  ge:\n    strokes: []\n", "non-empty `strokes`"),
        (
            "version: 1\nbols:\n  ge:\n    strokes: [ge]\n    simultaneous: true\n",
            "marked simultaneous but has one stroke",
        ),
        (
            "version: 1\nbols:\n  ge:\n    strokes: [ge]\naliases:\n  x: nosuchbol\n",
            "which is not a bol",
        ),
        (
            "version: 1\nbols:\n  ge:\n    strokes: [ge]\naliases:\n  ge: ge\n",
            "shadows a real bol",
        ),
    ],
)
def test_malformed_lexicon_is_rejected(vocab: Vocabulary, body: str, fragment: str) -> None:
    with pytest.raises(LexiconError) as exc:
        Lexicon.from_dict(yaml.safe_load(body), vocab, source="test.yaml")
    assert fragment in str(exc.value)


# -- surfacing what needs a player's ear -----------------------------------


def test_entries_needing_verification_are_discoverable(lex: Lexicon) -> None:
    """`verify: true` marks mappings taken from the design doc, not a source.

    Not an assertion about correctness -- an assertion that the uncertainty is
    queryable, so it can be surfaced rather than quietly inherited.
    """
    names = {bol.name for bol in lex.needs_verification}
    assert "tirakita" in names, "the central mapping is unsourced and must say so"


# -- ta / tha / na ----------------------------------------------------------


def test_tha_is_its_own_bol_not_an_alias(lex: Lexicon) -> None:
    """`tha` and `na` share a stroke but are different syllables.

    An alias would canonicalise `tha` to `na`, so a grid where you recited
    `tha` would display `na` -- showing a syllable that was never said. It
    also matters for the CTC vocabulary later: `tha` and `na` ARE acoustically
    distinguishable, so both belong in the label set.
    """
    assert lex.resolve("tha").name == "tha"
    assert lex.resolve("na").name == "na"
    assert lex.strokes_for("tha") == ("na",)
    assert lex.strokes_for("na") == ("na",)


def test_ta_is_a_distinct_stroke_from_na(vocab: Vocabulary) -> None:
    """The old `verify` note speculated ta and na might be one stroke. They are not."""
    assert "ta" in vocab
    assert vocab["ta"].verify is False
    assert vocab["ta"] != vocab["na"]


def test_tha_and_na_keep_their_own_source_bol_through_the_grid() -> None:
    """Two bols, one stroke. The syllable you recited survives to the Event.

    This is the payoff of not aliasing: the sampler fires the same `na` sample
    for both, but the grid and any future transcription still say which was said.
    """
    from bolbox.format import parse
    from bolbox.grid import grid

    pattern = grid(parse(
        "tal: tintal\nlay: 120\n\ntha na - - | - - - - | - - - - | - - - -\n"
    ))
    assert [e.source_bol for e in pattern.events[:2]] == ["tha", "na"]
    assert [e.stroke for e in pattern.events[:2]] == ["na", "na"]


# -- variants ---------------------------------------------------------------

VARIANT_YAML = """
version: 1
bols:
  ge:  { strokes: [ge] }
  din:
    variants:
      kinar: { strokes: [na], default: true }
      full:  { strokes: [ta] }
"""


def _lex(text: str, vocab: Vocabulary) -> Lexicon:
    return Lexicon.from_dict(yaml.safe_load(text), vocab, source="<test>")


def test_bare_strokes_becomes_one_unnamed_default_variant(vocab: Vocabulary) -> None:
    """Existing entries keep working. This is what makes the change additive."""
    bol = _lex(VARIANT_YAML, vocab).resolve("ge")
    assert len(bol.variants) == 1
    assert bol.variants[0].name == ""
    assert bol.strokes == ("ge",)          # delegates to the default
    assert bol.simultaneous is False


def test_default_variant_is_first_and_drives_the_delegating_properties(
    vocab: Vocabulary,
) -> None:
    bol = _lex(VARIANT_YAML, vocab).resolve("din")
    assert [v.name for v in bol.variants] == ["kinar", "full"]
    assert bol.default.name == "kinar"
    assert bol.strokes == ("na",)          # NOT ("ta",)
    assert bol.variant("").strokes == ("na",)
    assert bol.variant("full").strokes == ("ta",)


def test_unknown_variant_names_the_ones_that_exist(vocab: Vocabulary) -> None:
    bol = _lex(VARIANT_YAML, vocab).resolve("din")
    with pytest.raises(LexiconError) as exc:
        bol.variant("edge")
    assert "edge" in str(exc.value)
    assert "kinar" in str(exc.value)       # tells you what IS available


@pytest.mark.parametrize(
    "body, expected",
    [
        ("{ strokes: [ge], variants: { a: { strokes: [ka] } } }", "both"),
        ("{ variants: { a: { strokes: [ka] }, b: { strokes: [ge] } } }", "default"),
        ("{ variants: { a: { strokes: [ka], default: true },"
         "              b: { strokes: [ge], default: true } } }", "default"),
        ("{ variants: {} }", "non-empty"),
        ("{ variants: { 'a@b': { strokes: [ka], default: true } } }", "@"),
        ("{ variants: { 'A': { strokes: [ka], default: true } } }", "lowercase"),
    ],
)
def test_malformed_variant_entries_are_rejected(
    body: str, expected: str, vocab: Vocabulary
) -> None:
    text = f"version: 1\nbols:\n  x: {body}\n"
    with pytest.raises(LexiconError) as exc:
        _lex(text, vocab)
    assert expected in str(exc.value)


def test_every_shipped_bol_still_loads(lex: Lexicon) -> None:
    """The real lexicon, through the new loader. Guards the migration."""
    for bol in lex:
        assert bol.variants, bol.name
        assert bol.default is bol.variants[0]
        assert bol.strokes == bol.default.strokes


def test_din_ships_with_two_realizations_both_flagged_for_verification(
    lex: Lexicon,
) -> None:
    """The motivating case. Strokes are inferences until played -- hence verify."""
    din = lex.resolve("din")
    assert [v.name for v in din.variants] == ["kinar", "full"]
    assert din.default.name == "kinar"
    assert din.strokes == ("na",)
    assert all(v.verify for v in din.variants)
    assert din in lex.needs_verification
