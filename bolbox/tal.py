"""Tal definitions -- the metric cycles compositions are written in.

v1 supports tintal only. The `tal:` header is still REQUIRED in every
composition file so that adding jhaptal, rupak or ektal later is a table entry
rather than a hand-edit of every file you have typed.

A tal is not a time signature. Tintal is 16 matras in four vibhags with sam on
matra 0 and khali on the third vibhag; 4/4 is only how it gets *rendered* into
MIDI. `matra_to_quarter` keeps those two ideas separate so a tal whose matra is
not a quarter note does not need the domain model changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .errors import BolboxError


class UnknownTalError(BolboxError):
    def __init__(self, name: str, supported: list[str]) -> None:
        self.name = name
        self.supported = supported
        super().__init__(
            f"unknown or unsupported tal {name!r}. "
            f"v1 supports: {', '.join(supported)}."
        )


@dataclass(frozen=True)
class Tal:
    name: str
    matras: int
    vibhags: tuple[int, ...]
    khali_vibhags: frozenset[int]
    matra_to_quarter: Fraction = Fraction(1)
    description: str = ""

    def __post_init__(self) -> None:
        if sum(self.vibhags) != self.matras:
            raise ValueError(
                f"{self.name}: vibhags {self.vibhags} sum to {sum(self.vibhags)}, "
                f"expected {self.matras}"
            )
        if any(v >= len(self.vibhags) for v in self.khali_vibhags):
            raise ValueError(f"{self.name}: khali vibhag index out of range")

    @property
    def vibhag_starts(self) -> tuple[int, ...]:
        """Matra index each vibhag begins on. First is sam."""
        starts, running = [], 0
        for width in self.vibhags:
            starts.append(running)
            running += width
        return tuple(starts)

    @property
    def khali_matras(self) -> frozenset[int]:
        """Every matra inside a khali vibhag. Drives the velocity default."""
        out: set[int] = set()
        for index in self.khali_vibhags:
            start = self.vibhag_starts[index]
            out.update(range(start, start + self.vibhags[index]))
        return frozenset(out)

    def is_sam(self, matra: int) -> bool:
        return matra % self.matras == 0

    def is_khali(self, matra: int) -> bool:
        return (matra % self.matras) in self.khali_matras

    @property
    def midi_time_signature(self) -> tuple[int, int]:
        """How the cycle is written into MIDI so a DAW loops it correctly."""
        quarters = Fraction(self.matras) * self.matra_to_quarter
        if quarters.denominator == 1:
            return (int(quarters), 4)
        # Fall back to eighth-note denominator for tals whose cycle is not a
        # whole number of quarters. No v1 tal needs this, but the rule is stated
        # rather than left to be discovered.
        eighths = quarters * 2
        if eighths.denominator != 1:
            raise ValueError(
                f"{self.name}: cycle of {quarters} quarters has no clean "
                f"MIDI time signature; give it an explicit one"
            )
        return (int(eighths), 8)


TINTAL = Tal(
    name="tintal",
    matras=16,
    vibhags=(4, 4, 4, 4),
    khali_vibhags=frozenset({2}),
    matra_to_quarter=Fraction(1),
    description="16 matras in four vibhags. Sam on 1, khali on 9. The common one.",
)

# v1 table. Adding an entry here is the entire cost of supporting a new tal,
# because every composition file already declares which tal it is in.
TALS: dict[str, Tal] = {
    TINTAL.name: TINTAL,
}


def get_tal(name: str) -> Tal:
    key = name.strip().lower()
    if key not in TALS:
        raise UnknownTalError(name, sorted(TALS))
    return TALS[key]
