# Padhant Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record yourself reciting padhant in the browser, store it as WAV plus a metadata sidecar, and play it back — the instrument that produces this project's training data.

**Architecture:** Capture runs in the browser (`getUserMedia` → `AudioWorklet` → Float32 PCM → the existing `encodeWav`), because the browser already owns audio. The Python server writes bytes to disk and nothing else — it still renders no audio, so the locked "one audio engine" contract is untouched. A take is written to IndexedDB *before* upload and retried, so a dead server never costs you a recording.

**Tech Stack:** Python 3.13 (pyenv), FastAPI, pytest. TypeScript, Vite, vitest, Playwright (real Chromium with a fake audio device — the only honest way to test mic capture).

## Global Constraints

- Environment is **pyenv**, pinned by `.python-version`. Never `python3 -m venv`, never system pip.
- **The Python server renders no audio.** It stores and serves bytes. Playback and export stay in the browser.
- Recordings are stored as **PCM WAV**, never a lossy codec. `MediaRecorder` gives webm/opus and is therefore not acceptable for training data.
- Path confinement: every recording id is server-generated and validated; a client-supplied id is never trusted as a path component. Same rule and same shape as `read_composition` in `bolbox/server.py`.
- `data/recordings/` is git-ignored. Audio does not belong in the repo.
- A take is never lost to a server error. Buffer first, upload second.
- YAGNI: this plan records, stores, lists and plays back. **Labeling, the `Transcriber` seam, and `bolbox dataset` are the next plan** — do not build them here.

---

### Task 1: The recording store

**Files:**
- Create: `bolbox/recordings.py`, `tests/test_recordings.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RecordingMeta` frozen dataclass: `id, recorded_at, duration_sec, sample_rate, bols, tal, lay, notes`.
  - `RecordingStore(root: Path)` with `save(wav: bytes, meta: dict) -> RecordingMeta`, `list() -> list[RecordingMeta]` (newest first), `get(id) -> RecordingMeta`, `wav_path(id) -> Path`, `delete(id) -> None`.
  - `RecordingError` in `bolbox/errors.py`, subclassing `BolboxError` alongside `LexiconError`.
  - `MAX_WAV_BYTES = 100 * 1024 * 1024`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recordings.py`:

```python
"""Recording storage. The instrument that produces the training data.

The rules that matter here are about not losing or corrupting takes: ids are
server-generated so a client can never steer a path, oversized payloads are
refused rather than filling the disk, and a take with no label is a legitimate
state -- you record six of them and label them afterwards, because stopping to
type between takes is how a recording session becomes a chore you avoid.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bolbox.errors import RecordingError
from bolbox.recordings import MAX_WAV_BYTES, RecordingStore

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 100


@pytest.fixture
def store(tmp_path: Path) -> RecordingStore:
    return RecordingStore(tmp_path)


def test_save_writes_a_wav_and_a_sidecar(store: RecordingStore) -> None:
    meta = store.save(WAV, {"duration_sec": 7.4, "sample_rate": 48000})
    assert store.wav_path(meta.id).read_bytes() == WAV
    assert store.get(meta.id).duration_sec == 7.4


def test_an_unlabelled_take_is_valid(store: RecordingStore) -> None:
    """You record a run of takes and label them later. That is the point."""
    meta = store.save(WAV, {"duration_sec": 1.0, "sample_rate": 48000})
    assert meta.bols == ""


def test_ids_are_server_generated_and_unique(store: RecordingStore) -> None:
    a = store.save(WAV, {"duration_sec": 1.0, "sample_rate": 48000})
    b = store.save(WAV, {"duration_sec": 1.0, "sample_rate": 48000})
    assert a.id != b.id


def test_a_client_supplied_id_is_ignored(store: RecordingStore) -> None:
    """The id names a path. Trusting the client with it is the whole risk."""
    meta = store.save(WAV, {"id": "../../etc/passwd", "duration_sec": 1.0,
                            "sample_rate": 48000})
    assert meta.id != "../../etc/passwd"
    assert store.wav_path(meta.id).resolve().parent == store.root.resolve()


@pytest.mark.parametrize("bad", ["../escape", "/absolute", "a/b", "..", "", "no spaces"])
def test_lookup_rejects_ids_that_are_not_ids(store: RecordingStore, bad: str) -> None:
    with pytest.raises(RecordingError):
        store.get(bad)


def test_oversized_payloads_are_refused(store: RecordingStore) -> None:
    with pytest.raises(RecordingError, match="too large"):
        store.save(b"x" * (MAX_WAV_BYTES + 1), {"duration_sec": 1.0, "sample_rate": 48000})


def test_list_is_newest_first(store: RecordingStore) -> None:
    ids = [store.save(WAV, {"duration_sec": 1.0, "sample_rate": 48000}).id for _ in range(3)]
    assert [m.id for m in store.list()] == list(reversed(ids))


def test_delete_removes_both_files(store: RecordingStore) -> None:
    meta = store.save(WAV, {"duration_sec": 1.0, "sample_rate": 48000})
    store.delete(meta.id)
    assert not store.wav_path(meta.id).exists()
    assert not (store.root / f"{meta.id}.json").exists()
    with pytest.raises(RecordingError):
        store.get(meta.id)


def test_a_corrupt_sidecar_loses_one_take_not_the_dataset(store: RecordingStore) -> None:
    """The reason sidecars beat a single index file."""
    good = store.save(WAV, {"duration_sec": 1.0, "sample_rate": 48000})
    broken = store.save(WAV, {"duration_sec": 1.0, "sample_rate": 48000})
    (store.root / f"{broken.id}.json").write_text("{not json", encoding="utf-8")
    assert [m.id for m in store.list()] == [good.id]


def test_updating_a_label_preserves_everything_else(store: RecordingStore) -> None:
    meta = store.save(WAV, {"duration_sec": 7.4, "sample_rate": 48000})
    store.update(meta.id, {"bols": "dha dhin dhin dha", "lay": 120})
    after = store.get(meta.id)
    assert after.bols == "dha dhin dhin dha"
    assert after.lay == 120
    assert after.duration_sec == 7.4
    assert after.recorded_at == meta.recorded_at
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_recordings.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bolbox.recordings'`.

- [ ] **Step 3: Add `RecordingError`**

In `bolbox/errors.py`, beside the other `BolboxError` subclasses:

```python
class RecordingError(BolboxError):
    """A recording could not be stored, found, or read."""
```

- [ ] **Step 4: Write the store**

Create `bolbox/recordings.py`:

```python
"""Storage for recorded padhant: a WAV plus a JSON sidecar per take.

Sidecars rather than one index file, for three reasons: they diff cleanly in
git, they can be hand-edited when a label is wrong, and a corrupt one loses a
single take instead of the whole dataset.

The id is generated here and never taken from the client, because the id names
a path. `bols` may be empty -- an unlabelled take is a legitimate state, since
stopping to type between takes is how a recording session stops happening.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .errors import RecordingError

MAX_WAV_BYTES = 100 * 1024 * 1024

# Timestamp plus a short random suffix: sortable by name, and collision-free
# even when two takes land inside the same second.
_ID_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")


@dataclass(frozen=True)
class RecordingMeta:
    id: str
    recorded_at: str
    duration_sec: float
    sample_rate: int
    bols: str = ""
    tal: str = "tintal"
    lay: float = 0.0
    notes: str = ""

    @property
    def labelled(self) -> bool:
        return bool(self.bols.strip())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "recorded_at": self.recorded_at,
            "duration_sec": self.duration_sec,
            "sample_rate": self.sample_rate,
            "bols": self.bols,
            "tal": self.tal,
            "lay": self.lay,
            "notes": self.notes,
        }


class RecordingStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- write -------------------------------------------------------------

    def save(self, wav: bytes, meta: dict) -> RecordingMeta:
        if len(wav) > MAX_WAV_BYTES:
            raise RecordingError(
                f"recording is too large: {len(wav)} bytes, limit {MAX_WAV_BYTES}"
            )
        if not wav.startswith(b"RIFF"):
            raise RecordingError("recording is not a WAV (no RIFF header)")

        self.root.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        # `meta` is client data. Everything identifying is computed here.
        record = RecordingMeta(
            id=f"{now.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}",
            recorded_at=now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            duration_sec=float(meta.get("duration_sec", 0.0)),
            sample_rate=int(meta.get("sample_rate", 0)),
            bols=str(meta.get("bols", "")),
            tal=str(meta.get("tal", "tintal")),
            lay=float(meta.get("lay", 0.0)),
            notes=str(meta.get("notes", "")),
        )
        self.wav_path(record.id).write_bytes(wav)
        self._sidecar(record.id).write_text(
            json.dumps(record.to_dict(), indent=2), encoding="utf-8"
        )
        return record

    def update(self, id: str, changes: dict) -> RecordingMeta:
        """Edit the label and its context. Identity and audio facts are fixed."""
        current = self.get(id)
        editable = {"bols", "tal", "lay", "notes"}
        merged = current.to_dict() | {
            k: v for k, v in changes.items() if k in editable
        }
        record = RecordingMeta(
            id=current.id,
            recorded_at=current.recorded_at,
            duration_sec=current.duration_sec,
            sample_rate=current.sample_rate,
            bols=str(merged["bols"]),
            tal=str(merged["tal"]),
            lay=float(merged["lay"]),
            notes=str(merged["notes"]),
        )
        self._sidecar(id).write_text(
            json.dumps(record.to_dict(), indent=2), encoding="utf-8"
        )
        return record

    def delete(self, id: str) -> None:
        self._require_id(id)
        self.wav_path(id).unlink(missing_ok=True)
        self._sidecar(id).unlink(missing_ok=True)

    # -- read --------------------------------------------------------------

    def list(self) -> list[RecordingMeta]:
        if not self.root.is_dir():
            return []
        out: list[RecordingMeta] = []
        for path in sorted(self.root.glob("*.json"), reverse=True):
            try:
                out.append(self._read(path))
            except (RecordingError, OSError):
                # One unreadable sidecar must not take the list down with it.
                continue
        return out

    def get(self, id: str) -> RecordingMeta:
        self._require_id(id)
        path = self._sidecar(id)
        if not path.is_file():
            raise RecordingError(f"no recording {id!r}")
        return self._read(path)

    def wav_path(self, id: str) -> Path:
        self._require_id(id)
        return self.root / f"{id}.wav"

    # -- internals ---------------------------------------------------------

    def _sidecar(self, id: str) -> Path:
        return self.root / f"{id}.json"

    @staticmethod
    def _require_id(id: object) -> None:
        """Ids are a closed shape. This is what stops `../` reaching the disk."""
        if not isinstance(id, str) or not _ID_RE.match(id):
            raise RecordingError(f"not a recording id: {id!r}")

    @staticmethod
    def _read(path: Path) -> RecordingMeta:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RecordingError(f"{path.name}: corrupt sidecar: {exc}") from exc
        if not isinstance(raw, dict):
            raise RecordingError(f"{path.name}: sidecar is not an object")
        return RecordingMeta(
            id=str(raw["id"]),
            recorded_at=str(raw.get("recorded_at", "")),
            duration_sec=float(raw.get("duration_sec", 0.0)),
            sample_rate=int(raw.get("sample_rate", 0)),
            bols=str(raw.get("bols", "")),
            tal=str(raw.get("tal", "tintal")),
            lay=float(raw.get("lay", 0.0)),
            notes=str(raw.get("notes", "")),
        )
```

- [ ] **Step 5: Ignore the audio**

Add to `.gitignore`:

```
data/recordings/
```

Audio is not source. It is also the one artifact that cannot be regenerated, so
it wants a backup strategy rather than a git strategy.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS, including the 11 new tests.

- [ ] **Step 7: Commit**

```bash
git add bolbox/recordings.py bolbox/errors.py tests/test_recordings.py .gitignore
git commit -m "Store recorded padhant as WAV plus a JSON sidecar

Sidecars rather than one index: they diff, they can be hand-edited when a label
is wrong, and a corrupt one costs a single take instead of the dataset.

Ids are generated server-side and validated against a closed shape on every
lookup, because the id names a path. An unlabelled take is valid -- you record
a run and label afterwards, since stopping to type between takes is how a
recording session stops happening."
```

---

### Task 2: Endpoints

**Files:**
- Modify: `bolbox/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: Task 1's `RecordingStore`.
- Produces:
  - `POST /api/recordings` — multipart (`audio` file part + `meta` JSON string part) → `RecordingMeta.to_dict()`.
  - `GET /api/recordings` → `{"recordings": [...]}`.
  - `PATCH /api/recordings/{id}` — JSON body → updated meta.
  - `DELETE /api/recordings/{id}` → `{"deleted": id}`.
  - `GET /recordings/{id}.wav` — static mount, same shape as `/kits`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_server.py`:

```python
# -- recordings -------------------------------------------------------------

import io
import json as _json

WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 100


def _post_recording(bols: str = "") -> dict:
    return client.post(
        "/api/recordings",
        files={"audio": ("take.wav", io.BytesIO(WAV_BYTES), "audio/wav")},
        data={"meta": _json.dumps(
            {"duration_sec": 3.5, "sample_rate": 48000, "bols": bols, "lay": 120}
        )},
    ).json()


def test_post_stores_a_take_and_returns_its_id() -> None:
    body = _post_recording()
    assert body["id"] and body["duration_sec"] == 3.5
    client.delete(f"/api/recordings/{body['id']}")


def test_a_stored_take_is_listed_and_its_wav_is_served() -> None:
    body = _post_recording()
    listed = client.get("/api/recordings").json()["recordings"]
    assert body["id"] in [r["id"] for r in listed]
    assert client.get(f"/recordings/{body['id']}.wav").content == WAV_BYTES
    client.delete(f"/api/recordings/{body['id']}")


def test_patch_sets_the_label() -> None:
    body = _post_recording()
    patched = client.patch(
        f"/api/recordings/{body['id']}", json={"bols": "dha dhin dhin dha"}
    ).json()
    assert patched["bols"] == "dha dhin dhin dha"
    assert patched["duration_sec"] == 3.5  # audio facts survive a relabel
    client.delete(f"/api/recordings/{body['id']}")


def test_delete_removes_it() -> None:
    body = _post_recording()
    assert client.delete(f"/api/recordings/{body['id']}").status_code == 200
    assert client.get(f"/api/recordings/{body['id']}").status_code == 422


@pytest.mark.parametrize("bad", ["../../etc/passwd", "..", "not-an-id"])
def test_traversal_ids_are_refused(bad: str) -> None:
    assert client.get(f"/api/recordings/{bad}").status_code in (404, 422)
    assert client.delete(f"/api/recordings/{bad}").status_code in (404, 422)


def test_a_non_wav_upload_is_refused() -> None:
    res = client.post(
        "/api/recordings",
        files={"audio": ("take.webm", io.BytesIO(b"\x1aE\xdf\xa3not a wav"), "audio/webm")},
        data={"meta": _json.dumps({"duration_sec": 1.0, "sample_rate": 48000})},
    )
    assert res.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_server.py -k recording -v`
Expected: FAIL — 404 on `/api/recordings`, the routes do not exist.

- [ ] **Step 3: Add the routes**

In `bolbox/server.py`, add the import and store next to the existing module-level singletons:

```python
from fastapi import FastAPI, File, Form, UploadFile

from .recordings import RecordingStore

RECORDINGS_DIR = REPO_ROOT / "data" / "recordings"
_RECORDINGS = RecordingStore(RECORDINGS_DIR)
```

Add a handler so a `RecordingError` becomes a 422 like every other `BolboxError`
— it already subclasses `BolboxError`, so the existing `_handle_bolbox_error`
covers it. Verify that rather than adding a second handler.

Then the routes, after `read_composition`:

```python
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
async def update_recording(id: str, changes: dict) -> dict:
    return _RECORDINGS.update(id, changes).to_dict()


@app.delete("/api/recordings/{id}")
def delete_recording(id: str) -> dict:
    _RECORDINGS.get(id)  # 422 rather than a silent success on an unknown id
    _RECORDINGS.delete(id)
    return {"deleted": id}
```

Add `import json` at the top if it is not already there, and mount the audio
beside the kits mount at the bottom of the file:

```python
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/recordings", StaticFiles(directory=str(RECORDINGS_DIR)), name="recordings")
```

The mount must come **before** the catch-all `/` static mount, or the SPA
handler swallows it.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bolbox/server.py tests/test_server.py
git commit -m "Serve recordings: store, list, relabel, delete

Multipart in, sidecar metadata out. Ids are validated by RecordingStore on
every lookup, so a traversal id fails the same way whichever route it arrives
through. The static mount is registered before the SPA catch-all, which would
otherwise swallow it."
```

---

### Task 3: Mic capture in the browser

**Files:**
- Create: `web/public/recorder-worklet.js`, `web/src/recorder.ts`, `web/src/recorder.test.ts`
- Modify: `web/src/api.ts`

**Interfaces:**
- Consumes: Task 2's endpoints; `encodeWav` from `web/src/export.ts`.
- Produces:
  - `concatChunks(chunks: Float32Array[]): Float32Array` — exported for testing.
  - `class Recorder { start(): Promise<void>; stop(): Promise<Take>; readonly recording: boolean }`
  - `interface Take { wav: Blob; durationSec: number; sampleRate: number }`
  - `uploadRecording(take: Take, meta: object): Promise<RecordingMetaJSON>` in `api.ts`.

- [ ] **Step 1: Write the failing test**

Create `web/src/recorder.test.ts`. Only the pure part is unit-tested — a real
`AudioContext` does not exist under vitest, and faking one would test the fake:

```ts
import { describe, expect, it } from "vitest";
import { concatChunks } from "./recorder";

describe("concatChunks", () => {
  it("joins chunks in order", () => {
    const out = concatChunks([new Float32Array([1, 2]), new Float32Array([3])]);
    expect(Array.from(out)).toEqual([1, 2, 3]);
  });

  it("returns an empty buffer for no chunks", () => {
    expect(concatChunks([]).length).toBe(0);
  });

  it("does not mutate its inputs", () => {
    const a = new Float32Array([1, 2]);
    concatChunks([a, new Float32Array([3])]);
    expect(Array.from(a)).toEqual([1, 2]);
  });

  it("preserves sample values exactly", () => {
    // Float32 round-tripping matters: this is training data, not a preview.
    const a = new Float32Array([-1, -0.5, 0, 0.5, 0.999999]);
    expect(Array.from(concatChunks([a]))).toEqual(Array.from(a));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/recorder.test.ts`
Expected: FAIL — `Cannot find module './recorder'`.

- [ ] **Step 3: Write the worklet**

Create `web/public/recorder-worklet.js`. It must be a separate file served at a
URL — `audioWorklet.addModule` takes a URL, not a function, so this cannot be
bundled into `recorder.ts`:

```js
/**
 * Copies mono input frames to the main thread. No processing: this is a
 * capture tap, and anything clever here would be baked into the training data
 * with no way to undo it later.
 */
class RecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    // A disconnected or silent-but-live input gives an empty array, not zeros.
    if (channel && channel.length) this.port.postMessage(channel.slice());
    return true;
  }
}

registerProcessor("recorder-processor", RecorderProcessor);
```

- [ ] **Step 4: Write the recorder**

Create `web/src/recorder.ts`:

```ts
/**
 * Microphone capture to PCM WAV.
 *
 * Deliberately NOT MediaRecorder: it produces webm/opus, and lossy audio is
 * not something to train an acoustic model on. This taps raw Float32 frames
 * through an AudioWorklet and hands them to the same `encodeWav` the WAV
 * export already uses, so there is one WAV writer in the project.
 */

import { encodeWav } from "./export";

export interface Take {
  readonly wav: Blob;
  readonly durationSec: number;
  readonly sampleRate: number;
}

export class RecorderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RecorderError";
  }
}

/** Flatten captured frames. Exported because it is the part worth testing. */
export function concatChunks(chunks: Float32Array[]): Float32Array {
  let total = 0;
  for (const c of chunks) total += c.length;
  const out = new Float32Array(total);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

export class Recorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private chunks: Float32Array[] = [];

  get recording(): boolean {
    return this.node !== null;
  }

  async start(): Promise<void> {
    if (this.recording) return;
    this.chunks = [];

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        // No processing on the way in. Echo cancellation and noise suppression
        // are tuned for speech intelligibility and would eat exactly the
        // transients a percussion model needs.
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (err) {
      throw new RecorderError(
        `microphone unavailable: ${err instanceof Error ? err.message : String(err)}. ` +
          "Check the browser's microphone permission for this page.",
      );
    }

    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("/recorder-worklet.js");
    this.node = new AudioWorkletNode(this.ctx, "recorder-processor");
    this.node.port.onmessage = (e: MessageEvent<Float32Array>) => {
      this.chunks.push(e.data);
    };
    this.ctx.createMediaStreamSource(this.stream).connect(this.node);
    // Worklets only pull while connected to a destination. A zero gain keeps
    // the graph running without monitoring the mic into the speakers, which
    // would feed back the moment anyone used this without headphones.
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    this.node.connect(mute).connect(this.ctx.destination);
  }

  async stop(): Promise<Take> {
    if (!this.ctx || !this.node) throw new RecorderError("not recording");

    const sampleRate = this.ctx.sampleRate;
    const samples = concatChunks(this.chunks);

    this.node.port.onmessage = null;
    this.node.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx.close();
    this.node = null;
    this.ctx = null;
    this.stream = null;
    this.chunks = [];

    if (samples.length === 0) {
      throw new RecorderError("recorded nothing — is the right input device selected?");
    }

    // OfflineAudioContext is the cheapest way to get an AudioBuffer of the
    // right shape; nothing is rendered through it.
    const buffer = new OfflineAudioContext(1, samples.length, sampleRate).createBuffer(
      1,
      samples.length,
      sampleRate,
    );
    buffer.copyToChannel(samples, 0);

    return {
      wav: new Blob([encodeWav(buffer)], { type: "audio/wav" }),
      durationSec: samples.length / sampleRate,
      sampleRate,
    };
  }
}
```

- [ ] **Step 5: Add the upload client**

Append to `web/src/api.ts`:

```ts
export interface RecordingMetaJSON {
  readonly id: string;
  readonly recorded_at: string;
  readonly duration_sec: number;
  readonly sample_rate: number;
  readonly bols: string;
  readonly tal: string;
  readonly lay: number;
  readonly notes: string;
}

export async function uploadRecording(
  take: { wav: Blob; durationSec: number; sampleRate: number },
  meta: Record<string, unknown> = {},
): Promise<RecordingMetaJSON> {
  const form = new FormData();
  form.append("audio", take.wav, "take.wav");
  form.append(
    "meta",
    JSON.stringify({
      duration_sec: take.durationSec,
      sample_rate: take.sampleRate,
      ...meta,
    }),
  );
  const res = await fetch("/api/recordings", { method: "POST", body: form });
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => null);
    const parse = normaliseParseError(body);
    throw new ApiError(parse?.message ?? `/api/recordings returned ${res.status}`, res.status);
  }
  return (await res.json()) as RecordingMetaJSON;
}

export async function listRecordings(): Promise<RecordingMetaJSON[]> {
  const res = await fetch("/api/recordings");
  if (!res.ok) throw new ApiError(`/api/recordings returned ${res.status}`, res.status);
  const body = (await res.json()) as { recordings?: RecordingMetaJSON[] };
  return body.recordings ?? [];
}

export async function deleteRecording(id: string): Promise<void> {
  const res = await fetch(`/api/recordings/${id}`, { method: "DELETE" });
  if (!res.ok) throw new ApiError(`could not delete ${id}`, res.status);
}
```

- [ ] **Step 6: Run both checks**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no type errors; 65 tests pass (61 existing + 4 new).

- [ ] **Step 7: Commit**

```bash
git add web/public/recorder-worklet.js web/src/recorder.ts web/src/recorder.test.ts web/src/api.ts
git commit -m "Capture the microphone as PCM WAV

An AudioWorklet tap rather than MediaRecorder, which produces webm/opus --
lossy audio is not what you train an acoustic model on. Reuses the WAV writer
the export path already has, so there is one of them.

getUserMedia asks for no echo cancellation, noise suppression or AGC: those are
tuned for speech intelligibility and eat the transients a percussion model
needs. The worklet is connected through a zero gain, because a worklet only
pulls while connected to a destination and monitoring the mic to the speakers
would feed back for anyone not wearing headphones."
```

---

### Task 4: A take is never lost

**Files:**
- Create: `web/src/pending.ts`, `web/src/pending.test.ts`
- Modify: `web/package.json` (dev dependency)

**Interfaces:**
- Consumes: Task 3's `Take`.
- Produces:
  - `savePending(take: Take, meta: object): Promise<number>` — returns the local key.
  - `listPending(): Promise<PendingTake[]>` where `PendingTake = { key: number; wav: Blob; meta: Record<string, unknown> }`.
  - `dropPending(key: number): Promise<void>`.
  - `flushPending(upload: (take, meta) => Promise<unknown>): Promise<{ sent: number; failed: number }>`.

- [ ] **Step 1: Add the test double**

IndexedDB does not exist under vitest's node environment.

Run: `cd web && npm install --save-dev fake-indexeddb`

- [ ] **Step 2: Write the failing test**

Create `web/src/pending.test.ts`:

```ts
import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { dropPending, flushPending, listPending, savePending } from "./pending";

const take = () => ({
  wav: new Blob([new Uint8Array([1, 2, 3])], { type: "audio/wav" }),
  durationSec: 1.5,
  sampleRate: 48000,
});

describe("pending takes", () => {
  beforeEach(async () => {
    for (const p of await listPending()) await dropPending(p.key);
  });

  it("survives being written before any upload is attempted", async () => {
    await savePending(take(), { bols: "dha" });
    const pending = await listPending();
    expect(pending).toHaveLength(1);
    expect(pending[0]!.meta["bols"]).toBe("dha");
    expect(pending[0]!.meta["duration_sec"]).toBe(1.5);
  });

  it("drops a take only after its upload resolves", async () => {
    await savePending(take(), {});
    const upload = vi.fn().mockResolvedValue({ id: "x" });
    expect(await flushPending(upload)).toEqual({ sent: 1, failed: 0 });
    expect(await listPending()).toHaveLength(0);
  });

  it("KEEPS a take whose upload fails", async () => {
    // The whole reason this module exists. A dead server must cost nothing.
    await savePending(take(), {});
    const upload = vi.fn().mockRejectedValue(new Error("server down"));
    expect(await flushPending(upload)).toEqual({ sent: 0, failed: 1 });
    expect(await listPending()).toHaveLength(1);
  });

  it("keeps the failures and clears the successes in a mixed flush", async () => {
    await savePending(take(), { bols: "first" });
    await savePending(take(), { bols: "second" });
    let call = 0;
    const upload = vi.fn().mockImplementation(() => {
      call += 1;
      return call === 1 ? Promise.resolve({}) : Promise.reject(new Error("nope"));
    });
    expect(await flushPending(upload)).toEqual({ sent: 1, failed: 1 });
    const left = await listPending();
    expect(left).toHaveLength(1);
    expect(left[0]!.meta["bols"]).toBe("second");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run src/pending.test.ts`
Expected: FAIL — `Cannot find module './pending'`.

- [ ] **Step 4: Write the buffer**

Create `web/src/pending.ts`:

```ts
/**
 * Takes are written here BEFORE any upload is attempted, and removed only once
 * the server has acknowledged them.
 *
 * Losing a good take to a server that happened to be down is the most
 * enraging failure this tool has available, and it is the one that would teach
 * you not to trust it. IndexedDB rather than memory because it also has to
 * survive a reload.
 */

const DB_NAME = "bolbox-pending";
const STORE = "takes";

export interface PendingTake {
  readonly key: number;
  readonly wav: Blob;
  readonly meta: Record<string, unknown>;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { keyPath: "key", autoIncrement: true });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("indexedDB.open failed"));
  });
}

function run<T>(store: IDBObjectStore, request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("indexedDB request failed"));
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => Promise<T>,
): Promise<T> {
  const db = await open();
  try {
    return await fn(db.transaction(STORE, mode).objectStore(STORE));
  } finally {
    db.close();
  }
}

export async function savePending(
  take: { wav: Blob; durationSec: number; sampleRate: number },
  meta: Record<string, unknown> = {},
): Promise<number> {
  return withStore("readwrite", (store) =>
    run(
      store,
      store.add({
        wav: take.wav,
        meta: { duration_sec: take.durationSec, sample_rate: take.sampleRate, ...meta },
      }) as IDBRequest<number>,
    ),
  );
}

export async function listPending(): Promise<PendingTake[]> {
  return withStore("readonly", (store) =>
    run(store, store.getAll() as IDBRequest<PendingTake[]>),
  );
}

export async function dropPending(key: number): Promise<void> {
  await withStore("readwrite", (store) => run(store, store.delete(key)));
}

/**
 * Try every pending take. A take is dropped only after its upload resolves,
 * so a failure leaves it exactly where it was for the next attempt.
 */
export async function flushPending(
  upload: (
    take: { wav: Blob; durationSec: number; sampleRate: number },
    meta: Record<string, unknown>,
  ) => Promise<unknown>,
): Promise<{ sent: number; failed: number }> {
  let sent = 0;
  let failed = 0;
  for (const item of await listPending()) {
    const { duration_sec, sample_rate, ...rest } = item.meta;
    try {
      await upload(
        {
          wav: item.wav,
          durationSec: Number(duration_sec ?? 0),
          sampleRate: Number(sample_rate ?? 0),
        },
        rest,
      );
      await dropPending(item.key);
      sent += 1;
    } catch {
      // Deliberately swallowed and counted: one unreachable server must not
      // abandon the remaining takes, and the take itself is still on disk.
      failed += 1;
    }
  }
  return { sent, failed };
}
```

- [ ] **Step 5: Run both checks**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no type errors; 69 tests pass (65 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add web/src/pending.ts web/src/pending.test.ts web/package.json web/package-lock.json
git commit -m "Buffer takes to IndexedDB before uploading

A take is written locally first and dropped only once the server acknowledges
it, so a dead server costs nothing and a reload does not either. Losing a good
take is the failure that would teach you not to trust this tool."
```

---

### Task 5: Record mode — SUPERSEDED, DO NOT BUILD

> **This task is replaced by the workbench.** Record mode moved out of the
> composition app and into a separate local page, where it gains prompts and
> automatic labelling — see
> `docs/superpowers/specs/2026-08-04-workbench-design.md` §4. Recording is human
> work, and the workbench is where human work lives; a mode toggle in the
> composition app would have put a chore next to the instrument.
>
> **Tasks 1-4 above are unchanged and are still the engine.** Build them, then
> build the workbench. The text below is kept only so the decision is legible.

**Files:**
- Modify: `web/index.html`, `web/src/main.ts`
- Create: `web/e2e/record.spec.ts`
- Modify: `web/playwright.config.ts`

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces: a Record panel with arm/stop, a take list with inline `<audio>` playback and delete, and a pending-take indicator.

- [ ] **Step 1: Write the failing E2E test**

This is the first real test of capture, and it needs a real browser. Chromium's
fake device plays a tone into `getUserMedia`, which is enough to prove the whole
path — permission, worklet, WAV encode, upload, sidecar, playback URL.

Create `web/e2e/record.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.describe("record mode", () => {
  test("records a take, stores it, and lists it for playback", async ({ page }) => {
    await page.goto("/");
    await page.waitForFunction(() => document.body.dataset["ready"] === "true");

    await page.getByTestId("mode-record").click();
    await page.getByTestId("record").click();
    await expect(page.getByTestId("record")).toBeDisabled();

    await page.waitForTimeout(1200);
    await page.getByTestId("stop-record").click();

    const takes = page.getByTestId("take-list").locator("li");
    await expect(takes).toHaveCount(1);
    // The wav must actually be fetchable, not merely listed.
    const src = await takes.first().locator("audio").getAttribute("src");
    expect(src).toMatch(/^\/recordings\/\d{8}T\d{6}-[0-9a-f]{6}\.wav$/);
    const res = await page.request.get(src!);
    expect(res.status()).toBe(200);

    await takes.first().getByTestId("delete-take").click();
    await expect(takes).toHaveCount(0);
  });
});
```

- [ ] **Step 2: Grant the fake microphone**

In `web/playwright.config.ts`, in the `use.launchOptions.args` array that already
exists, add:

```ts
"--use-fake-ui-for-media-stream",
"--use-fake-device-for-media-capture",
```

and alongside `use:`, add:

```ts
permissions: ["microphone"],
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd web && npx playwright test e2e/record.spec.ts`
Expected: FAIL — no element with `data-testid="mode-record"`.

- [ ] **Step 4: Add the markup**

In `web/index.html`, add a mode switch above the first panel and a record panel
after the transport panel:

```html
<div class="row" style="margin-bottom: 0.75rem">
  <button id="mode-compose" data-testid="mode-compose" class="primary">Compose</button>
  <button id="mode-record" data-testid="mode-record">Record</button>
</div>
```

```html
<section class="panel" id="record-panel" hidden>
  <div class="row">
    <button id="record" data-testid="record" class="primary">Record</button>
    <button id="stop-record" data-testid="stop-record" disabled>Stop</button>
    <span id="record-status" data-testid="record-status"></span>
  </div>
  <ul id="take-list" data-testid="take-list" style="margin-top: 0.9rem"></ul>
</section>
```

- [ ] **Step 5: Wire it up**

In `web/src/main.ts`, add the imports:

```ts
import { deleteRecording, listRecordings, uploadRecording, type RecordingMetaJSON } from "./api";
import { flushPending, savePending } from "./pending";
import { Recorder, RecorderError } from "./recorder";
```

Add to the `dom` object: `modeCompose`, `modeRecord`, `recordPanel`, `record`,
`stopRecord`, `recordStatus`, `takeList` — following the existing `el<T>(id)`
pattern.

Then add this section before `// -- boot`:

```ts
// -- record mode ------------------------------------------------------------

const recorder = new Recorder();

function setMode(record: boolean): void {
  dom.recordPanel.hidden = !record;
  dom.modeRecord.classList.toggle("primary", record);
  dom.modeCompose.classList.toggle("primary", !record);
  if (record) void refreshTakes();
}

async function refreshTakes(): Promise<void> {
  let takes: RecordingMetaJSON[] = [];
  try {
    takes = await listRecordings();
  } catch (err) {
    showError({ message: err instanceof Error ? err.message : String(err) });
  }
  dom.takeList.innerHTML = "";
  for (const take of takes) dom.takeList.append(takeRow(take));
}

function takeRow(take: RecordingMetaJSON): HTMLElement {
  const row = document.createElement("li");
  const when = take.recorded_at.replace("T", " ").replace("Z", "");
  row.append(document.createTextNode(
    `${when} · ${take.duration_sec.toFixed(1)}s${take.bols ? ` · ${take.bols}` : " · unlabelled"}`,
  ));

  const audio = document.createElement("audio");
  audio.controls = true;
  audio.src = `/recordings/${take.id}.wav`;
  row.append(audio);

  const remove = document.createElement("button");
  remove.textContent = "Delete";
  remove.dataset["testid"] = "delete-take";
  remove.addEventListener("click", () => {
    void deleteRecording(take.id).then(refreshTakes).catch((err: unknown) => {
      showError({ message: err instanceof Error ? err.message : String(err) });
    });
  });
  row.append(remove);
  return row;
}

async function startRecording(): Promise<void> {
  try {
    await recorder.start();
    dom.record.disabled = true;
    dom.stopRecord.disabled = false;
    dom.recordStatus.textContent = "recording…";
  } catch (err) {
    // A denied microphone permission must say so. Silence here reads as a
    // broken button, and it is the single most likely first-run failure.
    showError({ message: err instanceof RecorderError ? err.message : String(err) });
  }
}

async function stopRecording(): Promise<void> {
  dom.record.disabled = false;
  dom.stopRecord.disabled = true;
  try {
    const take = await recorder.stop();
    // Local first, always. Only then try the network.
    await savePending(take, { tal: pattern?.tal ?? "tintal", lay: Number(dom.lay.value) });
    const { sent, failed } = await flushPending(uploadRecording);
    dom.recordStatus.textContent =
      failed > 0 ? `${sent} uploaded, ${failed} waiting — is the server running?` : "saved";
    await refreshTakes();
  } catch (err) {
    dom.recordStatus.textContent = "";
    showError({ message: err instanceof Error ? err.message : String(err) });
  }
}
```

Register the listeners beside the existing ones:

```ts
dom.modeCompose.addEventListener("click", () => setMode(false));
dom.modeRecord.addEventListener("click", () => setMode(true));
dom.record.addEventListener("click", () => void startRecording());
dom.stopRecord.addEventListener("click", () => void stopRecording());
```

And in `boot()`, after the kits populate, retry anything stranded by a previous
session:

```ts
  // A take left over from a session where the server was down.
  void flushPending(uploadRecording).then(({ sent }) => {
    if (sent > 0) void refreshTakes();
  });
```

- [ ] **Step 6: Run everything**

Run: `cd web && npx tsc --noEmit && npx vitest run && npx playwright test`
Expected: no type errors; 69 vitest pass; the new E2E test passes alongside the existing ones.

Run: `python -m pytest`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/index.html web/src/main.ts web/e2e/record.spec.ts web/playwright.config.ts
git commit -m "Record mode: capture, store, list, play back

One page, two modes, sharing the existing transport and pattern view. A take
goes to IndexedDB before the network, and boot retries anything a previous
session could not upload.

Tested end to end in real Chromium with a fake capture device -- permission,
worklet, WAV encode, upload, sidecar and the playback URL, which is the whole
path and the only honest way to test a microphone."
```

---

## What this plan does not do

The next plan (`padhant-labelling`) covers:

- The `Transcriber` interface and `NullTranscriber` — the seam the acoustic model swaps into.
- Label editing wired to `/api/pattern`, so a labelled take plays back through the existing sampler.
- The per-bol variant control for bols with more than one realization.
- `bolbox dataset` coverage reporting — minutes, labelled vs unlabelled, and **per-bol counts**, which is what turns "record 30 minutes" into "record until the gaps close."

And their own specs after that: the acoustic model (wav2vec2 fine-tune + CTC, causal encoder so streaming is a decode-mode switch rather than a retrain), streaming decode, and sampler choke groups.
