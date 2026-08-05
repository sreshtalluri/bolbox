"""`Pattern` -> a .mid file. One of the two independent renderers.

This module never talks to the sampler and the sampler never reads its output.
Both read `Pattern`. That separation is what makes a composite `dha` possible:
here it becomes two note-ons on one tick, while the sampler independently fires
a single recorded sample for the same event group.

THE ONE PLACE ROUNDING HAPPENS

`Pattern` positions are exact `Fraction` matras. MIDI needs integer ticks, so
this is where the exactness ends -- once, at the boundary, deliberately.

PPQ 1920 factors as 2^7 * 3 * 5, so it represents 3-, 5-, 6- and 8-way
divisions of a beat exactly. It CANNOT represent a 7-way one: a `{7, ...}`
group rounds to the nearest tick, at most 0.26 ms of error at 120 matras/min.
That is inaudible and, more importantly, it does not accumulate -- every
position is computed from the start of the pattern rather than by adding
deltas, so the thousandth cycle is as accurate as the first.

WHY THE TEXT META EVENTS

`dha` leaves here as two note-ons at the same tick, which is indistinguishable
from a `ge` and a `na` that happen to coincide. A text meta event per bol keeps
the word, so the file round-trips and practice mode (v2) can compare against a
target transcript without guessing. Most DAWs drop these on clip import; the
value is in the .mid file itself.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Protocol

import mido

from .errors import BolboxError
from .pattern import Pattern
from .tal import get_tal

PPQ = 1920
DRUM_CHANNEL = 9  # channel 10 in 1-based DAW numbering: the percussion channel
GATE_TICKS = PPQ // 8  # a 32nd note. One-shots ignore length; this is for DAWs.


class KitLike(Protocol):
    """The slice of a kit this module needs. Keeps midi.py free of kit.py."""

    def midi_override(self, stroke: str) -> int | None: ...


class MidiMapError(BolboxError):
    def __init__(self, stroke: str, known: list[str]) -> None:
        super().__init__(
            f"no MIDI note for stroke {stroke!r}. "
            f"Add it to CANONICAL_NOTE_MAP in bolbox/midi.py, or give the kit a "
            f"`midi_map` override. Mapped strokes: {', '.join(known)}."
        )


# Custom, contiguous from 36. Not General MIDI -- GM has no tabla slots, and
# inventing a mapping onto congas and bongos would put strokes on drums whose
# names actively mislead. Contiguous means a DAW drum rack maps in one drag.
#
# Kits may override any of these per stroke via `midi_map` in kit.json, which is
# how a bol-to-909 kit works without a code change.
CANONICAL_NOTE_MAP: dict[str, int] = {
    # bayan
    "ge": 36,
    "ka": 37,
    "ki": 38,
    # dayan
    "na": 40,
    "ta": 41,
    "tin": 42,
    "tun": 43,
    "te": 44,
    "ti": 45,
    "re": 46,
}


def note_for(stroke: str, kit: KitLike | None = None) -> int:
    """Resolve a stroke to a MIDI note. Kit override wins over the default."""
    if kit is not None:
        override = kit.midi_override(stroke)
        if override is not None:
            return override
    try:
        return CANONICAL_NOTE_MAP[stroke]
    except KeyError:
        raise MidiMapError(stroke, sorted(CANONICAL_NOTE_MAP)) from None


def ticks_for(pos: Fraction, matra_to_quarter: Fraction) -> int:
    """Exact matra position -> integer tick. The single rounding boundary."""
    exact = pos * matra_to_quarter * PPQ
    return int(exact) if exact.denominator == 1 else round(float(exact))


def build(pattern: Pattern, kit: KitLike | None = None) -> mido.MidiFile:
    """Render a Pattern to an in-memory MidiFile."""
    tal = get_tal(pattern.tal)
    midi = mido.MidiFile(ticks_per_beat=PPQ)
    track = mido.MidiTrack()
    midi.tracks.append(track)

    # Tempo is per QUARTER NOTE; lay is per MATRA. For tintal one matra is one
    # quarter so they coincide, but the conversion is written out rather than
    # assumed so a tal with a different matra does not silently play wrong.
    quarters_per_minute = pattern.lay * float(tal.matra_to_quarter)
    numerator, denominator = tal.midi_time_signature

    absolute: list[tuple[int, int, mido.Message | mido.MetaMessage]] = []

    def emit(tick: int, order: int, message) -> None:
        absolute.append((tick, order, message))

    emit(0, 0, mido.MetaMessage("track_name", name=pattern.title or "bolbox"))
    emit(0, 0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(quarters_per_minute)))
    emit(
        0,
        0,
        mido.MetaMessage(
            "time_signature", numerator=numerator, denominator=denominator
        ),
    )

    for pos, group in pattern.simultaneous_groups():
        tick = ticks_for(pos, tal.matra_to_quarter)

        # One text event per BOL, not per stroke and not per position. A
        # composite `dha` is one word across two notes; a compound `tirakita` is
        # one word across four positions. `bol_offset == 0` is the stroke that
        # starts a bol, so keying on it stamps each word exactly once.
        for bol in dict.fromkeys(
            e.source_bol for e in group if e.source_bol and e.bol_offset == 0
        ):
            emit(tick, 0, mido.MetaMessage("text", text=bol))

        for event in group:
            note = note_for(event.stroke, kit)
            emit(
                tick,
                1,
                mido.Message(
                    "note_on",
                    note=note,
                    velocity=event.velocity,
                    channel=DRUM_CHANNEL,
                ),
            )
            emit(
                tick + GATE_TICKS,
                2,
                mido.Message(
                    "note_off", note=note, velocity=0, channel=DRUM_CHANNEL
                ),
            )

    # End of track on the cycle boundary, so a DAW loops the full tal rather
    # than stopping at the last stroke.
    end_tick = ticks_for(pattern.total_matras, tal.matra_to_quarter)
    emit(end_tick, 3, mido.MetaMessage("end_of_track"))

    absolute.sort(key=lambda item: (item[0], item[1]))

    previous = 0
    for tick, _order, message in absolute:
        message.time = tick - previous
        previous = tick
        track.append(message)

    return midi


def write(pattern: Pattern, path: Path | str, kit: KitLike | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    build(pattern, kit).save(str(path))
    return path


def to_bytes(pattern: Pattern, kit: KitLike | None = None) -> bytes:
    """Serialize without touching disk. What the server hands the browser."""
    import io

    buffer = io.BytesIO()
    build(pattern, kit).save(file=buffer)
    return buffer.getvalue()
