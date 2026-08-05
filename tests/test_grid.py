"""T5 -- bols become positioned strokes.

The two expansions that matter: a composite stacks on one instant, a compound
spreads across its span. Get either wrong and the rhythm is wrong in a way that
sounds like a transcription bug later, which is exactly the ambiguity the
silent-half-first strategy exists to prevent.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
import yaml

from bolbox.format import parse
from bolbox.grid import BASE_VELOCITY, grid, grid_text
from bolbox.lexicon import Lexicon
from bolbox.pattern import Pattern
from bolbox.vocab import Vocabulary

_LEX = Lexicon.load(vocab=Vocabulary.load())


def header(body: str, lay: float = 120) -> str:
    return f"tal: tintal\nlay: {lay:g}\n\n{body}\n"


def pattern_for(body: str, **kwargs) -> Pattern:
    return grid_text(header(body), lexicon=_LEX, **kwargs)


def sixteen(first: str, count: int = 1) -> str:
    """Pad `first` out to a full tintal avartan.

    `count` is how many ELEMENTS `first` is, which is not its word count:
    `{2, ti ra}` is three words but one element.
    """
    return first + " " + " ".join(["dha"] * (16 - count))


# -- composites: one instant, several strokes ------------------------------


def test_composite_stacks_on_one_position() -> None:
    pattern = pattern_for(sixteen("dha"))
    first = [e for e in pattern.events if e.pos == 0]
    assert {e.stroke for e in first} == {"ge", "na"}
    assert all(e.pos == Fraction(0) for e in first)
    assert all(e.source_bol == "dha" for e in first)


def test_composite_group_survives_as_a_group() -> None:
    """The sampler needs to see one group with one source_bol, not two strokes."""
    pattern = pattern_for(sixteen("dha"))
    pos, group = pattern.simultaneous_groups()[0]
    assert pos == Fraction(0)
    assert len(group) == 2
    assert len({e.source_bol for e in group}) == 1


def test_dhin_is_ge_plus_tin() -> None:
    pattern = pattern_for(sixteen("dhin"))
    assert {e.stroke for e in pattern.events if e.pos == 0} == {"ge", "tin"}


# -- compounds: spread across the span -------------------------------------


def test_compound_spreads_across_its_matra() -> None:
    pattern = pattern_for(sixteen("tirakita"))
    first = sorted(e for e in pattern.events if e.pos < 1)
    assert [e.pos for e in first] == [Fraction(i, 4) for i in range(4)]
    assert [e.stroke for e in first] == ["te", "re", "ki", "ta"]


def test_compound_subdivision_is_relative_to_its_span() -> None:
    """`tirakita` inside a half-matra group gets eighths, not quarters."""
    pattern = pattern_for(sixteen("{2, dha tirakita}"))
    inner = sorted(e for e in pattern.events if Fraction(1, 2) <= e.pos < 1)
    assert [e.pos for e in inner] == [
        Fraction(1, 2),
        Fraction(5, 8),
        Fraction(3, 4),
        Fraction(7, 8),
    ]


def test_seven_grouping_stays_exact_through_gridding() -> None:
    pattern = pattern_for(sixteen("{7, ta ki ta ta ki ta ka}"))
    inner = sorted(e for e in pattern.events if e.pos < 1)
    assert [e.pos for e in inner] == [Fraction(i, 7) for i in range(7)]


# -- velocity ---------------------------------------------------------------


def test_sam_is_accented_by_default() -> None:
    pattern = pattern_for(sixteen("na"))
    assert pattern.events[0].velocity == BASE_VELOCITY + 12


def test_khali_vibhag_is_quieter() -> None:
    """Tintal's third vibhag is khali: matras 8..11 drop."""
    pattern = pattern_for(" ".join(["na"] * 16))
    by_pos = {e.pos: e.velocity for e in pattern.events}
    assert by_pos[Fraction(8)] == BASE_VELOCITY - 20
    assert by_pos[Fraction(11)] == BASE_VELOCITY - 20
    assert by_pos[Fraction(12)] == BASE_VELOCITY


def test_explicit_accent_overrides_the_positional_default() -> None:
    """An accent on a khali matra is an accent, not a wash. It replaces, not stacks."""
    body = " ".join(["na"] * 8 + ["na!"] + ["na"] * 7)
    pattern = pattern_for(body)
    by_pos = {e.pos: e.velocity for e in pattern.events}
    assert by_pos[Fraction(8)] == BASE_VELOCITY + 12, "explicit accent wins over khali"


def test_ghost_note_overrides_sam() -> None:
    pattern = pattern_for(sixteen("na."))
    assert pattern.events[0].velocity == BASE_VELOCITY - 20


def test_velocity_stays_in_midi_range() -> None:
    pattern = pattern_for(" ".join(["na!"] * 16))
    assert all(1 <= e.velocity <= 127 for e in pattern.events)


# -- pattern shape ----------------------------------------------------------


def test_lay_override_does_not_touch_positions() -> None:
    """Tempo is a rendering concern. Changing it must not move an event."""
    slow = pattern_for(sixteen("tirakita"), lay=60)
    fast = pattern_for(sixteen("tirakita"), lay=240)
    assert [e.pos for e in slow.events] == [e.pos for e in fast.events]
    assert slow.duration_seconds == 4 * fast.duration_seconds


def test_multiple_avartans_are_positioned_absolutely() -> None:
    line = " ".join(["dha"] * 16)
    pattern = grid_text(header(f"{line}\n{line}"), lexicon=_LEX)
    assert pattern.avartans == 2
    assert pattern.total_matras == 32
    assert max(e.pos for e in pattern.events) == Fraction(31), "last matra of cycle 2"
    assert Fraction(16) in {e.pos for e in pattern.events}, "cycle 2 starts at matra 16"


def test_rests_produce_no_events() -> None:
    pattern = pattern_for(" ".join(["dha", "-"] * 8))
    assert len(pattern.events) == 8 * 2, "eight dha, two strokes each"


def test_events_are_sorted_by_position() -> None:
    pattern = pattern_for(sixteen("{2, dha tirakita}"))
    assert list(pattern.events) == sorted(pattern.events)


def test_strokes_used_reports_what_a_kit_must_cover() -> None:
    pattern = pattern_for(sixteen("dha tirakita", 2))
    assert set(pattern.strokes_used) >= {"ge", "na", "te", "re", "ki", "ta"}


# -- serialization round trip ----------------------------------------------


def test_pattern_survives_the_json_round_trip() -> None:
    """The browser gets `[numerator, denominator]` pairs, not floats."""
    original = pattern_for(sixteen("{7, ta ki ta ta ki ta ka} dha tirakita", 3))
    restored = Pattern.from_dict(original.to_dict())

    assert restored.events == original.events
    assert [e.pos for e in restored.events] == [e.pos for e in original.events]
    assert restored.lay == original.lay
    assert restored.cycle_matras == original.cycle_matras


def test_json_positions_are_exact_pairs_not_floats() -> None:
    pattern = pattern_for(sixteen("{7, ta ki ta ta ki ta ka}"))
    positions = [e["pos"] for e in pattern.to_dict()["events"]]
    assert all(isinstance(p, list) and len(p) == 2 for p in positions)
    assert any(p[1] == 7 for p in positions), "a seventh must survive as a seventh"


@pytest.mark.parametrize("body", ["dha", "tirakita", "{2, ti ra}", "-"])
def test_gridding_never_loses_the_cycle(body: str) -> None:
    pattern = pattern_for(sixteen(body))
    assert pattern.total_matras == 16
    assert all(0 <= e.pos < 16 for e in pattern.events)


# -- variants -----------------------------------------------------------


def test_variant_selects_the_strokes_and_reaches_the_event() -> None:
    comp = parse(
        "tal: tintal\nlay: 120\n\n"
        "din din@full - - | - - - - | - - - - | - - - -\n"
    )
    pattern = grid(comp)
    default, chosen = pattern.events[0], pattern.events[1]

    assert default.source_bol == "din" and default.variant == ""
    assert default.stroke == "na"          # the default realization

    assert chosen.source_bol == "din" and chosen.variant == "full"
    assert chosen.stroke == "ta"           # the selected one


def test_variant_survives_the_dict_round_trip() -> None:
    comp = parse(
        "tal: tintal\nlay: 120\n\n"
        "din@full - - - | - - - - | - - - - | - - - -\n"
    )
    pattern = grid(comp)
    assert pattern.to_dict()["events"][0]["variant"] == "full"
    assert Pattern.from_dict(pattern.to_dict()) == pattern


def test_events_without_a_variant_key_still_load() -> None:
    """Patterns stored before variants existed must not fail to load."""
    payload = grid(parse(
        "tal: tintal\nlay: 120\n\ndha - - - | - - - - | - - - - | - - - -\n"
    )).to_dict()
    for event in payload["events"]:
        del event["variant"]
    assert Pattern.from_dict(payload).events[0].variant == ""


def test_json_null_variant_loads_as_empty_not_the_string_none() -> None:
    """`str(e.get("variant", ""))` turns a JSON `null` into the string "None",
    which would later render as `din@None` in the grid. `null` must mean "no
    variant chosen", same as a missing key.
    """
    payload = grid(parse(
        "tal: tintal\nlay: 120\n\ndha - - - | - - - - | - - - - | - - - -\n"
    )).to_dict()
    for event in payload["events"]:
        event["variant"] = None
    assert Pattern.from_dict(payload).events[0].variant == ""


_MULTI_STROKE_VARIANT_YAML = """
version: 1
bols:
  x:
    variants:
      one: { strokes: [ge], default: true }
      big: { strokes: [te, re, ki] }
"""


def test_multi_stroke_variant_subdivides_its_own_slot_count() -> None:
    """A variant can change the STROKE COUNT, not just which stroke fires.

    `_expand` divides the bol's share by `len(realization.strokes)`. If it
    divided by the DEFAULT realization's stroke count (one) instead of the
    selected one (three), every event here would land on the same position
    instead of subdividing the matra into thirds.
    """
    lex = Lexicon.from_dict(
        yaml.safe_load(_MULTI_STROKE_VARIANT_YAML), Vocabulary.load(), source="<test>"
    )
    comp = parse(
        "tal: tintal\nlay: 120\n\n"
        "x@big - - - | - - - - | - - - - | - - - -\n",
        lexicon=lex,
    )
    pattern = grid(comp, lexicon=lex)
    events = sorted(e for e in pattern.events if e.pos < 1)

    assert [e.pos for e in events] == [Fraction(0, 3), Fraction(1, 3), Fraction(2, 3)]
    assert [e.stroke for e in events] == ["te", "re", "ki"]
    assert [e.bol_offset for e in events] == [0, 1, 2]
    assert all(e.source_bol == "x" for e in events)
    assert all(e.variant == "big" for e in events)
