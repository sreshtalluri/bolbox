"""Labels, CTC targets, coverage and import.

The label stores what was recited; the CTC target is derived from it. These
tests pin the derivation, because it is the one place a lexicon change
silently changes every training target.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from bolbox.audio import encode_wav16, read_wav
from bolbox.dataset import (
    LabelError,
    coverage,
    ctc_targets,
    import_directory,
    manifest_rows,
    parse_label,
    unit_vocabulary,
)
from bolbox.lexicon import Lexicon
from bolbox.recordings import RecordingStore
from bolbox.vocab import Vocabulary


@pytest.fixture(scope="module")
def lexicon() -> Lexicon:
    return Lexicon.load(vocab=Vocabulary.load())


def tone(seconds: float = 0.5, rate: int = 16000) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    return encode_wav16(0.3 * np.sin(2 * np.pi * 220 * t), rate)


def test_units_are_the_non_compound_bols(lexicon: Lexicon) -> None:
    units = unit_vocabulary(lexicon)
    assert {"dha", "dhin", "din", "tha", "na", "te", "re", "ki", "ta"} <= set(units)
    for compound in ("tirakita", "takita", "kitataka", "takatira"):
        assert compound not in units


def test_compounds_expand_and_markup_is_dropped(lexicon: Lexicon) -> None:
    assert ctc_targets("dha tirakita dhin! | - na.", lexicon) == [
        "dha", "te", "re", "ki", "ta", "dhin", "na",
    ]


def test_a_variant_is_not_a_unit(lexicon: Lexicon) -> None:
    """The realization is not in the audio, so the model must never be asked for it."""
    assert ctc_targets("din din@full", lexicon) == ["din", "din"]


def test_tha_and_na_stay_distinct(lexicon: Lexicon) -> None:
    assert ctc_targets("tha na", lexicon) == ["tha", "na"]


def test_aliases_resolve_and_groups_flatten(lexicon: Lexicon) -> None:
    assert ctc_targets("trkt {2, ti ra} dhage", lexicon) == [
        "te", "re", "ki", "ta", "ti", "re", "dha", "ge",
    ]


def test_a_fragment_is_a_valid_label(lexicon: Lexicon) -> None:
    """A clip need not fill an avartan; a composition file must."""
    assert parse_label("dha dhin", lexicon).slots == 2


def test_slots_count_compound_strokes_but_not_simultaneous_ones(lexicon: Lexicon) -> None:
    assert parse_label("dha tirakita", lexicon).slots == 5


def test_unknown_bols_fail_with_a_column(lexicon: Lexicon) -> None:
    with pytest.raises(LabelError) as info:
        parse_label("dha traka", lexicon)
    assert info.value.token == "traka"
    assert info.value.column == 4


def test_unknown_variant_fails(lexicon: Lexicon) -> None:
    with pytest.raises(LabelError):
        parse_label("din@edge", lexicon)


def test_read_wav_handles_float_and_stereo() -> None:
    import struct
    x = np.array([[0.5, -0.5], [0.25, 0.25]], dtype="<f4")
    pcm = x.tobytes()
    head = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE",
                       b"fmt ", 16, 3, 2, 8000, 8000 * 8, 8, 32, b"data", len(pcm))
    samples, rate = read_wav(head + pcm)
    assert rate == 8000
    assert samples.tolist() == [0.0, 0.25]


def test_import_is_idempotent_and_takes_free_labels(tmp_path: Path, lexicon: Lexicon) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "a.wav").write_bytes(tone())
    (src / "a.txt").write_text("dha dhin dhin dha\n")
    (src / "b.wav").write_bytes(tone(0.6))
    (src / "c.wav").write_bytes(tone(0.7))
    (src / "c.txt").write_text("dha traka\n")  # does not tokenize
    (src / "junk.wav").write_bytes(b"RIFF....WAVEbroken")
    store = RecordingStore(tmp_path / "rec")

    first = import_directory(src, store, lexicon)
    assert len(first.imported) == 3
    assert [f[0] for f in first.failed] == ["junk.wav"]
    by_name = {m.source["name"]: m for m in first.imported}
    assert by_name["a.wav"].bols == "dha dhin dhin dha"
    assert by_name["b.wav"].bols == ""
    assert by_name["c.wav"].bols == "" and "traka" in by_name["c.wav"].notes
    assert by_name["b.wav"].duration_sec == pytest.approx(0.6, abs=0.01)

    again = import_directory(src, store, lexicon)
    assert again.imported == [] and len(again.duplicates) == 3


def test_coverage_and_manifest(tmp_path: Path, lexicon: Lexicon) -> None:
    store = RecordingStore(tmp_path)
    a = store.save(tone(), {"duration_sec": 0.5, "sample_rate": 16000, "bols": "dha tirakita"})
    store.save(tone(), {"duration_sec": 0.5, "sample_rate": 16000})
    s = store.save(tone(), {"duration_sec": 0.5, "sample_rate": 16000, "bols": "na"})
    store.update(s.id, {"skipped": True})

    cov = coverage(store, lexicon).to_dict(lexicon)
    assert (cov["takes"], cov["labelled"], cov["unlabelled"], cov["skipped"]) == (3, 1, 1, 1)
    assert cov["units"]["dha"] == 1 and cov["units"]["te"] == 1 and cov["units"]["na"] == 0
    assert cov["compounds"]["tirakita"] == 1

    rows = manifest_rows(store, lexicon)
    assert [r["id"] for r in rows] == [a.id]
    assert rows[0]["units"] == ["dha", "te", "re", "ki", "ta"]
    assert Path(rows[0]["wav"]).is_file()
