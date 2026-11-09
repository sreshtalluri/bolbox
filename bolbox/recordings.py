"""Storage for recorded padhant: a WAV plus a JSON sidecar per take.

This is Task 1 of `docs/superpowers/plans/2026-08-04-padhant-capture.md`, plus
the `speaker` field from the workbench spec (section 7) and a `source` record
for takes that arrived by import rather than through the browser.

Sidecars rather than one index file, for three reasons: they diff cleanly, they
can be hand-edited when a label is wrong, and a corrupt one loses a single take
instead of the whole dataset.

The id is generated here and never taken from the client, because the id names
a path. `bols` may be empty -- an unlabelled take is a legitimate state.

THE LABEL IS THE TEXT YOU RECITED, never its strokes. `tirakita` is stored as
`tirakita`, so fixing that bol's stroke mapping in data/lexicon.yaml re-expands
every label for free. CTC targets are derived from it at training time by
`bolbox.dataset.ctc_targets`, never stored.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .errors import RecordingError

MAX_WAV_BYTES = 100 * 1024 * 1024

# Timestamp plus a short random suffix: sortable by name, and collision-free
# even when two takes land inside the same second (which every import does).
_ID_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{6}$")

_EDITABLE = ("bols", "tal", "lay", "notes", "speaker", "skipped")


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
    # Single speaker by design. Tagged anyway, so a recitation from someone
    # else can never enter the training set without leaving a trace.
    speaker: str = "self"
    # Set on a take you chose not to label (a false start, a cough). Excluded
    # from training and from the labeling queue's "next unlabelled" walk.
    skipped: bool = False
    # Where an imported take came from: {"name", "sha256"}. Empty for takes
    # recorded in the browser. sha256 is what makes re-importing idempotent.
    source: dict = field(default_factory=dict)

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
            "speaker": self.speaker,
            "skipped": self.skipped,
            "source": dict(self.source),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "RecordingMeta":
        source = raw.get("source") or {}
        return cls(
            id=str(raw["id"]),
            recorded_at=str(raw.get("recorded_at", "")),
            duration_sec=float(raw.get("duration_sec", 0.0)),
            sample_rate=int(raw.get("sample_rate", 0)),
            bols=str(raw.get("bols", "")),
            tal=str(raw.get("tal", "tintal")),
            lay=float(raw.get("lay", 0.0) or 0.0),
            notes=str(raw.get("notes", "")),
            speaker=str(raw.get("speaker", "self")) or "self",
            skipped=bool(raw.get("skipped", False)),
            source=dict(source) if isinstance(source, dict) else {},
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


class RecordingStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- write -------------------------------------------------------------

    def save(
        self,
        wav: bytes,
        meta: dict,
        *,
        source: dict | None = None,
        recorded_at: datetime | None = None,
    ) -> RecordingMeta:
        if len(wav) > MAX_WAV_BYTES:
            raise RecordingError(
                f"recording is too large: {len(wav)} bytes, limit {MAX_WAV_BYTES}"
            )
        if not (wav.startswith(b"RIFF") and wav[8:12] == b"WAVE"):
            raise RecordingError("recording is not a WAV (no RIFF/WAVE header)")

        self.root.mkdir(parents=True, exist_ok=True)
        now = _now()
        # `meta` is client data. Everything identifying is computed here.
        record = RecordingMeta(
            id=f"{now.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}",
            recorded_at=_iso(recorded_at or now),
            duration_sec=float(meta.get("duration_sec", 0.0)),
            sample_rate=int(meta.get("sample_rate", 0)),
            bols=str(meta.get("bols", "")),
            tal=str(meta.get("tal", "tintal")),
            lay=float(meta.get("lay", 0.0) or 0.0),
            notes=str(meta.get("notes", "")),
            speaker=str(meta.get("speaker", "self")) or "self",
            source=dict(source or {}),
        )
        self.wav_path(record.id).write_bytes(wav)
        self._write(record)
        return record

    def update(self, id: str, changes: dict) -> RecordingMeta:
        """Edit the label and its context. Identity and audio facts are fixed."""
        current = self.get(id).to_dict()
        for key in _EDITABLE:
            if key in changes:
                current[key] = changes[key]
        record = RecordingMeta.from_dict(current)
        self._write(record)
        return record

    def delete(self, id: str) -> None:
        self._require_id(id)
        self.wav_path(id).unlink(missing_ok=True)
        self._sidecar(id).unlink(missing_ok=True)

    # -- read --------------------------------------------------------------

    def list(self) -> list[RecordingMeta]:
        """Newest first, by id."""
        if not self.root.is_dir():
            return []
        out: list[RecordingMeta] = []
        for path in sorted(self.root.glob("*.json"), reverse=True):
            try:
                out.append(self._read(path))
            except (RecordingError, OSError, KeyError, ValueError, TypeError):
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

    def known_hashes(self) -> set[str]:
        return {m.source["sha256"] for m in self.list() if m.source.get("sha256")}

    # -- internals ---------------------------------------------------------

    def _sidecar(self, id: str) -> Path:
        return self.root / f"{id}.json"

    def _write(self, record: RecordingMeta) -> None:
        # Write-then-rename so a crash mid-write cannot leave a half sidecar.
        path = self._sidecar(record.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)

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
        return RecordingMeta.from_dict(raw)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
