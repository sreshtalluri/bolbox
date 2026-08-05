# Workbench: Foundation and Verify — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local page at `/workbench` that lists outstanding human work and lets the eight `verify: true` mappings be heard through the real kit and confirmed or corrected — writing back to `data/lexicon.yaml` and `data/strokes.yaml` without destroying their comments.

**Architecture:** A second Vite entry sharing only the audio modules with the composition app. The Python server gains a task API and write endpoints; every write validates through the existing loaders before touching disk, then reloads the server's cached vocabulary. Task state is derived from repo state, not stored, so it cannot go stale.

**Tech Stack:** Python 3.13 (pyenv), FastAPI, `ruamel.yaml`, pytest. TypeScript, Vite, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-04-workbench-design.md` (§0–§3).

## Global Constraints

- Environment is **pyenv**, pinned by `.python-version`. Never `python3 -m venv`, never system pip.
- **Comments in `data/*.yaml` are load-bearing** — they carry why `tha` is a bol rather than an alias, why `ki` may be physically `ka`, and what each `VERIFY` note asks. No write may destroy them.
- `data/strokes.yaml` is the single source of truth for physical strokes.
- Every write **validates through `Lexicon.from_dict` / `Vocabulary.from_dict` before touching disk**, so a bad edit fails with the loader's own error rather than producing a file that no longer loads.
- Every successful write **reloads the server's `_VOCAB` and `_LEXICON`** as part of the write, not as a separate call.
- The workbench shares `kit.ts`, `graph.ts` and `export.ts` with the composition app and nothing else. No second sample engine.
- The composition app gains no link to the workbench and no awareness of it.
- YAGNI: no record, no label, no import. Those are the next two plans.

## Sequencing

This plan has no dependency on `2026-08-04-padhant-capture.md`. It can be built
and used immediately. Record/label (spec §4) needs that plan's Tasks 1–4 first;
import (spec §7) comes last.

---

### Task 1: Prove the round-trip before building on it

If `ruamel` cannot round-trip these files unchanged, direct writes are off the
table and the design falls back to proposing diffs. **Learn that here, not after
five tasks depend on it.**

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_yaml_roundtrip.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ruamel.yaml>=0.18` as a runtime dependency.

- [ ] **Step 1: Write the failing test**

Create `tests/test_yaml_roundtrip.py`:

```python
"""The gate on writing to the data files at all.

`data/lexicon.yaml` and `data/strokes.yaml` are commented with the reasoning
behind each mapping -- why `tha` is a bol and not an alias, why `ki` may be the
same physical stroke as `ka`, what each VERIFY note is asking a player to check.
PyYAML deletes all of it: load-and-dump takes the lexicon from 144 lines to 126.

If these tests cannot pass, the workbench must not write these files.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from bolbox.yamlio import load_yaml, dump_yaml

DATA = Path(__file__).resolve().parent.parent / "data"
FILES = [DATA / "lexicon.yaml", DATA / "strokes.yaml"]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_round_trip_is_byte_identical(path: Path) -> None:
    """Load and dump with no changes must reproduce the file exactly."""
    original = path.read_text(encoding="utf-8")
    buffer = io.StringIO()
    dump_yaml(load_yaml(path), buffer)
    assert buffer.getvalue() == original


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_comments_survive_an_edit(path: Path) -> None:
    """The case that actually matters: change one value, keep every comment."""
    original = path.read_text(encoding="utf-8")
    comment_lines = [ln for ln in original.splitlines() if ln.lstrip().startswith("#")]
    assert comment_lines, f"{path.name} has no comments -- this test is vacuous"

    data = load_yaml(path)
    data["version"] = 99
    buffer = io.StringIO()
    dump_yaml(data, buffer)
    written = buffer.getvalue()

    assert "version: 99" in written
    for line in comment_lines:
        assert line in written, f"lost comment: {line.strip()[:60]}"


def test_flow_style_entries_stay_on_one_line() -> None:
    """`ge: { strokes: [ge] }` must not become four block-style lines.

    PyYAML's expansion of these is half of what makes its output unreadable.
    """
    buffer = io.StringIO()
    dump_yaml(load_yaml(DATA / "lexicon.yaml"), buffer)
    assert "{ strokes: [ge] }" in buffer.getvalue()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_yaml_roundtrip.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bolbox.yamlio'`.

- [ ] **Step 3: Add the dependency**

In `pyproject.toml`, add to `dependencies`:

```toml
    "ruamel.yaml>=0.18",
```

Then: `pip install -e ".[dev]"`

- [ ] **Step 4: Write the round-trip helpers**

Create `bolbox/yamlio.py`:

```python
"""Reading and writing the data files without destroying them.

Everything that WRITES `data/*.yaml` goes through here. Everything that only
READS may keep using PyYAML via `yaml.safe_load` -- reading is not the risk.

ruamel's round-trip mode preserves comments, key order, quoting and flow style.
PyYAML preserves none of it, and those comments are the reasoning behind every
mapping in the vocabulary.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO, Any

from ruamel.yaml import YAML

# Module-level and reused: a YAML() instance carries the round-trip
# configuration, and constructing a fresh default one per call is how the
# preservation settings silently stop applying.
_yaml = YAML()
_yaml.preserve_quotes = True
# The data files wrap prose descriptions; the default 80 would re-wrap them and
# fail the byte-identical test for reasons that have nothing to do with content.
_yaml.width = 4096


def load_yaml(path: Path | str) -> Any:
    """Load preserving comments and formatting, for a file that will be written."""
    return _yaml.load(Path(path).read_text(encoding="utf-8"))


def dump_yaml(data: Any, target: Path | str | IO[str]) -> None:
    """Write back, preserving everything `load_yaml` retained."""
    if hasattr(target, "write"):
        _yaml.dump(data, target)
        return
    path = Path(target)
    with path.open("w", encoding="utf-8") as handle:
        _yaml.dump(data, handle)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_yaml_roundtrip.py -v`
Expected: PASS, all four.

**If any test fails, STOP.** Do not adjust the test to match ruamel's output —
the test *is* the requirement. Report which file and how the output differs.
Tuning `_yaml.indent(...)`, `_yaml.width`, or `default_flow_style` is legitimate;
weakening the assertions is not. If it cannot be made to pass, report BLOCKED:
the spec's fallback is the workbench proposing diffs instead of writing.

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest`

```bash
git add pyproject.toml bolbox/yamlio.py tests/test_yaml_roundtrip.py
git commit -m "Round-trip the data files without destroying them

PyYAML takes data/lexicon.yaml from 144 lines to 126 and deletes every comment.
Those comments carry why tha is a bol rather than an alias and what each VERIFY
note asks, so anything that writes these files goes through ruamel round-trip
instead. The byte-identical test is the gate on writing them at all."
```

---

### Task 2: Edits to the vocabulary

**Files:**
- Create: `bolbox/edits.py`, `tests/test_edits.py`

**Interfaces:**
- Consumes: Task 1's `load_yaml` / `dump_yaml`.
- Produces, all raising `LexiconError` / `VocabError` on invalid input **before writing**:
  - `confirm_bol(name, *, lexicon_path=None, vocab=None) -> None`
  - `confirm_stroke(name, *, strokes_path=None) -> None`
  - `set_bol_strokes(name, strokes: list[str], *, lexicon_path=None, vocab=None) -> None`
  - `split_bol_into_variants(name, variants: dict[str, dict], default: str, *, lexicon_path=None, vocab=None) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_edits.py`:

```python
"""Edits the workbench makes to the vocabulary on the player's say-so.

Every one validates before it writes. A UI that can leave data/lexicon.yaml in
a state the loader rejects is a UI that can brick the whole toolchain from a
button, so the order is: build the candidate, load it, and only then write.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bolbox.edits import (
    confirm_bol,
    confirm_stroke,
    set_bol_strokes,
    split_bol_into_variants,
)
from bolbox.errors import LexiconError
from bolbox.lexicon import Lexicon
from bolbox.vocab import Vocabulary

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    lex = tmp_path / "lexicon.yaml"
    strokes = tmp_path / "strokes.yaml"
    shutil.copy(DATA / "lexicon.yaml", lex)
    shutil.copy(DATA / "strokes.yaml", strokes)
    return lex, strokes


def _load(files: tuple[Path, Path]) -> Lexicon:
    lex, strokes = files
    return Lexicon.load(lex, vocab=Vocabulary.load(strokes))


def test_confirming_a_bol_clears_verify_on_every_variant(files) -> None:
    lex_path, strokes_path = files
    vocab = Vocabulary.load(strokes_path)
    assert _load(files).resolve("din").verify is True

    confirm_bol("din", lexicon_path=lex_path, vocab=vocab)

    din = _load(files).resolve("din")
    assert din.verify is False
    assert [v.name for v in din.variants] == ["kinar", "full"]  # nothing else moved


def test_confirming_preserves_the_comments(files) -> None:
    lex_path, strokes_path = files
    before = lex_path.read_text(encoding="utf-8")
    confirm_bol("din", lexicon_path=lex_path, vocab=Vocabulary.load(strokes_path))
    after = lex_path.read_text(encoding="utf-8")
    for line in (ln for ln in before.splitlines() if ln.lstrip().startswith("#")):
        assert line in after, f"lost comment: {line.strip()[:60]}"


def test_confirming_a_stroke_clears_its_flag(files) -> None:
    _, strokes_path = files
    assert Vocabulary.load(strokes_path)["ti"].verify is True
    confirm_stroke("ti", strokes_path=strokes_path)
    assert Vocabulary.load(strokes_path)["ti"].verify is False


def test_setting_strokes_replaces_the_default_realization(files) -> None:
    lex_path, strokes_path = files
    set_bol_strokes("takita", ["ta", "ki", "te"],
                    lexicon_path=lex_path, vocab=Vocabulary.load(strokes_path))
    assert _load(files).resolve("takita").strokes == ("ta", "ki", "te")


def test_splitting_a_bol_into_variants(files) -> None:
    """The `din` path: you discover mid-check that one syllable is two strokes."""
    lex_path, strokes_path = files
    split_bol_into_variants(
        "tin",
        {"kinar": {"strokes": ["tin"]}, "sur": {"strokes": ["tun"]}},
        default="kinar",
        lexicon_path=lex_path,
        vocab=Vocabulary.load(strokes_path),
    )
    tin = _load(files).resolve("tin")
    assert [v.name for v in tin.variants] == ["kinar", "sur"]
    assert tin.strokes == ("tin",)  # the default is first


def test_an_unknown_stroke_is_refused_and_nothing_is_written(files) -> None:
    """Validation happens before the write, not after."""
    lex_path, strokes_path = files
    before = lex_path.read_text(encoding="utf-8")
    with pytest.raises((LexiconError, Exception)):
        set_bol_strokes("takita", ["ta", "NOT_A_STROKE"],
                        lexicon_path=lex_path, vocab=Vocabulary.load(strokes_path))
    assert lex_path.read_text(encoding="utf-8") == before


def test_splitting_without_a_valid_default_is_refused(files) -> None:
    lex_path, strokes_path = files
    before = lex_path.read_text(encoding="utf-8")
    with pytest.raises(LexiconError):
        split_bol_into_variants(
            "tin", {"a": {"strokes": ["tin"]}}, default="nope",
            lexicon_path=lex_path, vocab=Vocabulary.load(strokes_path),
        )
    assert lex_path.read_text(encoding="utf-8") == before


def test_editing_an_unknown_bol_is_refused(files) -> None:
    lex_path, strokes_path = files
    with pytest.raises(LexiconError, match="notabol"):
        confirm_bol("notabol", lexicon_path=lex_path,
                    vocab=Vocabulary.load(strokes_path))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_edits.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bolbox.edits'`.

- [ ] **Step 3: Write the editor**

Create `bolbox/edits.py`:

```python
"""Vocabulary edits made on the player's say-so, from the workbench.

THE RULE: validate, then write. Every function here builds the candidate
document, loads it through the real loader, and only writes if that succeeds.
A UI that can leave `data/lexicon.yaml` unloadable is a UI that can brick the
whole toolchain from one button press, and the loader is the only thing that
knows what valid means.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import LexiconError, VocabError
from .lexicon import DEFAULT_LEXICON_PATH, Lexicon
from .vocab import DEFAULT_STROKES_PATH, Vocabulary
from .yamlio import dump_yaml, load_yaml


def _bol_entry(doc: Any, name: str) -> Any:
    bols = doc.get("bols")
    if bols is None or name not in bols:
        raise LexiconError(f"no bol {name!r} in the lexicon")
    return bols[name]


def _commit_lexicon(doc: Any, path: Path, vocab: Vocabulary) -> None:
    """Load the candidate before writing it. This is the whole safety story."""
    Lexicon.from_dict(doc, vocab, source=f"{path} (pending edit)")
    dump_yaml(doc, path)


def confirm_bol(
    name: str, *, lexicon_path: Path | str | None = None, vocab: Vocabulary | None = None
) -> None:
    """Clear `verify` on every realization of a bol."""
    path = Path(lexicon_path or DEFAULT_LEXICON_PATH)
    doc = load_yaml(path)
    entry = _bol_entry(doc, name)

    entry.pop("verify", None)
    for variant in (entry.get("variants") or {}).values():
        variant.pop("verify", None)

    _commit_lexicon(doc, path, vocab or Vocabulary.load())


def set_bol_strokes(
    name: str,
    strokes: list[str],
    *,
    lexicon_path: Path | str | None = None,
    vocab: Vocabulary | None = None,
) -> None:
    """Replace the strokes of a bol's default realization."""
    if not strokes:
        raise LexiconError(f"bol {name!r} needs at least one stroke")
    path = Path(lexicon_path or DEFAULT_LEXICON_PATH)
    doc = load_yaml(path)
    entry = _bol_entry(doc, name)

    variants = entry.get("variants")
    if variants:
        default = next(
            (k for k, v in variants.items() if v.get("default")), None
        )
        if default is None:
            raise LexiconError(f"bol {name!r} has no default variant")
        variants[default]["strokes"] = list(strokes)
    else:
        entry["strokes"] = list(strokes)

    _commit_lexicon(doc, path, vocab or Vocabulary.load())


def split_bol_into_variants(
    name: str,
    variants: dict[str, dict],
    default: str,
    *,
    lexicon_path: Path | str | None = None,
    vocab: Vocabulary | None = None,
) -> None:
    """Turn a single-realization bol into several named ones.

    The `din` path -- you are checking a mapping by ear and discover the
    syllable is two different strokes depending on how you play it.
    """
    if default not in variants:
        raise LexiconError(
            f"default {default!r} is not among the variants given: "
            f"{', '.join(variants) or '(none)'}"
        )
    path = Path(lexicon_path or DEFAULT_LEXICON_PATH)
    doc = load_yaml(path)
    entry = _bol_entry(doc, name)

    entry.pop("strokes", None)
    entry.pop("simultaneous", None)
    entry["variants"] = {
        vname: {**body, **({"default": True} if vname == default else {})}
        for vname, body in variants.items()
    }

    _commit_lexicon(doc, path, vocab or Vocabulary.load())


def confirm_stroke(name: str, *, strokes_path: Path | str | None = None) -> None:
    """Clear `verify` on a physical stroke."""
    path = Path(strokes_path or DEFAULT_STROKES_PATH)
    doc = load_yaml(path)
    strokes = doc.get("strokes")
    if strokes is None or name not in strokes:
        raise VocabError(f"no stroke {name!r} in the vocabulary")
    strokes[name].pop("verify", None)
    Vocabulary.from_dict(doc, source=f"{path} (pending edit)")
    dump_yaml(doc, path)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_edits.py -v`
Expected: PASS, all eight.

- [ ] **Step 5: Run the full suite and commit**

```bash
git add bolbox/edits.py tests/test_edits.py
git commit -m "Vocabulary edits that validate before they write

Every edit builds the candidate document, loads it through the real loader, and
writes only if that succeeds. A UI that can leave lexicon.yaml unloadable is one
that can brick the toolchain from a button, and the loader is the only thing
that knows what valid means."
```

---

### Task 3: Write endpoints, and the staleness fix

**Files:**
- Modify: `bolbox/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: Task 2's edit functions.
- Produces:
  - `POST /api/lexicon/bols/{name}/confirm`
  - `PUT /api/lexicon/bols/{name}` — body `{"strokes": [...]}` or `{"variants": {...}, "default": "..."}`
  - `POST /api/strokes/{name}/confirm`
  - `reload_vocabulary()` — refreshes `_VOCAB` and `_LEXICON`, called by every successful write.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
# -- workbench writes -------------------------------------------------------

import shutil as _shutil
from pathlib import Path as _Path

_DATA = _Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def restore_data():
    """These tests write the real data files. Put them back afterwards.

    The reload matters as much as the file restore: the server holds the edited
    vocabulary in memory, so without it every later test in the session would
    see a confirmed `din`. Call `reload_vocabulary` directly rather than through
    an endpoint -- hitting a write endpoint to trigger a reload would edit the
    files we just restored.
    """
    from bolbox.server import reload_vocabulary

    lex, strokes = _DATA / "lexicon.yaml", _DATA / "strokes.yaml"
    saved = (lex.read_text("utf-8"), strokes.read_text("utf-8"))
    try:
        yield
    finally:
        lex.write_text(saved[0], encoding="utf-8")
        strokes.write_text(saved[1], encoding="utf-8")
        reload_vocabulary()


def test_confirming_a_bol_is_visible_without_a_restart(restore_data) -> None:
    """The staleness trap.

    server.py loads _LEXICON once at import. Without a reload inside the write,
    a confirmed mapping is ignored until the process restarts -- you would
    confirm a correction and watch the app keep using the old one.
    """
    before = client.get("/api/vocabulary").json()
    assert next(b for b in before["bols"] if b["name"] == "din")["verify"] is True

    assert client.post("/api/lexicon/bols/din/confirm").status_code == 200

    after = client.get("/api/vocabulary").json()
    assert next(b for b in after["bols"] if b["name"] == "din")["verify"] is False


def test_confirming_a_stroke_is_visible_without_a_restart(restore_data) -> None:
    assert client.post("/api/strokes/ti/confirm").status_code == 200
    strokes = client.get("/api/vocabulary").json()["strokes"]
    assert next(s for s in strokes if s["name"] == "ti")["verify"] is False


def test_put_replaces_strokes(restore_data) -> None:
    assert client.put("/api/lexicon/bols/takita",
                      json={"strokes": ["ta", "ki", "te"]}).status_code == 200
    bols = client.get("/api/vocabulary").json()["bols"]
    assert next(b for b in bols if b["name"] == "takita")["strokes"] == ["ta", "ki", "te"]


def test_put_can_split_into_variants(restore_data) -> None:
    res = client.put("/api/lexicon/bols/tin", json={
        "variants": {"kinar": {"strokes": ["tin"]}, "sur": {"strokes": ["tun"]}},
        "default": "kinar",
    })
    assert res.status_code == 200
    bols = client.get("/api/vocabulary").json()["bols"]
    tin = next(b for b in bols if b["name"] == "tin")
    assert [v["name"] for v in tin["variants"]] == ["kinar", "sur"]


def test_an_invalid_edit_is_refused_and_changes_nothing(restore_data) -> None:
    before = (_DATA / "lexicon.yaml").read_text("utf-8")
    res = client.put("/api/lexicon/bols/takita", json={"strokes": ["NOT_A_STROKE"]})
    assert res.status_code == 422
    assert (_DATA / "lexicon.yaml").read_text("utf-8") == before


def test_editing_an_unknown_bol_is_refused() -> None:
    assert client.post("/api/lexicon/bols/notabol/confirm").status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_server.py -k "confirming or put_ or invalid_edit or unknown_bol" -v`
Expected: FAIL — 404 on every new route.

- [ ] **Step 3: Add the reload and the routes**

In `bolbox/server.py`, replace the two module-level loads (lines 50-51) with a
reloadable pair:

```python
_VOCAB = Vocabulary.load()
_LEXICON = Lexicon.load(vocab=_VOCAB)


def reload_vocabulary() -> None:
    """Re-read the data files into the module singletons.

    Called by every successful write. server.py loads these once at import and
    every request reuses them, so without this a confirmed correction is ignored
    until the process restarts -- and worse, takes could be recorded against a
    vocabulary you believe you fixed.
    """
    global _VOCAB, _LEXICON
    _VOCAB = Vocabulary.load()
    _LEXICON = Lexicon.load(vocab=_VOCAB)
```

Every handler that reads `_LEXICON` must read the **module global** at call
time, which the existing handlers already do. Do not capture it in a default
argument or a closure.

Then add the routes, and the import:

```python
from . import edits


@app.post("/api/lexicon/bols/{name}/confirm")
def confirm_bol_route(name: str) -> dict:
    edits.confirm_bol(name, vocab=_VOCAB)
    reload_vocabulary()
    return {"confirmed": name}


@app.put("/api/lexicon/bols/{name}")
def update_bol_route(name: str, body: dict) -> dict:
    if "variants" in body:
        edits.split_bol_into_variants(
            name, body["variants"], body.get("default", ""), vocab=_VOCAB
        )
    elif "strokes" in body:
        edits.set_bol_strokes(name, list(body["strokes"]), vocab=_VOCAB)
    else:
        raise LexiconError("body needs either `strokes` or `variants`")
    reload_vocabulary()
    return {"updated": name}


@app.post("/api/strokes/{name}/confirm")
def confirm_stroke_route(name: str) -> dict:
    edits.confirm_stroke(name)
    reload_vocabulary()
    return {"confirmed": name}
```

Add `LexiconError` to the imports from `.errors`. `RecordingError`-style
handling already exists: `LexiconError` and `VocabError` subclass `BolboxError`,
which `_handle_bolbox_error` turns into a 422. Verify that rather than adding a
handler.

- [ ] **Step 4: Run the full suite and commit**

Run: `python -m pytest -v`

```bash
git add bolbox/server.py tests/test_server.py
git commit -m "Workbench write endpoints, and reload the vocabulary with them

server.py loaded the lexicon once at import, so a confirmed correction would
have been ignored until restart -- you would fix a mapping in the UI and watch
the app keep using the old one, or record takes against a vocabulary you
believed you had fixed. The reload is part of the write so it cannot be
forgotten."
```

---

### Task 4: The task list

**Files:**
- Create: `bolbox/tasks.py`, `tests/test_tasks.py`, `data/human-tasks.yaml`
- Modify: `bolbox/server.py`

**Interfaces:**
- Consumes: `Lexicon`, `Vocabulary`.
- Produces:
  - `Task` frozen dataclass: `id, kind, title, detail, payload, done`.
  - `derive_tasks(lexicon, vocab) -> list[Task]`
  - `authored_tasks(path) -> list[Task]`, `mark_done(id, path) -> None`
  - `all_tasks(lexicon, vocab, path) -> list[Task]`
  - `GET /api/tasks`, `POST /api/tasks/{id}/done`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tasks.py`:

```python
"""What human work is outstanding.

Derived tasks are computed from repo state on every call, so they cannot go
stale: the `verify: true` flag IS the task, and clearing it removes the entry.
That is the property worth protecting when new kinds get added.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bolbox.lexicon import Lexicon
from bolbox.tasks import all_tasks, authored_tasks, derive_tasks, mark_done
from bolbox.vocab import Vocabulary

VOCAB_YAML = """
version: 1
strokes:
  na: {drum: dayan, damped: false}
  ta: {drum: dayan, damped: false, verify: true}
"""

LEX_YAML = """
version: 1
bols:
  na: {strokes: [na]}
  din:
    variants:
      kinar: {strokes: [na], default: true, verify: true}
      full:  {strokes: [ta]}
"""


@pytest.fixture
def state() -> tuple[Lexicon, Vocabulary]:
    vocab = Vocabulary.from_dict(yaml.safe_load(VOCAB_YAML), source="<test>")
    return Lexicon.from_dict(yaml.safe_load(LEX_YAML), vocab, source="<test>"), vocab


def test_a_flagged_bol_produces_a_task(state) -> None:
    tasks = derive_tasks(*state)
    din = [t for t in tasks if t.kind == "verify_bol"]
    assert [t.payload["bol"] for t in din] == ["din"]
    assert "din" in din[0].title


def test_a_flagged_stroke_produces_a_task(state) -> None:
    tasks = [t for t in derive_tasks(*state) if t.kind == "verify_stroke"]
    assert [t.payload["stroke"] for t in tasks] == ["ta"]


def test_an_unflagged_entry_produces_nothing(state) -> None:
    """The property that makes this maintenance-free."""
    names = {t.payload.get("bol") for t in derive_tasks(*state)}
    assert "na" not in names


def test_the_payload_carries_what_the_ui_needs_to_play_it(state) -> None:
    """The Verify panel plays strokes; it must not have to re-derive them."""
    task = next(t for t in derive_tasks(*state) if t.kind == "verify_bol")
    assert task.payload["variants"] == [
        {"name": "kinar", "strokes": ["na"], "simultaneous": False, "verify": True},
        {"name": "full", "strokes": ["ta"], "simultaneous": False, "verify": False},
    ]


def test_a_composite_variant_reports_simultaneous(state) -> None:
    """`dhun` is ge+tun struck together. The UI must not audition it as two hits."""
    lexicon, vocab = state
    tasks = derive_tasks(Lexicon.load(vocab=Vocabulary.load()), Vocabulary.load())
    dhun = next(t for t in tasks if t.payload.get("bol") == "dhun")
    assert dhun.payload["variants"][0]["simultaneous"] is True


def test_task_ids_are_stable_across_calls(state) -> None:
    assert [t.id for t in derive_tasks(*state)] == [t.id for t in derive_tasks(*state)]


def test_authored_tasks_load_and_persist_done(tmp_path: Path) -> None:
    path = tmp_path / "human-tasks.yaml"
    path.write_text(
        "version: 1\ntasks:\n"
        "  - id: mic-denied\n    title: Deny the mic permission\n"
        "    detail: The error must read clearly.\n",
        encoding="utf-8",
    )
    assert [t.done for t in authored_tasks(path)] == [False]

    mark_done("mic-denied", path)
    assert [t.done for t in authored_tasks(path)] == [True]


def test_marking_an_unknown_authored_task_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "human-tasks.yaml"
    path.write_text("version: 1\ntasks: []\n", encoding="utf-8")
    with pytest.raises(KeyError):
        mark_done("nope", path)


def test_all_tasks_merges_both_sources(state, tmp_path: Path) -> None:
    path = tmp_path / "human-tasks.yaml"
    path.write_text(
        "version: 1\ntasks:\n  - id: x\n    title: T\n    detail: D\n", encoding="utf-8"
    )
    kinds = {t.kind for t in all_tasks(*state, path)}
    assert {"verify_bol", "verify_stroke", "manual"} <= kinds


def test_the_real_repo_has_the_tasks_we_expect() -> None:
    """Grounding: the eight flagged entries must actually surface."""
    vocab = Vocabulary.load()
    tasks = derive_tasks(Lexicon.load(vocab=vocab), vocab)
    bols = {t.payload["bol"] for t in tasks if t.kind == "verify_bol"}
    strokes = {t.payload["stroke"] for t in tasks if t.kind == "verify_stroke"}
    assert "din" in bols and "tirakita" in bols
    assert {"ti", "ki"} <= strokes
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tasks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bolbox.tasks'`.

- [ ] **Step 3: Write the task module**

Create `bolbox/tasks.py`:

```python
"""Outstanding human work, mostly computed rather than listed.

A checklist goes stale the moment something is fixed without editing it. So
anything queryable is DERIVED: the `verify: true` flag is the task, and clearing
it removes the entry with no bookkeeping. Work no query can find -- "deny the
microphone permission and check the error reads clearly" -- lives in an authored
file alongside.

Adding a new derived kind is one function returning `list[Task]`, appended to
DERIVERS. That is the whole extension story.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .lexicon import Lexicon
from .vocab import Vocabulary
from .yamlio import dump_yaml, load_yaml

DEFAULT_TASKS_PATH = Path(__file__).resolve().parent.parent / "data" / "human-tasks.yaml"


@dataclass(frozen=True)
class Task:
    id: str
    kind: str
    title: str
    detail: str
    payload: dict = field(default_factory=dict)
    done: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "payload": self.payload,
            "done": self.done,
        }


# -- derived ----------------------------------------------------------------


def _verify_bols(lexicon: Lexicon, _vocab: Vocabulary) -> list[Task]:
    out: list[Task] = []
    for bol in lexicon:
        if not bol.verify:
            continue
        out.append(
            Task(
                id=f"verify_bol:{bol.name}",
                kind="verify_bol",
                title=f"Confirm how `{bol.name}` is played",
                detail=bol.description or "Play it and confirm the strokes are right.",
                payload={
                    "bol": bol.name,
                    "variants": [
                        {
                            "name": v.name,
                            "strokes": list(v.strokes),
                            # The UI needs this to audition correctly: a
                            # composite (`dhun` = ge+tun) must be heard as one
                            # stroke of the drum, not two in sequence.
                            "simultaneous": v.simultaneous,
                            "verify": v.verify,
                        }
                        for v in bol.variants
                    ],
                },
            )
        )
    return out


def _verify_strokes(_lexicon: Lexicon, vocab: Vocabulary) -> list[Task]:
    return [
        Task(
            id=f"verify_stroke:{s.name}",
            kind="verify_stroke",
            title=f"Confirm the stroke `{s.name}`",
            detail=s.description or "Hear it and confirm it is its own stroke.",
            payload={"stroke": s.name, "drum": s.drum, "damped": s.damped},
        )
        for s in vocab.needs_verification
    ]


DERIVERS: list[Callable[[Lexicon, Vocabulary], list[Task]]] = [
    _verify_bols,
    _verify_strokes,
]


def derive_tasks(lexicon: Lexicon, vocab: Vocabulary) -> list[Task]:
    return [task for derive in DERIVERS for task in derive(lexicon, vocab)]


# -- authored ---------------------------------------------------------------


def authored_tasks(path: Path | str | None = None) -> list[Task]:
    target = Path(path or DEFAULT_TASKS_PATH)
    if not target.is_file():
        return []
    doc = load_yaml(target)
    return [
        Task(
            id=str(entry["id"]),
            kind="manual",
            title=str(entry.get("title", entry["id"])),
            detail=str(entry.get("detail", "")),
            done=bool(entry.get("done", False)),
        )
        for entry in (doc.get("tasks") or [])
    ]


def mark_done(id: str, path: Path | str | None = None) -> None:
    target = Path(path or DEFAULT_TASKS_PATH)
    doc = load_yaml(target)
    for entry in doc.get("tasks") or []:
        if str(entry["id"]) == id:
            entry["done"] = True
            dump_yaml(doc, target)
            return
    raise KeyError(f"no authored task {id!r}")


def all_tasks(
    lexicon: Lexicon, vocab: Vocabulary, path: Path | str | None = None
) -> list[Task]:
    return [*derive_tasks(lexicon, vocab), *authored_tasks(path)]
```

- [ ] **Step 4: Seed the authored file**

Create `data/human-tasks.yaml` from `docs/YOUR-TURN.md` §3 — the manual checks
that no query can derive:

```yaml
# Human work that cannot be computed from the repo. Everything derivable --
# `verify: true` flags, unlabelled takes -- is generated instead, so it cannot
# go stale. This file is only for what a query cannot find.

version: 1

tasks:
  - id: mic-permission-error
    title: Deny the microphone permission and read the error
    detail: >
      It must say something actionable, not leave a dead button. This is the
      most likely first-run failure and the one that would make you distrust
      the tool.

  - id: playback-sounds-like-you
    title: Record a take and play it back
    detail: Not thin, not clipped, not half-speed.

  - id: input-levels
    title: Recite a loud `dha` and check it does not clip
    detail: >
      Capture is deliberately raw -- no AGC, no noise suppression, no echo
      cancellation, because those eat percussion transients. Your input gain is
      not being fixed for you. Set it once and leave it.

  - id: survives-a-dead-server
    title: Kill the server mid-session, record two takes, restart it
    detail: >
      Both should upload on their own. If a take is ever lost, that is a bug,
      not a limitation -- say so.
```

- [ ] **Step 5: Add the endpoints**

In `bolbox/server.py`:

```python
from . import tasks as task_module


@app.get("/api/tasks")
def list_tasks() -> dict:
    return {
        "tasks": [t.to_dict() for t in task_module.all_tasks(_LEXICON, _VOCAB)]
    }


@app.post("/api/tasks/{id}/done")
def complete_task(id: str) -> dict:
    try:
        task_module.mark_done(id)
    except KeyError as exc:
        raise BolboxError(str(exc)) from exc
    return {"done": id}
```

- [ ] **Step 6: Run the full suite and commit**

```bash
git add bolbox/tasks.py tests/test_tasks.py data/human-tasks.yaml bolbox/server.py
git commit -m "Derive the human task list from repo state

A checklist goes stale the moment something is fixed without editing it, so
anything queryable is computed instead: the verify flag IS the task, and
clearing it removes the entry. An authored file carries only what no query can
find. Adding a kind is one function in DERIVERS."
```

---

### Task 5: The workbench page

**Files:**
- Create: `web/workbench.html`, `web/src/workbench/main.ts`, `web/src/workbench/tasks.ts`, `web/src/workbench/tasks.test.ts`
- Modify: `web/vite.config.ts`

**Interfaces:**
- Consumes: Task 4's `/api/tasks`.
- Produces:
  - `TaskJSON` interface mirroring `Task.to_dict()`.
  - `fetchTasks(): Promise<TaskJSON[]>`, `groupByKind(tasks): Map<string, TaskJSON[]>`, `outstanding(tasks): TaskJSON[]`.

- [ ] **Step 1: Write the failing test**

Create `web/src/workbench/tasks.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { groupByKind, outstanding, type TaskJSON } from "./tasks";

const task = (id: string, kind: string, done = false): TaskJSON => ({
  id, kind, title: id, detail: "", payload: {}, done,
});

describe("task list", () => {
  it("groups by kind, preserving first-seen order", () => {
    const grouped = groupByKind([
      task("a", "verify_bol"), task("b", "verify_stroke"), task("c", "verify_bol"),
    ]);
    expect([...grouped.keys()]).toEqual(["verify_bol", "verify_stroke"]);
    expect(grouped.get("verify_bol")!.map((t) => t.id)).toEqual(["a", "c"]);
  });

  it("hides completed work", () => {
    const left = outstanding([task("a", "manual", true), task("b", "manual")]);
    expect(left.map((t) => t.id)).toEqual(["b"]);
  });

  it("returns an empty group map for no tasks", () => {
    expect(groupByKind([]).size).toBe(0);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npx vitest run src/workbench/tasks.test.ts`
Expected: FAIL — `Cannot find module './tasks'`.

Note `vite.config.ts` already includes `src/**/*.test.ts`, so the subdirectory
is picked up with no config change.

- [ ] **Step 3: Write the module**

Create `web/src/workbench/tasks.ts`:

```ts
/**
 * The workbench's view of outstanding human work.
 *
 * Derived tasks arrive computed from repo state, so this layer never persists
 * or reconciles anything -- it renders what the server says and refetches
 * after a write. Any local task cache would be a second source of truth that
 * could disagree with the data files.
 */

export interface TaskJSON {
  readonly id: string;
  readonly kind: string;
  readonly title: string;
  readonly detail: string;
  readonly payload: Record<string, unknown>;
  readonly done: boolean;
}

export async function fetchTasks(): Promise<TaskJSON[]> {
  const res = await fetch("/api/tasks");
  if (!res.ok) throw new Error(`/api/tasks returned ${res.status}`);
  const body = (await res.json()) as { tasks?: TaskJSON[] };
  return body.tasks ?? [];
}

export function outstanding(tasks: readonly TaskJSON[]): TaskJSON[] {
  return tasks.filter((t) => !t.done);
}

/** Group by kind, keeping first-seen order so the list does not reshuffle. */
export function groupByKind(tasks: readonly TaskJSON[]): Map<string, TaskJSON[]> {
  const out = new Map<string, TaskJSON[]>();
  for (const task of tasks) {
    const bucket = out.get(task.kind);
    if (bucket) bucket.push(task);
    else out.set(task.kind, [task]);
  }
  return out;
}

export const KIND_LABELS: Readonly<Record<string, string>> = {
  verify_bol: "Confirm how these bols are played",
  verify_stroke: "Confirm these strokes",
  manual: "Checks to run by hand",
};
```

- [ ] **Step 4: Add the page and the build entry**

Create `web/workbench.html` — deliberately plain. This is a private tool, and
styling it like the app would invite treating it as one:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>bolbox workbench</title>
    <style>
      body { font: 15px/1.5 system-ui, sans-serif; margin: 2rem auto; max-width: 52rem; padding: 0 1rem; }
      h1 { font-size: 1.2rem; }
      .banner { background: #fffbe6; border: 1px solid #e8d98a; padding: .6rem .8rem; border-radius: 4px; }
      .task { border: 1px solid #ddd; border-radius: 4px; padding: .8rem; margin: .6rem 0; }
      .detail { color: #555; font-size: .9em; white-space: pre-wrap; }
      .strokes { font-family: ui-monospace, monospace; }
      button { font: inherit; padding: .25rem .7rem; }
      #error { color: #a00; }
    </style>
  </head>
  <body>
    <h1>bolbox workbench</h1>
    <p class="banner">
      Local tool for the human work — verifying mappings by ear. Writes directly
      to <code>data/lexicon.yaml</code> and <code>data/strokes.yaml</code>.
      Needs <code>bolbox serve</code> running.
    </p>
    <p id="error" role="alert" data-testid="error"></p>
    <div id="tasks" data-testid="tasks"></div>
    <script type="module" src="/src/workbench/main.ts"></script>
  </body>
</html>
```

In `web/vite.config.ts`, add a `build` section alongside `server` and `test`:

```ts
  build: {
    rollupOptions: {
      // Two entries: the composition app, and the private workbench. The
      // workbench is deliberately not linked from the app -- different job.
      input: {
        main: "index.html",
        workbench: "workbench.html",
      },
    },
  },
```

- [ ] **Step 5: Render the list**

Create `web/src/workbench/main.ts`:

```ts
/**
 * Workbench shell: fetch the task list and render it.
 *
 * Refetches after every write rather than mutating a local copy, because the
 * server derives most tasks from the data files -- a local edit could disagree
 * with what is actually on disk, and disk is the truth.
 */

import { fetchTasks, groupByKind, KIND_LABELS, outstanding, type TaskJSON } from "./tasks";

const el = (id: string): HTMLElement => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`missing element #${id}`);
  return found;
};

const dom = { tasks: el("tasks"), error: el("error") };

export function showError(message: string): void {
  dom.error.textContent = message;
}

function renderTask(task: TaskJSON): HTMLElement {
  const box = document.createElement("div");
  box.className = "task";
  box.dataset["taskId"] = task.id;

  const title = document.createElement("strong");
  title.textContent = task.title;
  box.append(title);

  if (task.detail) {
    const detail = document.createElement("div");
    detail.className = "detail";
    detail.textContent = task.detail;
    box.append(detail);
  }
  return box;
}

export async function refresh(): Promise<void> {
  showError("");
  let tasks: TaskJSON[];
  try {
    tasks = await fetchTasks();
  } catch (err) {
    // The overwhelmingly likely cause is that `bolbox serve` is not running,
    // and an empty page would read as "no work left to do".
    showError(
      `${err instanceof Error ? err.message : String(err)} — is \`bolbox serve\` running?`,
    );
    return;
  }

  dom.tasks.innerHTML = "";
  const left = outstanding(tasks);
  if (left.length === 0) {
    dom.tasks.textContent = "Nothing outstanding.";
    return;
  }
  for (const [kind, group] of groupByKind(left)) {
    const heading = document.createElement("h2");
    heading.style.fontSize = "1rem";
    heading.textContent = `${KIND_LABELS[kind] ?? kind} (${group.length})`;
    dom.tasks.append(heading);
    for (const task of group) dom.tasks.append(renderTask(task));
  }
  document.body.dataset["ready"] = "true";
}

void refresh();
```

- [ ] **Step 6: Run the checks and commit**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no type errors; 64 tests pass (61 + 3 new).

Verify by hand: `python -m bolbox serve`, then open
`http://127.0.0.1:5173/workbench.html` with `npm run dev`. You should see the
eight flagged entries grouped under two headings.

```bash
git add web/workbench.html web/src/workbench web/vite.config.ts
git commit -m "Workbench page: render the outstanding human work

A second Vite entry, deliberately unlinked from the composition app and
deliberately plain -- it is a private tool, and styling it like the app would
invite treating it as one. Refetches after writes rather than caching, because
the server derives tasks from the data files and disk is the truth."
```

---

### Task 6: Verify by ear

**Files:**
- Create: `web/src/workbench/play.ts`, `web/src/workbench/play.test.ts`, `web/e2e/workbench.spec.ts`
- Modify: `web/src/workbench/main.ts`

**Interfaces:**
- Consumes: Task 5's shell; `Kit`, `VoicePool`, `renderEvents` from the shared audio modules.
- Produces:
  - `strokeEvents(strokes: readonly string[], startSec: number, gapSec?: number): ScheduledEvent[]`
  - `playStrokes(ctx, kit, strokes): void`

- [ ] **Step 1: Write the failing test**

Create `web/src/workbench/play.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { performedEvents, strokeEvents } from "./play";

describe("strokeEvents", () => {
  it("spaces strokes so a compound is audible as separate hits", () => {
    const events = strokeEvents(["te", "re", "ki", "ta"], 10, 0.25);
    expect(events.map((e) => e.whenSec)).toEqual([10, 10.25, 10.5, 10.75]);
    expect(events.map((e) => e.stroke)).toEqual(["te", "re", "ki", "ta"]);
  });

  it("marks only the first stroke as starting the bol", () => {
    // bol_offset === 0 is what the renderers use to tell one word from many.
    expect(strokeEvents(["ge", "na"], 0).map((e) => e.bolOffset)).toEqual([0, 1]);
  });

  it("gives every stroke a distinct round-robin index", () => {
    // Repeated strokes must not fire the identical sample twice in a row --
    // that machine-gunning is exactly what round robins exist to prevent.
    const events = strokeEvents(["ta", "ta", "ta"], 0);
    expect(new Set(events.map((e) => e.rrIndex)).size).toBe(3);
  });

  it("gives every stroke a distinct groupKey", () => {
    // Sharing a groupKey is how the graph decides ge+na were a `dha` and fires
    // one composite sample. That would collapse exactly what we want heard.
    const keys = strokeEvents(["ge", "na"], 0).map((e) => e.groupKey);
    expect(new Set(keys).size).toBe(2);
  });

  it("returns nothing for no strokes", () => {
    expect(strokeEvents([], 0)).toEqual([]);
  });
});

describe("performedEvents", () => {
  it("lands a composite's strokes on one instant, sharing a groupKey", () => {
    // `dhun` is ge+tun struck together -- one stroke of the instrument.
    const events = performedEvents(["ge", "tun"], true, "dhun", 5);
    expect(events.map((e) => e.whenSec)).toEqual([5, 5]);
    expect(new Set(events.map((e) => e.groupKey)).size).toBe(1);
    expect(events.every((e) => e.sourceBol === "dhun")).toBe(true);
  });

  it("spaces a compound's strokes in sequence", () => {
    const events = performedEvents(["te", "re", "ki", "ta"], false, "tirakita", 0);
    const times = events.map((e) => e.whenSec);
    expect(new Set(times).size).toBe(4);
    expect(times).toEqual([...times].sort((a, b) => a - b));
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npx vitest run src/workbench/play.test.ts`
Expected: FAIL — `Cannot find module './play'`.

- [ ] **Step 3: Write the adapter**

Create `web/src/workbench/play.ts`:

```ts
/**
 * Auditioning strokes through the REAL kit.
 *
 * A thin adapter over the composition app's sampler, not a second engine. The
 * whole value of verifying by ear is hearing the samples that will actually
 * play; an approximation would let you confirm a mapping against a sound you
 * will never hear again.
 */

import { renderEvents, VoicePool } from "../graph";
import type { Kit } from "../kit";
import type { ScheduledEvent } from "../scheduler";

/** Slow enough that four strokes of a compound are individually audible. */
export const AUDITION_GAP_SEC = 0.28;

/**
 * Strokes spaced out, each its own event. For "which stroke is this?".
 *
 * Every event gets a DISTINCT `groupKey`. That field is how the graph builder
 * notices that `ge` + `na` at one instant were a `dha` and fires a single
 * composite sample instead — which is the opposite of what this function is
 * for. Sharing a key here would silently collapse the strokes you are trying
 * to hear separately.
 */
export function strokeEvents(
  strokes: readonly string[],
  startSec: number,
  gapSec: number = AUDITION_GAP_SEC,
): ScheduledEvent[] {
  return strokes.map((stroke, index) => ({
    whenSec: startSec + gapSec * index,
    stroke,
    velocity: 100,
    sourceBol: "",
    bolOffset: index,
    // Distinct per hit so repeated strokes rotate through round robins rather
    // than firing sample 0 every time.
    rrIndex: index,
    bolRrIndex: index,
    groupKey: `audition-${index}`,
    loopIndex: 0,
    posMatras: 0,
  }));
}

/**
 * The bol as it is actually played. For "does this sound right?".
 *
 * A composite (`dhun` = ge + tun) is ONE stroke of the instrument: both
 * strokes land on the same instant and share a `groupKey`, so a kit holding a
 * recorded `dhun` fires that single sample. Hearing it as two spaced hits
 * would be auditioning a sound the instrument never makes.
 */
export function performedEvents(
  strokes: readonly string[],
  simultaneous: boolean,
  sourceBol: string,
  startSec: number,
): ScheduledEvent[] {
  if (!simultaneous) return strokeEvents(strokes, startSec, AUDITION_GAP_SEC / 2);
  return strokes.map((stroke, index) => ({
    whenSec: startSec,
    stroke,
    velocity: 100,
    sourceBol,
    bolOffset: index,
    rrIndex: index,
    bolRrIndex: 0,
    groupKey: `performed-${sourceBol}`,
    loopIndex: 0,
    posMatras: 0,
  }));
}

// Defaults match the composition app's `new VoicePool()` in player.ts:19,43 --
// 4 voices per stroke with a 20ms release on steal.
const pool = new VoicePool();

/** A small lead so the first note is never scheduled in the past. */
const LEAD_SEC = 0.05;

export function playStrokes(
  ctx: AudioContext,
  kit: Kit,
  strokes: readonly string[],
): void {
  renderEvents(ctx, ctx.destination, strokeEvents(strokes, ctx.currentTime + LEAD_SEC), kit, pool);
}

export function playPerformed(
  ctx: AudioContext,
  kit: Kit,
  strokes: readonly string[],
  simultaneous: boolean,
  sourceBol: string,
): void {
  renderEvents(
    ctx,
    ctx.destination,
    performedEvents(strokes, simultaneous, sourceBol, ctx.currentTime + LEAD_SEC),
    kit,
    pool,
  );
}

- [ ] **Step 4: Write the E2E test**

Create `web/e2e/workbench.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.describe("workbench", () => {
  test("lists the flagged mappings and confirming one removes it", async ({ page }) => {
    await page.goto("/workbench.html");
    await page.waitForFunction(() => document.body.dataset["ready"] === "true");

    const din = page.locator('[data-task-id="verify_bol:din"]');
    await expect(din).toBeVisible();

    // Auditioning must not throw -- the audio path is real, only the output is
    // unobservable from here.
    await din.getByTestId("play-variant-kinar").click();

    await din.getByTestId("confirm").click();
    await expect(din).toBeHidden();

    // And it is gone from the server's view, not just the DOM.
    const body = await (await page.request.get("/api/tasks")).json();
    expect(body.tasks.map((t: { id: string }) => t.id)).not.toContain("verify_bol:din");
  });
});
```

**This test mutates `data/lexicon.yaml`.** Restore it afterwards:
`git checkout data/lexicon.yaml`. Note that in the run instructions below.

- [ ] **Step 5: Add the Verify UI**

In `web/src/workbench/main.ts`, import the audio pieces and extend `renderTask`
so a `verify_bol` task renders its variants with play buttons and a Confirm
button, and a `verify_stroke` task renders one play button and Confirm.

```ts
import { loadKit, makeSynthKit, type Kit } from "../kit";
import { playPerformed, playStrokes } from "./play";

let ctx: AudioContext | null = null;
let kit: Kit | null = null;

/** Created on first press: a context made before a user gesture is suspended. */
async function audio(): Promise<{ ctx: AudioContext; kit: Kit }> {
  if (!ctx) ctx = new AudioContext();
  if (!kit) {
    try {
      kit = await loadKit("deolekar-tabla", ctx);
    } catch {
      // Auditioning against the placeholder is still worth something, and a
      // missing kit must not make Confirm unreachable.
      kit = makeSynthKit(ctx);
      showError("kit unavailable — auditioning with the built-in synth");
    }
  }
  return { ctx, kit };
}

function playButton(label: string, testid: string, strokes: string[]): HTMLButtonElement {
  const button = document.createElement("button");
  button.textContent = label;
  button.dataset["testid"] = testid;
  button.addEventListener("click", () => {
    void audio().then(({ ctx, kit }) => playStrokes(ctx, kit, strokes));
  });
  return button;
}

function performedButton(
  bol: string,
  variant: { name: string; strokes: string[]; simultaneous: boolean },
): HTMLButtonElement {
  const button = document.createElement("button");
  button.textContent = "As played";
  button.dataset["testid"] = `play-performed-${variant.name || "default"}`;
  button.addEventListener("click", () => {
    void audio().then(({ ctx, kit }) =>
      playPerformed(ctx, kit, variant.strokes, variant.simultaneous, bol),
    );
  });
  return button;
}

function confirmButton(path: string): HTMLButtonElement {
  const button = document.createElement("button");
  button.textContent = "Confirm";
  button.dataset["testid"] = "confirm";
  button.addEventListener("click", () => {
    void fetch(path, { method: "POST" })
      .then((res) => {
        if (!res.ok) throw new Error(`${path} returned ${res.status}`);
        return refresh();
      })
      .catch((err: unknown) => showError(err instanceof Error ? err.message : String(err)));
  });
  return button;
}
```

Then in `renderTask`, after the detail block:

```ts
  if (task.kind === "verify_bol") {
    const bol = String(task.payload["bol"]);
    const variants = (task.payload["variants"] ?? []) as {
      name: string; strokes: string[]; simultaneous: boolean;
    }[];
    for (const variant of variants) {
      const row = document.createElement("div");
      const label = variant.name ? `${bol}@${variant.name}` : bol;
      const strokes = document.createElement("span");
      strokes.className = "strokes";
      strokes.textContent = `${label} → ${variant.strokes.join(" ")} `;
      row.append(
        strokes,
        playButton("Play strokes", `play-variant-${variant.name || "default"}`, variant.strokes),
        // "As played" is the one that answers "does this sound right?" -- a
        // composite fires its single recorded sample here and two spaced hits
        // in the button above.
        performedButton(bol, variant),
      );
      box.append(row);
    }
    box.append(confirmButton(`/api/lexicon/bols/${bol}/confirm`));
  }

  if (task.kind === "verify_stroke") {
    const stroke = String(task.payload["stroke"]);
    box.append(
      playButton("Play", `play-stroke-${stroke}`, [stroke]),
      confirmButton(`/api/strokes/${stroke}/confirm`),
    );
  }
```

- [ ] **Step 6: Run everything and commit**

```bash
cd web && npx tsc --noEmit && npx vitest run
npx playwright test e2e/workbench.spec.ts
cd .. && git checkout data/lexicon.yaml   # the E2E test confirms `din` for real
python -m pytest
```

Expected: no type errors; 71 vitest pass (61 existing + 3 from Task 5 + 7 here); the workbench E2E passes; Python green.

```bash
git add web/src/workbench web/e2e/workbench.spec.ts
git commit -m "Verify mappings by ear in the workbench

Auditions through the real kit via a thin adapter over the composition app's
sampler, not a second engine -- the point of confirming by ear is hearing the
samples that will actually play, and an approximation would let you confirm a
mapping against a sound you never hear again.

Confirm clears the verify flag through the write API, which reloads the
server's vocabulary, and the task disappears because it was derived from that
flag in the first place."
```

---

## What this plan does not do

- **Record and label** (spec §4). Needs `2026-08-04-padhant-capture.md` Tasks 1–4 first.
- **Import** (spec §7). Last: three destinations, mandatory provenance, assignment by ear.
- **Generated riyaz drills, the invent-a-bol form, retrain.** Cut in the spec, with reasons.
- **A `coverage` or `missing_sample` task kind.** One function each in `DERIVERS` when wanted.
