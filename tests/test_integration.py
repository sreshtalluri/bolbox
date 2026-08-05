"""The seams between the halves. No single module owns these.

Every other test file checks one component against its own contract. These check
that the components still agree with each other -- which is where a project with
four data files and two renderers actually breaks.

The one that matters most: a `Pattern` that a real kit cannot play. That failure
does not raise anywhere. It is silence, and silence reads as a sequencing bug.
"""

from __future__ import annotations

import io
from pathlib import Path

import mido
import pytest

from bolbox.format import parse_file
from bolbox.grid import grid, grid_text
from bolbox.kit import Kit
from bolbox.lexicon import Lexicon
from bolbox.midi import CANONICAL_NOTE_MAP, build, note_for
from bolbox.vocab import Vocabulary

REPO_ROOT = Path(__file__).resolve().parent.parent
KITS_DIR = REPO_ROOT / "kits"
COMPOSITIONS = REPO_ROOT / "data" / "compositions"

_VOCAB = Vocabulary.load()
_LEX = Lexicon.load(vocab=_VOCAB)


def kit_dirs() -> list[Path]:
    if not KITS_DIR.is_dir():
        return []
    return sorted(p for p in KITS_DIR.iterdir() if (p / "kit.json").is_file())


def composition_files() -> list[Path]:
    return sorted(COMPOSITIONS.glob("*.txt"))


# -- the four data files agree ---------------------------------------------


def test_every_lexicon_stroke_exists_in_the_vocabulary() -> None:
    for bol in _LEX:
        _VOCAB.require(bol.strokes, source=f"lexicon bol {bol.name!r}")


def test_every_vocabulary_stroke_has_a_midi_note() -> None:
    for stroke in _VOCAB.names:
        assert note_for(stroke) in range(128), stroke


def test_the_note_map_has_no_strokes_the_vocabulary_lacks() -> None:
    """A note mapped to a stroke that no longer exists is dead config."""
    _VOCAB.require(CANONICAL_NOTE_MAP.keys(), source="CANONICAL_NOTE_MAP")


@pytest.mark.parametrize("kit_dir", kit_dirs(), ids=lambda p: p.name)
def test_every_kit_covers_the_whole_vocabulary(kit_dir: Path) -> None:
    """The silent-dropout guard, applied to every kit that ships.

    A kit that resolves every stroke cannot play silence for a stroke a
    composition uses. That is the property; this asserts it kit by kit.
    """
    kit = Kit.load(kit_dir, vocab=_VOCAB, lexicon=_LEX)
    assert _VOCAB.missing_from(kit.stroke_names) == []


@pytest.mark.parametrize("kit_dir", kit_dirs(), ids=lambda p: p.name)
def test_every_kit_composite_is_a_real_composite_bol(kit_dir: Path) -> None:
    kit = Kit.load(kit_dir, vocab=_VOCAB, lexicon=_LEX)
    for name in kit.composite_names:
        bol = _LEX.resolve(name)
        assert bol.simultaneous, f"{name} is not a composite bol"


# -- every shipped composition survives the whole pipeline -----------------


@pytest.mark.parametrize("path", composition_files(), ids=lambda p: p.name)
def test_composition_parses_grids_and_renders(path: Path) -> None:
    composition = parse_file(path, lexicon=_LEX)
    pattern = grid(composition, lexicon=_LEX)

    assert pattern.events, f"{path.name} produced no strokes"
    assert pattern.total_matras == composition.tal.matras * len(composition.avartans)

    midi = build(pattern)
    note_ons = [m for m in midi.tracks[0] if m.type == "note_on"]
    assert len(note_ons) == len(pattern.events)


@pytest.mark.parametrize("path", composition_files(), ids=lambda p: p.name)
@pytest.mark.parametrize("kit_dir", kit_dirs(), ids=lambda p: p.name)
def test_every_kit_can_play_every_composition(path: Path, kit_dir: Path) -> None:
    """The seam that matters: a real pattern against a real kit.

    Nothing else checks this. `grid` does not know about kits and `kit` does not
    know about compositions, so a stroke that a composition uses and a kit lacks
    would only show up as a gap you hear.
    """
    kit = Kit.load(kit_dir, vocab=_VOCAB, lexicon=_LEX)
    pattern = grid(parse_file(path, lexicon=_LEX), lexicon=_LEX)

    for stroke in pattern.strokes_used:
        assert kit.resolve_stroke(stroke) is not None, (
            f"{kit_dir.name} cannot play {stroke!r} from {path.name}"
        )


@pytest.mark.parametrize("kit_dir", kit_dirs(), ids=lambda p: p.name)
def test_composites_reachable_from_a_real_pattern(kit_dir: Path) -> None:
    """`dha` must arrive at the kit as a word, not as two anonymous strokes.

    This is the whole reason `Pattern` carries `source_bol`. If it regresses,
    every kit's recorded `dha` becomes unreachable and the tool quietly starts
    sounding like a two-sample approximation.
    """
    kit = Kit.load(kit_dir, vocab=_VOCAB, lexicon=_LEX)
    if not kit.composite_names:
        pytest.skip(f"{kit_dir.name} has no composites")

    pattern = grid(parse_file(COMPOSITIONS / "theka-tintal.txt", lexicon=_LEX), lexicon=_LEX)

    hits = [
        event
        for event in pattern.events
        if event.bol_offset == 0 and kit.resolve_composite(event.source_bol)
    ]
    assert hits, "no composite in the theka resolved against the kit"
    assert all(event.source_bol == "dha" for event in hits[:1])


# -- the renderers stay independent ----------------------------------------


def test_midi_and_kit_read_the_pattern_not_each_other() -> None:
    """Neither renderer may depend on the other's output.

    If `kit.py` ever grew a MIDI import, or `midi.py` a kit import beyond the
    narrow override protocol, a composite `dha` would become unrepresentable
    again -- the exact regression the `Pattern` intermediate exists to prevent.
    """
    kit_source = (REPO_ROOT / "bolbox" / "kit.py").read_text()
    midi_source = (REPO_ROOT / "bolbox" / "midi.py").read_text()

    assert "import mido" not in kit_source
    assert "from .midi" not in kit_source and "from bolbox.midi" not in kit_source
    assert "from .kit" not in midi_source and "from bolbox.kit" not in midi_source


def test_kit_midi_override_flows_through_the_renderer() -> None:
    """The bol-to-909 path: a kit changes note numbers with no code change."""
    kits = kit_dirs()
    if not kits:
        pytest.skip("no kits")

    kit = Kit.load(kits[0], vocab=_VOCAB, lexicon=_LEX)
    pattern = grid_text(
        "tal: tintal\nlay: 120\n\n" + " ".join(["dha"] * 16), lexicon=_LEX
    )

    rendered = build(pattern, kit)
    notes = {m.note for m in rendered.tracks[0] if m.type == "note_on"}

    for stroke in ("ge", "na"):
        expected = kit.midi_override(stroke) or CANONICAL_NOTE_MAP[stroke]
        assert expected in notes, f"{stroke} did not render at note {expected}"


# -- the full Milestone 1 path ---------------------------------------------


def test_milestone_one_round_trip(tmp_path: Path) -> None:
    """Type a composition, render it, reload it, and check it loops.

    The design doc's pass criterion for Milestone 1 is a tintal kaida that
    round-trips to a DAW and loops without hand-editing. Loading is as close as
    a test gets to that; the tempo and time-signature meta are what make the
    loop work, so both are asserted rather than assumed.
    """
    composition = parse_file(COMPOSITIONS / "theka-tintal.txt", lexicon=_LEX)
    pattern = grid(composition, lexicon=_LEX)

    buffer = io.BytesIO()
    build(pattern).save(file=buffer)
    reloaded = mido.MidiFile(file=io.BytesIO(buffer.getvalue()))

    kinds = {m.type for m in reloaded.tracks[0]}
    assert {"set_tempo", "time_signature", "note_on", "note_off"} <= kinds

    total_ticks = sum(m.time for m in reloaded.tracks[0])
    assert total_ticks == 16 * reloaded.ticks_per_beat, "must end on the cycle, not the last stroke"

    texts = [m.text for m in reloaded.tracks[0] if m.type == "text"]
    assert texts.count("dha") + texts.count("dhin") + texts.count("tin") + texts.count("ta") == 16
