"""The CLI. Thin, but it is the fastest path from a file to a sound.

`check` is the one that earns its keep: it validates a composition without
producing anything, which is what you want while typing a corpus and what CI
should run over data/compositions/.
"""

from __future__ import annotations

import mido
import pytest

from bolbox.cli import main

THEKA = "data/compositions/theka-tintal.txt"


def test_check_passes_on_the_shipped_files(capsys) -> None:
    assert main(["check", THEKA, "data/compositions/demo-format-features.txt"]) == 0
    out = capsys.readouterr().out
    assert "ok" in out
    assert "tintal" in out


def test_check_fails_loudly_with_a_position(tmp_path, capsys) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text("tal: tintal\nlay: 120\n\ndha dha dhaXYZ " + "dha " * 13 + "\n")

    assert main(["check", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "line 4" in err
    assert "dhaXYZ" in err


def test_check_reports_every_bad_file_not_just_the_first(tmp_path, capsys) -> None:
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("tal: tintal\n\ndha dha\n")

    assert main(["check", str(tmp_path / "a.txt"), str(tmp_path / "b.txt")]) == 1
    assert capsys.readouterr().err.count("FAIL") == 2


def test_render_writes_a_loadable_midi_file(tmp_path) -> None:
    out = tmp_path / "theka.mid"
    assert main(["render", THEKA, "-o", str(out)]) == 0
    assert out.exists()

    reloaded = mido.MidiFile(str(out))
    assert any(m.type == "note_on" for m in reloaded.tracks[0])


def test_render_lay_override_changes_duration(tmp_path) -> None:
    slow = tmp_path / "slow.mid"
    fast = tmp_path / "fast.mid"
    main(["render", THEKA, "-o", str(slow), "--lay", "60"])
    main(["render", THEKA, "-o", str(fast), "--lay", "240"])

    assert mido.MidiFile(str(slow)).length == pytest.approx(
        mido.MidiFile(str(fast)).length * 4, rel=0.01
    )


def test_render_defaults_the_output_path(tmp_path) -> None:
    source = tmp_path / "piece.txt"
    source.write_text("tal: tintal\nlay: 120\n\n" + "dha " * 16 + "\n")

    assert main(["render", str(source)]) == 0
    assert (tmp_path / "piece.mid").exists()


def test_show_prints_the_grid(capsys) -> None:
    assert main(["show", THEKA]) == 0
    out = capsys.readouterr().out
    assert "tintal" in out
    assert "ge+na" in out, "a composite prints as its stacked strokes"
    assert "dha" in out


def test_show_marks_positions_off_the_matra(capsys) -> None:
    """A compound's inner strokes are not on a matra and must not look like they are."""
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "t.txt"
        path.write_text("tal: tintal\nlay: 120\n\ntirakita " + "dha " * 15 + "\n")
        assert main(["show", str(path)]) == 0

    out = capsys.readouterr().out
    assert "+1/4" in out, "off-matra positions print their exact fraction"
