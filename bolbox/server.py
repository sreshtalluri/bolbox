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

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import midi as midi_renderer
from .errors import BolboxError, ParseError
from .format import parse
from .grid import grid
from .lexicon import Lexicon
from .tal import TALS
from .vocab import Vocabulary

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
WEB_DIST = WEB_DIR / "dist"
KITS_DIR = REPO_ROOT / "kits"
COMPOSITIONS_DIR = REPO_ROOT / "data" / "compositions"

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


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
