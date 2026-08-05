"""`Pattern` -- the single source of truth that both renderers read.

    composition text ---parse---> tree ---grid---> Pattern
    recited audio (v2) --align--------------------> Pattern
                                                      |
                            +-------------------------+-------------------------+
                            v                                                   v
                        midi.py                                        web/ scheduler
                 round to ticks at PPQ                          convert to seconds at lay
                 dha -> two note-ons                            dha -> one composite sample
                                                                       (if the kit has one)

WHY POSITIONS ARE RATIONAL, NOT SECONDS

Seconds are tempo-derived render data, not truth. Storing them means a tempo
change recomputes every event and re-accumulates float error, loop boundaries
stop landing exactly on sam, and "events sum to the cycle length" becomes a
tolerance you have to tune rather than an equality you can assert.

Rounding to a fixed MIDI PPQ has the same problem for odd tuplets. PPQ 1920
factors as 2^7 * 3 * 5, so it represents 3-, 5-, 6- and 8-way divisions exactly
and CANNOT represent a 7-way one -- which tisra and khand groupings need.

So positions are exact `Fraction` matras from sam, and rounding happens exactly
once, in whichever renderer is doing the rendering.

WHY EVENTS CARRY `source_bol`

Without it a composite `dha` is unreachable: by the time it is two strokes the
sampler cannot know it was ever a `dha`, so it fires `ge` and `na` separately
and a single recorded `dha` sample -- the thing that makes a tabla library sound
credible -- can never play. `source_bol` is what lets kit.py ask "do I have a
composite for this?" while midi.py independently emits two notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

MIN_VELOCITY = 1
MAX_VELOCITY = 127


@dataclass(frozen=True, order=True)
class Event:
    """One stroke at one exact position in the cycle.

    ``bol_offset`` is this stroke's index within the bol that produced it, so
    ``bol_offset == 0`` marks the stroke that starts a bol. Renderers need it to
    tell "one `tirakita`" from "four strokes that happen to be adjacent" --
    without it, MIDI stamps the word four times and a re-import reads four
    tirakitas where there was one.

    ``variant`` names the physical realization chosen for ``source_bol``, empty
    for the default. It is here rather than derivable from ``stroke`` because
    two realizations can share a stroke, and because a kit may later key a
    sample on `din@full` specifically.
    """

    pos: Fraction
    stroke: str = field(compare=False)
    velocity: int = field(default=100, compare=False)
    source_bol: str = field(default="", compare=False)
    bol_offset: int = field(default=0, compare=False)
    variant: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.pos, Fraction):
            raise TypeError(
                f"Event.pos must be a Fraction, got {type(self.pos).__name__}. "
                "Seconds and floats are render data; see the module docstring."
            )
        if self.pos < 0:
            raise ValueError(f"Event.pos must be >= 0, got {self.pos}")
        if not MIN_VELOCITY <= self.velocity <= MAX_VELOCITY:
            raise ValueError(
                f"velocity {self.velocity} outside {MIN_VELOCITY}..{MAX_VELOCITY}"
            )

    def seconds(self, lay: float) -> float:
        """Position in seconds at a given lay. A rendering step, not state."""
        return float(self.pos) * 60.0 / lay


@dataclass(frozen=True)
class Pattern:
    """A whole composition, positioned but not yet rendered.

    ``lay`` is in MATRAS PER MINUTE -- the tabla convention, not quarter notes.
    For tintal one matra is one quarter note, so the MIDI tempo meta equals lay
    directly; a tal with a different `matra_to_quarter` converts on the way out.
    """

    events: tuple[Event, ...]
    tal: str
    cycle_matras: int
    lay: float
    avartans: int = 1
    title: str = ""

    def __post_init__(self) -> None:
        if self.cycle_matras <= 0:
            raise ValueError("cycle_matras must be positive")
        if self.lay <= 0:
            raise ValueError("lay must be positive")
        if self.avartans <= 0:
            raise ValueError("avartans must be positive")
        object.__setattr__(self, "events", tuple(sorted(self.events)))

    # -- derived ------------------------------------------------------------

    @property
    def total_matras(self) -> Fraction:
        return Fraction(self.cycle_matras * self.avartans)

    @property
    def duration_seconds(self) -> float:
        return float(self.total_matras) * 60.0 / self.lay

    @property
    def strokes_used(self) -> list[str]:
        """Distinct strokes in first-appearance order. Used by the kit validator."""
        seen: dict[str, None] = {}
        for event in self.events:
            seen.setdefault(event.stroke, None)
        return list(seen)

    @property
    def bols_used(self) -> list[str]:
        seen: dict[str, None] = {}
        for event in self.events:
            if event.source_bol:
                seen.setdefault(event.source_bol, None)
        return list(seen)

    def simultaneous_groups(self) -> list[tuple[Fraction, tuple[Event, ...]]]:
        """Events bucketed by exact position.

        A composite `dha` appears here as two events at one position. Both
        renderers need this grouping: MIDI to emit one tick with two note-ons,
        the sampler to notice the group came from a single bol.
        """
        buckets: dict[Fraction, list[Event]] = {}
        for event in self.events:
            buckets.setdefault(event.pos, []).append(event)
        return [(pos, tuple(buckets[pos])) for pos in sorted(buckets)]

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        """JSON-safe form for the browser.

        Positions ship as exact ``[numerator, denominator]`` pairs. The client
        divides once, at scheduling time, and anchors each cycle from its index
        rather than accumulating -- so browser playback inherits the same
        no-drift property the Fraction representation buys here.
        """
        return {
            "tal": self.tal,
            "cycle_matras": self.cycle_matras,
            "lay": self.lay,
            "avartans": self.avartans,
            "title": self.title,
            "events": [
                {
                    "pos": [e.pos.numerator, e.pos.denominator],
                    "stroke": e.stroke,
                    "velocity": e.velocity,
                    "source_bol": e.source_bol,
                    "bol_offset": e.bol_offset,
                    "variant": e.variant,
                }
                for e in self.events
            ],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Pattern":
        events = tuple(
            Event(
                pos=Fraction(int(e["pos"][0]), int(e["pos"][1])),
                stroke=e["stroke"],
                velocity=int(e.get("velocity", 100)),
                source_bol=e.get("source_bol", ""),
                bol_offset=int(e.get("bol_offset", 0)),
                variant=str(e.get("variant") or ""),
            )
            for e in raw.get("events", [])
        )
        return cls(
            events=events,
            tal=raw["tal"],
            cycle_matras=int(raw["cycle_matras"]),
            lay=float(raw["lay"]),
            avartans=int(raw.get("avartans", 1)),
            title=raw.get("title", ""),
        )
