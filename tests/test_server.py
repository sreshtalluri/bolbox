"""The local server: patterns and MIDI in, no audio.

The endpoint contract matters more than usual here because the browser is the
only audio renderer. If `/api/pattern` ever started returning seconds, or the
server started rendering WAVs, playback and export would stop being the same
code path -- which is the whole reason the split is drawn where it is.
"""

from __future__ import annotations

import io

import mido
import pytest
from fastapi.testclient import TestClient

from bolbox.server import app

client = TestClient(app)

THEKA = (
    "tal: tintal\nlay: 120\n\n"
    "dha dhin dhin dha | dha dhin dhin dha | dha tin tin ta | ta dhin dhin dha\n"
)


# -- /api/pattern -----------------------------------------------------------


def test_pattern_round_trips_a_composition() -> None:
    response = client.post("/api/pattern", json={"text": THEKA})
    assert response.status_code == 200

    body = response.json()
    assert body["tal"] == "tintal"
    assert body["cycle_matras"] == 16
    assert body["lay"] == 120
    assert len(body["events"]) == 28, "16 bols, 12 of them composite"


def test_positions_ship_as_exact_pairs_never_seconds() -> None:
    """A float here would quietly reintroduce the drift the design avoids."""
    body = client.post(
        "/api/pattern",
        json={"text": "tal: tintal\nlay: 120\n\n{7, ta ki ta ta ki ta ka} " + "dha " * 15},
    ).json()

    positions = [e["pos"] for e in body["events"]]
    assert all(isinstance(p, list) and len(p) == 2 for p in positions)
    assert all(isinstance(n, int) for p in positions for n in p)
    assert any(p[1] == 7 for p in positions), "a seventh survives as a seventh"


def test_lay_override_changes_tempo_but_not_positions() -> None:
    slow = client.post("/api/pattern", json={"text": THEKA, "lay": 60}).json()
    fast = client.post("/api/pattern", json={"text": THEKA, "lay": 240}).json()

    assert slow["lay"] == 60 and fast["lay"] == 240
    assert [e["pos"] for e in slow["events"]] == [e["pos"] for e in fast["events"]]


def test_composite_events_share_a_position_and_a_bol() -> None:
    body = client.post("/api/pattern", json={"text": THEKA}).json()
    first = [e for e in body["events"] if e["pos"] == [0, 1]]
    assert len(first) == 2
    assert {e["source_bol"] for e in first} == {"dha"}
    assert [e["bol_offset"] for e in first] == [0, 1]


# -- errors carry a position ------------------------------------------------


def test_parse_error_returns_line_and_column() -> None:
    """The UI points at the mistake, so the payload has to carry where it is."""
    response = client.post(
        "/api/pattern",
        json={"text": "tal: tintal\nlay: 120\n\ndha dha dhaXYZ " + "dha " * 13},
    )
    assert response.status_code == 422

    body = response.json()
    assert body["line"] == 4
    assert body["column"] > 1
    assert "no known bol starts at" in body["error"]
    assert body["text"] == "dhaXYZ"


def test_wrong_matra_count_is_reported() -> None:
    response = client.post(
        "/api/pattern", json={"text": "tal: tintal\nlay: 120\n\ndha dha dha"}
    )
    assert response.status_code == 422
    assert "expected 16 matras" in response.json()["error"]


def test_missing_tal_header_is_reported() -> None:
    response = client.post("/api/pattern", json={"text": "lay: 120\n\n" + "dha " * 16})
    assert response.status_code == 422
    assert "tal" in response.json()["error"]


def test_unsupported_tal_names_what_is_supported() -> None:
    response = client.post(
        "/api/pattern", json={"text": "tal: jhaptal\nlay: 120\n\n" + "dha " * 16}
    )
    assert response.status_code == 422
    assert "tintal" in response.json()["error"]


# -- /api/midi --------------------------------------------------------------


def test_midi_endpoint_returns_a_loadable_file() -> None:
    response = client.post("/api/midi", json={"text": THEKA})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/midi"
    assert "attachment" in response.headers["content-disposition"]

    reloaded = mido.MidiFile(file=io.BytesIO(response.content))
    assert reloaded.ticks_per_beat == 1920
    assert sum(1 for m in reloaded.tracks[0] if m.type == "note_on") == 28


def test_midi_carries_tempo_and_time_signature() -> None:
    """Without both, the clip does not loop in a DAW -- Milestone 1's criterion."""
    response = client.post("/api/midi", json={"text": THEKA})
    track = mido.MidiFile(file=io.BytesIO(response.content)).tracks[0]
    kinds = {m.type for m in track}
    assert "set_tempo" in kinds
    assert "time_signature" in kinds


# -- discovery endpoints ----------------------------------------------------


def test_vocabulary_exposes_strokes_bols_and_tals() -> None:
    body = client.get("/api/vocabulary").json()
    assert any(s["name"] == "ge" for s in body["strokes"])
    assert any(b["name"] == "dha" and b["simultaneous"] for b in body["bols"])
    assert "trkt" in body["surface_forms"], "aliases must be discoverable by the UI"
    assert any(t["name"] == "tintal" and t["matras"] == 16 for t in body["tals"])


def test_compositions_are_listed_and_readable() -> None:
    listing = client.get("/api/compositions").json()["compositions"]
    assert "theka-tintal.txt" in listing

    body = client.get("/api/compositions/theka-tintal.txt").text
    assert "tal: tintal" in body


@pytest.mark.parametrize("name", ["../pyproject.toml", "..%2Fpyproject.toml"])
def test_composition_reads_cannot_escape_the_directory(name: str) -> None:
    """A URL path is untrusted input, `..` included."""
    response = client.get(f"/api/compositions/{name}")
    assert response.status_code == 404


def test_kits_endpoint_responds_even_with_no_kits() -> None:
    response = client.get("/api/kits")
    assert response.status_code == 200
    assert isinstance(response.json()["kits"], list)


# -- the boundary this split exists to hold --------------------------------


def test_server_exposes_no_audio_rendering_endpoint() -> None:
    """Audio is the browser's job, so that export and playback cannot diverge.

    If a `/api/render` or `/api/wav` ever appears here, there are two sample
    engines again and the WAV you download stops being the thing you heard.
    """
    paths = {route.path for route in app.routes}
    assert not any("wav" in p or "render" in p or "audio" in p for p in paths)


# -- the default kit is explicit, not accidental ---------------------------


def test_default_kit_is_named_not_inferred_from_sort_order() -> None:
    """It was previously "whichever directory sorts first", which is invisible
    in the code and would break silently the first time a kit is renamed."""
    body = client.get("/api/kits").json()
    assert body["default"] == "deolekar-tabla"
    assert body["kits"][0] == body["default"], "list order agrees with the field"


def test_default_kit_actually_exists_on_disk() -> None:
    from bolbox.server import KITS_DIR

    body = client.get("/api/kits").json()
    assert (KITS_DIR / body["default"] / "kit.json").is_file()


def test_every_listed_kit_loads() -> None:
    """A kit the API advertises but that will not load is worse than one hidden."""
    from bolbox.kit import Kit
    from bolbox.server import KITS_DIR, _LEXICON, _VOCAB

    for name in client.get("/api/kits").json()["kits"]:
        Kit.load(KITS_DIR / name, vocab=_VOCAB, lexicon=_LEXICON)


def test_vocabulary_exposes_variants() -> None:
    body = client.get("/api/vocabulary").json()
    din = next(b for b in body["bols"] if b["name"] == "din")
    assert [v["name"] for v in din["variants"]] == ["kinar", "full"]
    assert din["strokes"] == din["variants"][0]["strokes"]  # default first

    # A client that does not care about variants reads what it read before.
    ge = next(b for b in body["bols"] if b["name"] == "ge")
    assert len(ge["variants"]) == 1
    assert ge["variants"][0]["name"] == ""
    assert ge["strokes"] == ["ge"]


def test_vocabulary_lists_tha_and_na_separately() -> None:
    names = [b["name"] for b in client.get("/api/vocabulary").json()["bols"]]
    assert "tha" in names and "na" in names


# -- recordings and labeling ------------------------------------------------

import json as _json

import numpy as _np

from bolbox import server as _server
from bolbox.audio import encode_wav16
from bolbox.recordings import RecordingStore


@pytest.fixture
def recordings(tmp_path, monkeypatch) -> RecordingStore:
    store = RecordingStore(tmp_path / "recordings")
    monkeypatch.setattr(_server, "_RECORDINGS", store)
    return store


def _wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    rng = _np.random.default_rng(0)
    x = rng.normal(0, 0.001, int(seconds * rate))
    for t in (0.2, 0.5, 0.8):
        i = int(t * rate)
        n = int(0.05 * rate)
        x[i : i + n] += 0.4 * _np.sin(_np.arange(n) * 0.2) * _np.exp(-_np.arange(n) / (0.01 * rate))
    return encode_wav16(x, rate)


def _post(bols: str = "") -> dict:
    res = client.post(
        "/api/recordings",
        files={"audio": ("take.wav", io.BytesIO(_wav()), "audio/wav")},
        data={"meta": _json.dumps({"duration_sec": 1.0, "sample_rate": 16000, "bols": bols})},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_post_list_serve_and_delete(recordings) -> None:
    body = _post()
    listed = client.get("/api/recordings").json()["recordings"]
    assert [r["id"] for r in listed] == [body["id"]]
    assert client.get(f"/api/recordings/{body['id']}/file").content[:4] == b"RIFF"
    assert client.delete(f"/api/recordings/{body['id']}").status_code == 200
    assert client.get(f"/api/recordings/{body['id']}").status_code == 422


def test_patch_refuses_a_label_that_does_not_tokenize(recordings) -> None:
    body = _post()
    res = client.patch(f"/api/recordings/{body['id']}", json={"bols": "dha traka"})
    assert res.status_code == 422
    assert res.json()["token"] == "traka"
    assert recordings.get(body["id"]).bols == "", "nothing was written"
    ok = client.patch(f"/api/recordings/{body['id']}", json={"bols": "dha tirakita"})
    assert ok.status_code == 200 and ok.json()["bols"] == "dha tirakita"


@pytest.mark.parametrize("bad", ["..%2F..%2Fetc%2Fpasswd", "..", "not-an-id"])
def test_traversal_ids_are_refused(recordings, bad: str) -> None:
    assert client.get(f"/api/recordings/{bad}").status_code in (404, 422)
    assert client.get(f"/api/recordings/{bad}/file").status_code in (404, 422)


def test_label_check_reports_units_or_a_column(recordings) -> None:
    ok = client.post("/api/labels/check", json={"text": "dha tirakita"}).json()
    assert ok["ok"] and ok["units"] == ["dha", "te", "re", "ki", "ta"] and ok["slots"] == 5
    bad = client.post("/api/labels/check", json={"text": "dha xyz"}).json()
    assert not bad["ok"] and bad["column"] == 4


def test_prelabel_drafts_from_the_previous_take(recordings) -> None:
    first = _post("dha dhin dhin dha")
    second = _post()
    # Same-second ids sort randomly; pin queue order explicitly.
    recordings.update(first["id"], {})
    for rid, when in ((first["id"], "2026-01-01T00:00:00Z"), (second["id"], "2026-01-01T00:00:10Z")):
        path = recordings.root / f"{rid}.json"
        raw = _json.loads(path.read_text())
        raw["recorded_at"] = when
        path.write_text(_json.dumps(raw))

    pre = client.get(f"/api/recordings/{second['id']}/prelabel").json()
    assert pre["draft"] == "dha dhin dhin dha"
    assert pre["draft_source"].startswith("take")
    assert pre["onset_count"] == 3
    assert len(pre["onsets"]) == 3
    # The corpus is offered too, for cycling.
    assert any(c["source"].endswith(".txt") for c in pre["candidates"])


def test_prelabel_keeps_a_saved_label(recordings) -> None:
    body = _post("na tin")
    assert client.get(f"/api/recordings/{body['id']}/prelabel").json()["draft"] == "na tin"


def test_dataset_and_label_page(recordings) -> None:
    _post("dha tirakita")
    d = client.get("/api/dataset").json()
    assert d["labelled"] == 1 and d["compounds"]["tirakita"] == 1
    page = client.get("/label")
    assert page.status_code == 200 and "bolbox label" in page.text
    assert client.get("/label/core.js").status_code == 200


def test_prelabel_does_not_carry_a_label_into_a_different_length_clip(recordings) -> None:
    short = _post("na tin na")
    theka = _post("dha dhin dhin dha | dha dhin dhin dha | dha tin tin ta | ta dhin dhin dha")
    new = _post()  # three onsets: the sixteen-bol theka just before it cannot be right
    for i, rid in enumerate((short["id"], theka["id"], new["id"])):
        path = recordings.root / f"{rid}.json"
        raw = _json.loads(path.read_text())
        raw["recorded_at"] = f"2026-01-01T00:00:0{i}Z"
        path.write_text(_json.dumps(raw))
    pre = client.get(f"/api/recordings/{new['id']}/prelabel").json()
    assert pre["draft"] == "na tin na"
