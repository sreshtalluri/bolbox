"""Recording storage: the instrument that produces the training data.

The rules here are about not losing or corrupting takes: ids are server
generated so a client can never steer a path, oversized payloads are refused,
and an unlabelled take is a legitimate state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bolbox.errors import RecordingError
from bolbox.recordings import MAX_WAV_BYTES, RecordingStore

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 100
META = {"duration_sec": 1.0, "sample_rate": 48000}


@pytest.fixture
def store(tmp_path: Path) -> RecordingStore:
    return RecordingStore(tmp_path)


def test_save_writes_a_wav_and_a_sidecar(store: RecordingStore) -> None:
    meta = store.save(WAV, {"duration_sec": 7.4, "sample_rate": 48000})
    assert store.wav_path(meta.id).read_bytes() == WAV
    assert store.get(meta.id).duration_sec == 7.4


def test_an_unlabelled_take_is_valid_and_defaults_to_self(store: RecordingStore) -> None:
    meta = store.save(WAV, META)
    assert meta.bols == "" and not meta.labelled
    assert meta.speaker == "self"


def test_a_client_supplied_id_is_ignored(store: RecordingStore) -> None:
    meta = store.save(WAV, {**META, "id": "../../etc/passwd"})
    assert meta.id != "../../etc/passwd"
    assert store.wav_path(meta.id).resolve().parent == store.root.resolve()


@pytest.mark.parametrize("bad", ["../escape", "/absolute", "a/b", "..", "", "no spaces"])
def test_lookup_rejects_ids_that_are_not_ids(store: RecordingStore, bad: str) -> None:
    with pytest.raises(RecordingError):
        store.get(bad)


def test_oversized_and_non_wav_payloads_are_refused(store: RecordingStore) -> None:
    with pytest.raises(RecordingError, match="too large"):
        store.save(b"x" * (MAX_WAV_BYTES + 1), META)
    with pytest.raises(RecordingError, match="not a WAV"):
        store.save(b"\x1aE\xdf\xa3webm", META)


def test_list_is_newest_first(store: RecordingStore) -> None:
    ids = [store.save(WAV, META).id for _ in range(3)]
    assert sorted(m.id for m in store.list()) == sorted(ids)
    assert [m.id for m in store.list()] == sorted(ids, reverse=True)


def test_delete_removes_both_files(store: RecordingStore) -> None:
    meta = store.save(WAV, META)
    store.delete(meta.id)
    assert not store.wav_path(meta.id).exists()
    with pytest.raises(RecordingError):
        store.get(meta.id)


def test_a_corrupt_sidecar_loses_one_take_not_the_dataset(store: RecordingStore) -> None:
    good = store.save(WAV, META)
    broken = store.save(WAV, META)
    (store.root / f"{broken.id}.json").write_text("{not json", encoding="utf-8")
    assert [m.id for m in store.list()] == [good.id]


def test_updating_a_label_preserves_everything_else(store: RecordingStore) -> None:
    meta = store.save(WAV, {"duration_sec": 7.4, "sample_rate": 48000},
                      source={"name": "a.wav", "sha256": "ab"})
    store.update(meta.id, {"bols": "dha dhin dhin dha", "lay": 120,
                           "duration_sec": 99, "id": "nope"})
    after = store.get(meta.id)
    assert after.bols == "dha dhin dhin dha"
    assert after.lay == 120
    assert after.duration_sec == 7.4, "audio facts are not editable"
    assert after.source == {"name": "a.wav", "sha256": "ab"}
    assert after.recorded_at == meta.recorded_at


def test_skip_is_a_flag_not_a_delete(store: RecordingStore) -> None:
    meta = store.save(WAV, META)
    assert store.update(meta.id, {"skipped": True}).skipped
    assert store.wav_path(meta.id).exists()
