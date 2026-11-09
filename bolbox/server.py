"""Local HTTP server. Serves patterns and MIDI; it does NOT render audio.

Audio rendering lives entirely in the browser. Playback uses `AudioContext` and
export uses `OfflineAudioContext` over the same graph-building code, so a
downloaded WAV is the same code path as what was heard -- equivalence by
construction rather than by keeping two sample engines in agreement.

That is also why moving the lay slider never touches this server. Tempo is a
client-side rendering concern; the pattern it re-renders is already in hand.

Run it:

    python -m bolbox.server            # or: uvicorn bolbox.server:app --reload
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import midi as midi_renderer
from .audio import read_wav
from .dataset import LabelError, coverage, parse_label
from .errors import BolboxError, ParseError, RecordingError
from .format import parse
from .grid import grid
from .lexicon import Lexicon
from .onsets import detect_onsets
from .recordings import RecordingStore
from .tal import TALS
from .vocab import Vocabulary

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
WEB_DIST = WEB_DIR / "dist"
KITS_DIR = REPO_ROOT / "kits"
COMPOSITIONS_DIR = REPO_ROOT / "data" / "compositions"
# BOLBOX_RECORDINGS moves the take store, e.g. to a backed-up folder outside
# the repo. The audio is the one artifact that cannot be regenerated.
RECORDINGS_DIR = Path(
    os.environ.get("BOLBOX_RECORDINGS") or REPO_ROOT / "data" / "recordings"
).expanduser()
LABEL_DIR = WEB_DIR / "label"

app = FastAPI(title="bolbox", version="0.1.0")

# The Vite dev server runs on a different port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_VOCAB = Vocabulary.load()
_LEXICON = Lexicon.load(vocab=_VOCAB)
_RECORDINGS = RecordingStore(RECORDINGS_DIR)


class PatternRequest(BaseModel):
    text: str = Field(..., description="Composition text, header included")
    lay: float | None = Field(
        None, description="Matras per minute. Overrides the file header."
    )


def _parse_error_payload(exc: ParseError) -> dict:
    """Errors reach the UI with a position so it can point at the mistake."""
    return {
        "error": exc.message,
        "line": exc.line,
        "column": exc.column,
        "text": exc.text,
    }


@app.exception_handler(ParseError)
async def _handle_parse_error(_request, exc: ParseError) -> JSONResponse:
    return JSONResponse(status_code=422, content=_parse_error_payload(exc))


@app.exception_handler(LabelError)
async def _handle_label_error(_request, exc: LabelError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": str(exc), "token": exc.token, "column": exc.column},
    )


@app.exception_handler(BolboxError)
async def _handle_bolbox_error(_request, exc: BolboxError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.post("/api/pattern")
def build_pattern(request: PatternRequest) -> dict:
    composition = parse(request.text, lexicon=_LEXICON)
    pattern = grid(composition, lexicon=_LEXICON, lay=request.lay)
    return pattern.to_dict()


@app.post("/api/midi")
def build_midi(request: PatternRequest) -> Response:
    composition = parse(request.text, lexicon=_LEXICON)
    pattern = grid(composition, lexicon=_LEXICON, lay=request.lay)
    title = (pattern.title or "bolbox").replace('"', "")
    return Response(
        content=midi_renderer.to_bytes(pattern),
        media_type="audio/midi",
        headers={"Content-Disposition": f'attachment; filename="{title}.mid"'},
    )


@app.get("/api/vocabulary")
def vocabulary() -> dict:
    """Strokes, bols and tals. Lets the UI validate and hint without guessing."""
    return {
        "strokes": [
            {
                "name": stroke.name,
                "drum": stroke.drum,
                "damped": stroke.damped,
                "verify": stroke.verify,
            }
            for stroke in _VOCAB
        ],
        "bols": [
            {
                "name": bol.name,
                # The default realization, flattened -- so a client that does
                # not care about variants reads exactly what it read before.
                "strokes": list(bol.strokes),
                "simultaneous": bol.simultaneous,
                "verify": bol.verify,
                "variants": [
                    {
                        "name": v.name,
                        "strokes": list(v.strokes),
                        "simultaneous": v.simultaneous,
                        "verify": v.verify,
                        "description": v.description,
                    }
                    for v in bol.variants
                ],
            }
            for bol in _LEXICON
        ],
        "surface_forms": _LEXICON.surface_forms,
        "tals": [
            {
                "name": tal.name,
                "matras": tal.matras,
                "vibhags": list(tal.vibhags),
                "khali_matras": sorted(tal.khali_matras),
            }
            for tal in TALS.values()
        ],
    }


# Which kit the UI opens with. Named explicitly rather than left to whichever
# directory happens to sort first -- that worked by accident, was invisible in
# the code, and would have broken silently the first time a kit was renamed.
DEFAULT_KIT = "deolekar-tabla"
FALLBACK_KIT = "placeholder-tabla"


@app.get("/api/kits")
def list_kits() -> dict:
    """Kit ids the browser can load. Manifests are served as static files.

    The default is returned both as its own field and first in the list, so a
    client that reads `default` and one that takes `kits[0]` agree.
    """
    if not KITS_DIR.is_dir():
        return {"kits": [], "default": None}

    names = sorted(
        path.name for path in KITS_DIR.iterdir() if (path / "kit.json").is_file()
    )
    if not names:
        return {"kits": [], "default": None}

    preferred = next(
        (name for name in (DEFAULT_KIT, FALLBACK_KIT) if name in names), names[0]
    )
    ordered = [preferred] + [name for name in names if name != preferred]
    return {"kits": ordered, "default": preferred}


@app.get("/api/compositions")
def list_compositions() -> dict:
    if not COMPOSITIONS_DIR.is_dir():
        return {"compositions": []}
    return {
        "compositions": sorted(p.name for p in COMPOSITIONS_DIR.glob("*.txt"))
    }


@app.get("/api/compositions/{name}")
def read_composition(name: str) -> Response:
    # Resolve and confine to the compositions directory: a name like
    # `../../etc/passwd` must not escape, and `..` in a URL path is not
    # something to leave to the client's good manners.
    target = (COMPOSITIONS_DIR / name).resolve()
    if not target.is_file() or COMPOSITIONS_DIR.resolve() not in target.parents:
        return JSONResponse(status_code=404, content={"error": f"no composition {name!r}"})
    return Response(content=target.read_text(encoding="utf-8"), media_type="text/plain")


# -- recordings and labeling -------------------------------------------------
#
# Capture plan Task 2, plus what the labeling tool needs. The server stores
# bytes and reads them for onset detection; it still renders no audio.


@app.post("/api/recordings")
async def create_recording(
    audio: UploadFile = File(...),
    meta: str = Form("{}"),
) -> dict:
    """Store one take. The browser owns capture; this owns the disk."""
    try:
        parsed = json.loads(meta)
    except json.JSONDecodeError as exc:
        raise RecordingError(f"meta is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RecordingError("meta must be a JSON object")
    return _RECORDINGS.save(await audio.read(), parsed).to_dict()


@app.get("/api/recordings")
def list_recordings() -> dict:
    return {"recordings": [r.to_dict() for r in _RECORDINGS.list()]}


@app.get("/api/recordings/{id}")
def read_recording(id: str) -> dict:
    return _RECORDINGS.get(id).to_dict()


@app.patch("/api/recordings/{id}")
def update_recording(id: str, changes: dict) -> dict:
    # A label that does not tokenize is refused here, not discovered at
    # training time. An empty label is fine: it means "not labelled yet".
    bols = changes.get("bols")
    if isinstance(bols, str) and bols.strip():
        parse_label(bols, _LEXICON)
    return _RECORDINGS.update(id, changes).to_dict()


@app.delete("/api/recordings/{id}")
def delete_recording(id: str) -> dict:
    _RECORDINGS.get(id)  # 422 rather than a silent success on an unknown id
    _RECORDINGS.delete(id)
    return {"deleted": id}


@app.get("/api/recordings/{id}/file")
def recording_file(id: str) -> Response:
    """The stored take, byte for byte. Serving bytes, not rendering audio."""
    path = _RECORDINGS.wav_path(id)
    if not path.is_file():
        return JSONResponse(status_code=404, content={"error": f"no audio for {id!r}"})
    return FileResponse(path, media_type="audio/wav")


class LabelCheck(BaseModel):
    text: str


@app.post("/api/labels/check")
def check_label(request: LabelCheck) -> dict:
    """Live validation while typing. Errors carry the column to underline."""
    try:
        parsed = parse_label(request.text, _LEXICON)
    except LabelError as exc:
        return {"ok": False, "error": str(exc), "token": exc.token, "column": exc.column}
    return {
        "ok": True,
        "bols": list(parsed.bols),
        "units": list(parsed.units),
        "slots": parsed.slots,
    }


def _queue_key(meta) -> tuple:
    return (meta.recorded_at, meta.source.get("name", ""), meta.id)


def _corpus_lines() -> list[tuple[str, str]]:
    out = []
    if not COMPOSITIONS_DIR.is_dir():
        return out
    for path in sorted(COMPOSITIONS_DIR.glob("*.txt")):
        in_body = False
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                in_body = True  # the header ends at the first blank line
                continue
            if in_body and ":" not in stripped.split()[0]:
                out.append((stripped, path.name))
    return out


def _plausible(slots: int, onsets: int) -> bool:
    # The detector under-counts compounds, so allow a quarter of the label.
    return abs(slots - onsets) <= max(2, round(0.25 * slots))


@app.get("/api/recordings/{id}/prelabel")
def prelabel(id: str) -> dict:
    """What the labeling page pre-fills, so you correct rather than type.

    There is no acoustic model yet, so the draft is not a transcription. It
    is, in order: the take's own label if it has one; otherwise the label of
    the nearest earlier labelled take, if its length fits the detected onset
    count (padhant is recorded as tempo triples, so two takes in three repeat
    the one before); otherwise whichever earlier label or corpus line has the
    stroke count closest to the onset count. Every
    alternative is returned too, ranked, for cycling with a key.

    When a CTCTranscriber exists it replaces the draft source and nothing
    else on the page changes -- the Transcriber seam from the capture spec.
    """
    meta = _RECORDINGS.get(id)
    samples, rate = read_wav(_RECORDINGS.wav_path(id).read_bytes())
    onsets = detect_onsets(samples, rate)

    queue = sorted(_RECORDINGS.list(), key=_queue_key)
    earlier = [m for m in queue if _queue_key(m) < _queue_key(meta) and m.labelled]

    candidates: list[dict] = []
    seen: set[str] = set()

    def add(text: str, source: str) -> None:
        key = " ".join(text.split())
        if not key or key in seen:
            return
        try:
            slots = parse_label(text, _LEXICON).slots
        except LabelError:
            return
        seen.add(key)
        candidates.append({"text": text, "source": source, "slots": slots})

    for m in reversed(earlier):
        add(m.bols, f"take {m.source.get('name') or m.id}")
    for text, name in _corpus_lines():
        add(text, name)

    n = len(onsets)
    ranked = sorted(candidates, key=lambda c: abs(c["slots"] - n))
    # The previous take wins only if its length is plausible for this clip.
    # Otherwise this is the first take of a new composition and the previous
    # label is the one draft guaranteed to be wrong.
    previous = candidates[0] if earlier and candidates else None
    if previous is not None and _plausible(previous["slots"], n):
        ranked.remove(previous)
        ranked.insert(0, previous)

    if meta.labelled:
        draft, source = meta.bols, "saved label"
    elif ranked:
        draft, source = ranked[0]["text"], ranked[0]["source"]
    else:
        draft, source = "", "none"

    return {
        "id": id,
        "onsets": onsets,
        "onset_count": n,
        "draft": draft,
        "draft_source": source,
        "candidates": ranked[:20],
    }


@app.get("/api/dataset")
def dataset_coverage() -> dict:
    return coverage(_RECORDINGS, _LEXICON).to_dict(_LEXICON)


@app.get("/label")
def label_page() -> Response:
    entry = LABEL_DIR / "index.html"
    if not entry.is_file():
        return JSONResponse(status_code=503, content={"error": "web/label/ is missing"})
    return FileResponse(entry)


if LABEL_DIR.is_dir():
    app.mount("/label", StaticFiles(directory=str(LABEL_DIR)), name="label")

if KITS_DIR.is_dir():
    app.mount("/kits", StaticFiles(directory=str(KITS_DIR)), name="kits")

if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
elif WEB_DIR.is_dir():
    # Before the front end is built, serve its source directly so the app is
    # usable without a build step.
    @app.get("/")
    def index() -> Response:
        entry = WEB_DIR / "index.html"
        if entry.is_file():
            return FileResponse(entry)
        return JSONResponse(
            status_code=503,
            content={"error": "web/ has no index.html yet; run the Vite dev server"},
        )

    app.mount("/src", StaticFiles(directory=str(WEB_DIR / "src")), name="web-src")


def main(port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
