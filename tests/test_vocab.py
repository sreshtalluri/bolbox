"""T1 -- the stroke vocabulary is the single source of truth.

The failure this file exists to prevent: a stroke named somewhere (a kit, the
note map, the lexicon) that is not in strokes.yaml, or a stroke in strokes.yaml
that a kit does not supply. The second one plays silence, which reads as a
sequencing bug and costs an evening.
"""

from __future__ import annotations

import pytest
import yaml

from bolbox.errors import UnknownStrokeError, VocabError
from bolbox.vocab import Vocabulary


@pytest.fixture(scope="module")
def vocab() -> Vocabulary:
    return Vocabulary.load()


# -- the real file ---------------------------------------------------------


def test_ships_a_loadable_vocabulary(vocab: Vocabulary) -> None:
    assert len(vocab) > 0
    assert vocab.version == 1


def test_composites_are_not_strokes(vocab: Vocabulary) -> None:
    """`dha` is one syllable made of two strokes, so it belongs in the lexicon.

    Putting it here would let a kit supply a `dha` sample without supplying the
    `ge` and `na` that MIDI export needs, which is exactly the kind of drift the
    single-source-of-truth rule exists to stop.
    """
    for composite in ("dha", "dhin", "dhun"):
        assert composite not in vocab, f"{composite} is a composite, not a stroke"


def test_every_stroke_is_on_a_real_drum(vocab: Vocabulary) -> None:
    assert {s.drum for s in vocab} <= {"dayan", "bayan"}
    assert vocab.on_drum("bayan"), "bayan strokes are required for ge/ka"
    assert vocab.on_drum("dayan")


def test_ge_is_resonant_and_on_the_bayan(vocab: Vocabulary) -> None:
    """The pitch envelope in the kit schema exists for this stroke specifically."""
    ge = vocab["ge"]
    assert ge.drum == "bayan"
    assert ge.resonant


def test_lookup_is_case_insensitive(vocab: Vocabulary) -> None:
    assert "GE" in vocab
    assert vocab["Ge"].name == "ge"


def test_names_are_stable_order(vocab: Vocabulary) -> None:
    """Order is part of the contract -- the CTC vocabulary is generated from it."""
    assert vocab.names == Vocabulary.load().names


# -- require() -------------------------------------------------------------


def test_require_accepts_known_strokes(vocab: Vocabulary) -> None:
    vocab.require(["ge", "na"], source="test")


def test_require_names_every_unknown_at_once(vocab: Vocabulary) -> None:
    with pytest.raises(UnknownStrokeError) as exc:
        vocab.require(["ge", "wobble", "na", "sproing"], source="kit 'bogus'")

    assert exc.value.unknown == ["wobble", "sproing"]
    message = str(exc.value)
    assert "wobble" in message and "sproing" in message
    assert "kit 'bogus'" in message, "the error must name where the bad stroke came from"


def test_require_rejects_a_composite(vocab: Vocabulary) -> None:
    """A kit listing `dha` as a stroke is a mistake worth catching loudly."""
    with pytest.raises(UnknownStrokeError):
        vocab.require(["dha"], source="kit 'confused'")


# -- missing_from(): the silent-dropout guard ------------------------------


def test_missing_from_reports_uncovered_strokes(vocab: Vocabulary) -> None:
    """The direction require() cannot check.

    A kit supplying only `ge` names nothing unknown, so require() passes -- but
    every other stroke would play silence. This is the check that catches it.
    """
    missing = vocab.missing_from(["ge"])
    assert "na" in missing
    assert "ge" not in missing
    assert len(missing) == len(vocab) - 1


def test_missing_from_is_empty_for_a_complete_kit(vocab: Vocabulary) -> None:
    assert vocab.missing_from(vocab.names) == []


def test_missing_from_ignores_case(vocab: Vocabulary) -> None:
    assert vocab.missing_from([n.upper() for n in vocab.names]) == []


# -- malformed input -------------------------------------------------------


@pytest.mark.parametrize(
    "body, fragment",
    [
        ("version: 1\nstrokes: {}\n", "non-empty mapping"),
        ("version: 1\n", "non-empty mapping"),
        ("version: 1\nstrokes:\n  ge:\n    drum: tabla\n    damped: false\n", "drum"),
        ("version: 1\nstrokes:\n  ge:\n    drum: bayan\n", "damped"),
        ("version: 1\nstrokes:\n  Ge:\n    drum: bayan\n    damped: false\n", "lowercase"),
        ("version: 1\nstrokes:\n  ge: 3\n", "mapping"),
        ("- not a mapping\n", "mapping at the top level"),
    ],
)
def test_malformed_vocabulary_is_rejected(body: str, fragment: str) -> None:
    with pytest.raises(VocabError) as exc:
        Vocabulary.from_dict(yaml.safe_load(body), source="test.yaml")
    assert fragment in str(exc.value)


def test_missing_file_is_a_clear_error(tmp_path) -> None:
    with pytest.raises(VocabError) as exc:
        Vocabulary.load(tmp_path / "nope.yaml")
    assert "not found" in str(exc.value)
