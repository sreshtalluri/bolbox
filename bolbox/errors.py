"""Error types.

Every error carries enough information to point at the offending text. The design
principle throughout bolbox is that failures are loud and positional: a bad
composition file tells you the line, the column, and the substring that broke.
Silent fallbacks are a bug, not a convenience.
"""

from __future__ import annotations


class BolboxError(Exception):
    """Base for every bolbox error."""


class VocabError(BolboxError):
    """The stroke vocabulary file is malformed."""


class UnknownStrokeError(BolboxError):
    """One or more symbols are not in the canonical stroke vocabulary.

    Raised by ``Vocabulary.require``. Carries the offending names so callers can
    report all of them at once rather than one per run.
    """

    def __init__(self, unknown: list[str], source: str, known: list[str]) -> None:
        self.unknown = list(unknown)
        self.source = source
        self.known = list(known)
        names = ", ".join(repr(n) for n in self.unknown)
        super().__init__(
            f"{source}: unknown stroke(s) {names}. "
            f"Known strokes: {', '.join(self.known)}. "
            f"Add them to data/strokes.yaml or fix the spelling."
        )


class LexiconError(BolboxError):
    """The lexicon file is malformed or contradicts the stroke vocabulary."""


class TokenizeError(BolboxError):
    """A bol token could not be segmented into known surface forms.

    ``offending`` is the exact substring that failed to match, and ``offset`` is
    its index within ``token`` -- both so the caller can point at it precisely.
    """

    def __init__(self, token: str, offset: int, offending: str) -> None:
        self.token = token
        self.offset = offset
        self.offending = offending
        super().__init__(
            f"cannot segment {token!r} at offset {offset}: "
            f"no known bol starts at {offending!r}"
        )


class ParseError(BolboxError):
    """A composition file is malformed.

    Always carries line and column (both 1-based) so an editor can jump to it.
    """

    def __init__(self, message: str, line: int, column: int, text: str = "") -> None:
        self.message = message
        self.line = line
        self.column = column
        self.text = text
        location = f"line {line}, column {column}"
        detail = f": {text!r}" if text else ""
        super().__init__(f"{location}: {message}{detail}")


class RecordingError(BolboxError):
    """A recording could not be stored, found, or read."""
