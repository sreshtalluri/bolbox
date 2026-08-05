"""Composition tree -> `Pattern`. Where bols become strokes.

    Composition --flatten--> [PlacedBol] --grid--> Pattern
                             (bol-level,           (stroke-level,
                              exact spans)          exact positions)

TWO WAYS A BOL BECOMES STROKES

A *composite* (`dha` = ge + na, marked `simultaneous` in the lexicon) stacks all
of its strokes on one position. Downstream that is one MIDI tick with two
note-ons, and one opportunity for a kit to substitute a single recorded sample.

A *compound* (`tirakita` = te re ki ta) spreads its strokes evenly across the
span the bol was given. A `tirakita` occupying one matra puts strokes at 0, 1/4,
1/2 and 3/4 of it; the same bol inside `{2, dha tirakita}` gets half a matra and
its strokes land at 1/2, 5/8, 3/4 and 7/8. The subdivision is relative, so
nesting composes without special cases.

VELOCITY

Baseline 100. Sam takes +12, every matra inside a khali vibhag takes -20. An
explicit `!` or `.` in the composition OVERRIDES the positional default rather
than stacking with it -- so what you typed is what you get, and an accent on a
khali matra is an accent rather than a wash.
"""

from __future__ import annotations

from fractions import Fraction

from .format import Composition, PlacedBol
from .lexicon import Lexicon
from .pattern import MAX_VELOCITY, MIN_VELOCITY, Event, Pattern
from .tal import Tal

BASE_VELOCITY = 100
ACCENT_DELTA = 12
GHOST_DELTA = -20
SAM_DELTA = 12
KHALI_DELTA = -20


def grid(
    composition: Composition,
    lexicon: Lexicon | None = None,
    lay: float | None = None,
) -> Pattern:
    """Turn a parsed composition into the `Pattern` both renderers read.

    ``lay`` overrides the file's header, which is what the UI slider does. The
    file keeps its own tempo; playback is free to disagree without editing it.
    """
    lexicon = lexicon or Lexicon.load()
    placed = composition.flatten(lexicon)

    events: list[Event] = []
    for bol_placement in placed:
        events.extend(_expand(bol_placement, composition.tal, lexicon))

    return Pattern(
        events=tuple(events),
        tal=composition.tal.name,
        cycle_matras=composition.tal.matras,
        lay=lay if lay is not None else composition.lay,
        avartans=len(composition.avartans),
        title=composition.title,
    )


def _expand(placed: PlacedBol, tal: Tal, lexicon: Lexicon) -> list[Event]:
    bol = lexicon.resolve(placed.surface)
    velocity = _velocity(placed, tal)

    if bol.simultaneous:
        # One instant, several strokes. This is what makes a composite `dha`
        # reachable downstream: the events share a position AND a source_bol.
        return [
            Event(
                pos=placed.pos,
                stroke=stroke,
                velocity=velocity,
                source_bol=bol.name,
                bol_offset=index,
            )
            for index, stroke in enumerate(bol.strokes)
        ]

    share = placed.duration / len(bol.strokes)
    return [
        Event(
            pos=placed.pos + share * index,
            stroke=stroke,
            velocity=velocity,
            source_bol=bol.name,
            bol_offset=index,
        )
        for index, stroke in enumerate(bol.strokes)
    ]


def _velocity(placed: PlacedBol, tal: Tal) -> int:
    if placed.accent == "accent":
        return _clamp(BASE_VELOCITY + ACCENT_DELTA)
    if placed.accent == "ghost":
        return _clamp(BASE_VELOCITY + GHOST_DELTA)

    # Positional defaults apply only when the composition did not say otherwise,
    # and only to a bol sitting exactly on its matra -- a stroke partway through
    # a subdivided matra is not on sam even if its matra is.
    on_the_matra = placed.pos.denominator == 1
    if on_the_matra and tal.is_sam(placed.matra):
        return _clamp(BASE_VELOCITY + SAM_DELTA)
    if tal.is_khali(placed.matra):
        return _clamp(BASE_VELOCITY + KHALI_DELTA)
    return BASE_VELOCITY


def _clamp(velocity: int) -> int:
    return max(MIN_VELOCITY, min(MAX_VELOCITY, velocity))


def grid_text(
    text: str,
    lexicon: Lexicon | None = None,
    lay: float | None = None,
) -> Pattern:
    """Parse and grid in one step. The path the server endpoint takes."""
    from .format import parse

    lexicon = lexicon or Lexicon.load()
    return grid(parse(text, lexicon=lexicon), lexicon=lexicon, lay=lay)


def cycle_positions(pattern: Pattern) -> list[Fraction]:
    """Matra positions where each avartan begins. Useful for loop markers."""
    return [Fraction(i * pattern.cycle_matras) for i in range(pattern.avartans)]
