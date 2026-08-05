"""T6 -- Pattern -> .mid.

Two things here are easy to get wrong and expensive to notice late:

  1. Missing tempo or time-signature meta. The file plays, but the clip does not
     loop in a DAW, which is Milestone 1's actual pass criterion.
  2. Accumulated rounding. PPQ 1920 cannot represent a 7-way split, so those
     positions round -- but every tick is computed from the start of the
     pattern, never by adding deltas, so the error must not grow with time.
"""

from __future__ import annotations

from fractions import Fraction

import mido
import pytest

from bolbox.grid import grid_text
from bolbox.lexicon import Lexicon
from bolbox.midi import (
    CANONICAL_NOTE_MAP,
    DRUM_CHANNEL,
    PPQ,
    MidiMapError,
    build,
    note_for,
    ticks_for,
    to_bytes,
    write,
)
from bolbox.pattern import Pattern
from bolbox.tal import TINTAL
from bolbox.vocab import Vocabulary

_VOCAB = Vocabulary.load()
_LEX = Lexicon.load(vocab=_VOCAB)


def pattern_for(body: str, count: int = 1, lay: float = 120) -> Pattern:
    padded = body + " " + " ".join(["dha"] * (16 - count))
    return grid_text(f"tal: tintal\nlay: {lay:g}\n\n{padded}\n", lexicon=_LEX)


def messages(pattern: Pattern, kind: str) -> list:
    return [m for m in build(pattern).tracks[0] if m.type == kind]


def absolute_ticks(pattern: Pattern, kind: str = "note_on") -> list[int]:
    ticks, running = [], 0
    for message in build(pattern).tracks[0]:
        running += message.time
        if message.type == kind:
            ticks.append(running)
    return ticks


# -- the note map -----------------------------------------------------------


def test_every_stroke_in_the_vocabulary_has_a_note() -> None:
    """The single-source-of-truth link, in the direction midi.py owns."""
    for stroke in _VOCAB.names:
        assert note_for(stroke) in range(128), stroke


def test_note_map_has_no_collisions() -> None:
    """Two strokes on one note would be silently unplayable in a DAW."""
    notes = list(CANONICAL_NOTE_MAP.values())
    assert len(notes) == len(set(notes))


def test_unknown_stroke_says_how_to_fix_it() -> None:
    with pytest.raises(MidiMapError) as exc:
        note_for("wobble")
    assert "wobble" in str(exc.value)
    assert "midi_map" in str(exc.value), "must mention the kit override escape hatch"


def test_kit_override_wins_over_the_canonical_map() -> None:
    """How a bol-to-909 kit works without touching Python."""

    class Kit:
        def midi_override(self, stroke: str) -> int | None:
            return 60 if stroke == "ge" else None

    assert note_for("ge", Kit()) == 60
    assert note_for("na", Kit()) == CANONICAL_NOTE_MAP["na"], "falls through"


# -- composites -------------------------------------------------------------


def test_dha_emits_two_note_ons_on_one_tick() -> None:
    pattern = pattern_for("dha")
    on_messages = messages(pattern, "note_on")
    at_zero = [m for m in on_messages[:2]]
    assert len(at_zero) == 2
    assert {m.note for m in at_zero} == {
        CANONICAL_NOTE_MAP["ge"],
        CANONICAL_NOTE_MAP["na"],
    }
    assert at_zero[1].time == 0, "the second note is on the same tick"


def test_everything_is_on_the_percussion_channel() -> None:
    for message in messages(pattern_for("dha"), "note_on"):
        assert message.channel == DRUM_CHANNEL


def test_every_note_on_has_a_note_off() -> None:
    pattern = pattern_for("dha tirakita", 2)
    assert len(messages(pattern, "note_on")) == len(messages(pattern, "note_off"))


# -- meta events, without which the clip will not loop ---------------------


def test_tempo_meta_matches_lay() -> None:
    """For tintal one matra is one quarter, so lay converts straight through."""
    tempo = messages(pattern_for("dha", lay=120), "set_tempo")[0]
    assert mido.tempo2bpm(tempo.tempo) == pytest.approx(120.0)

    tempo = messages(pattern_for("dha", lay=90), "set_tempo")[0]
    assert mido.tempo2bpm(tempo.tempo) == pytest.approx(90.0)


def test_time_signature_is_present_and_matches_the_tal() -> None:
    signature = messages(pattern_for("dha"), "time_signature")[0]
    assert (signature.numerator, signature.denominator) == TINTAL.midi_time_signature
    assert (signature.numerator, signature.denominator) == (16, 4)


def test_track_ends_on_the_cycle_boundary_not_the_last_stroke() -> None:
    """A clip that ends at the last stroke loops early and drops the tail."""
    pattern = pattern_for("dha")
    total = sum(m.time for m in build(pattern).tracks[0])
    assert total == 16 * PPQ


def test_ppq_is_1920() -> None:
    assert build(pattern_for("dha")).ticks_per_beat == 1920


# -- text meta: what makes export lossless in bols -------------------------


def test_each_bol_gets_one_text_event_not_one_per_stroke() -> None:
    """`dha` is one word even though it is two notes."""
    texts = [m.text for m in messages(pattern_for("dha"), "text")]
    assert texts.count("dha") == 16, "sixteen dha in the padded avartan"


def test_compound_bol_records_its_word_once() -> None:
    pattern = pattern_for("tirakita")
    texts = [m.text for m in messages(pattern, "text")]
    assert texts.count("tirakita") == 1, "four strokes, one word"


def test_text_events_use_the_canonical_spelling() -> None:
    """You typed `trkt`; the file records `tirakita` so re-import is unambiguous."""
    pattern = pattern_for("trkt")
    assert "tirakita" in [m.text for m in messages(pattern, "text")]


# -- rounding: the one boundary where exactness ends -----------------------


def test_exact_positions_convert_without_rounding() -> None:
    assert ticks_for(Fraction(0), Fraction(1)) == 0
    assert ticks_for(Fraction(1), Fraction(1)) == PPQ
    assert ticks_for(Fraction(1, 4), Fraction(1)) == PPQ // 4
    assert ticks_for(Fraction(1, 3), Fraction(1)) == PPQ // 3, "1920 divides by 3"
    assert ticks_for(Fraction(1, 5), Fraction(1)) == PPQ // 5, "and by 5"


def test_seven_way_split_rounds_but_does_not_accumulate() -> None:
    """PPQ 1920 = 2^7 * 3 * 5 cannot represent a seventh. Bound the damage.

    Each tick is computed from the start of the pattern, so error stays under
    half a tick everywhere instead of growing across the cycle.
    """
    pattern = pattern_for("{7, ta ki ta ta ki ta ka}")
    ticks = absolute_ticks(pattern)[:7]
    for index, tick in enumerate(ticks):
        exact = Fraction(index, 7) * PPQ
        assert abs(tick - float(exact)) <= 0.5, f"stroke {index} drifted"


def test_error_does_not_grow_across_avartans() -> None:
    """The thousandth cycle must be as accurate as the first.

    The same 7-group repeats at the head of every avartan. Its strokes' offsets
    from their own cycle start must be byte-identical every time -- which they
    are only because each tick is computed from the pattern origin rather than
    by adding a cycle duration over and over.
    """
    line = "{7, ta ki ta ta ki ta ka} " + " ".join(["dha"] * 15)
    text = "tal: tintal\nlay: 120\n\n" + "\n".join([line] * 8) + "\n"
    pattern = grid_text(text, lexicon=_LEX)

    ticks_by_cycle: list[tuple[int, ...]] = []
    for cycle in range(8):
        start = Fraction(cycle * 16)
        offsets = tuple(
            ticks_for(event.pos, TINTAL.matra_to_quarter) - cycle * 16 * PPQ
            for event in pattern.events
            if start <= event.pos < start + 1
        )
        ticks_by_cycle.append(offsets)

    assert len(set(ticks_by_cycle)) == 1, f"drifted across cycles: {ticks_by_cycle}"
    assert len(ticks_by_cycle[0]) == 7


# -- files ------------------------------------------------------------------


def test_writes_a_file_that_reloads(tmp_path) -> None:
    pattern = pattern_for("dha tirakita", 2)
    path = write(pattern, tmp_path / "out.mid")
    assert path.exists()

    reloaded = mido.MidiFile(str(path))
    assert reloaded.ticks_per_beat == PPQ
    assert any(m.type == "note_on" for m in reloaded.tracks[0])


def test_to_bytes_matches_a_written_file(tmp_path) -> None:
    pattern = pattern_for("dha")
    path = write(pattern, tmp_path / "out.mid")
    assert to_bytes(pattern) == path.read_bytes()


def test_theka_renders_end_to_end(tmp_path) -> None:
    """The Milestone 1 path: a real composition to a loadable clip."""
    from bolbox.format import parse_file
    from bolbox.grid import grid

    composition = parse_file("data/compositions/theka-tintal.txt", lexicon=_LEX)
    pattern = grid(composition, lexicon=_LEX)
    path = write(pattern, tmp_path / "theka.mid")

    reloaded = mido.MidiFile(str(path))
    note_ons = [m for m in reloaded.tracks[0] if m.type == "note_on"]
    assert len(note_ons) == len(pattern.events)
    assert sum(m.time for m in reloaded.tracks[0]) == 16 * PPQ
