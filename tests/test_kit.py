"""T7 -- a kit that loads makes a sound for every stroke.

The failure this file exists to prevent is silence. A kit missing `re` does not
raise anything at playback time; it just plays nothing where `re` should be, and
nothing reads as a sequencing bug rather than a missing WAV. So the validator is
total over data/strokes.yaml, and most of what follows is the different ways a
manifest can fail to be total.

The rest covers the mechanisms that make totality achievable without recording
fourteen strokes: `alias_of` (many-to-one, chains resolve, cycles do not) and
`composites` (a single recorded `dha` instead of `ge` + `na`).
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from bolbox.errors import UnknownStrokeError
from bolbox.kit import SCHEMA_VERSION, Kit, KitError, SampleSet
from bolbox.lexicon import Lexicon
from bolbox.vocab import Vocabulary

KITS_DIR = Path(__file__).resolve().parent.parent / "kits"
PLACEHOLDER = KITS_DIR / "placeholder-tabla"
SPARSE = KITS_DIR / "sparse-demo"
DEOLEKAR = KITS_DIR / "deolekar-tabla"


@pytest.fixture(scope="module")
def vocab() -> Vocabulary:
    return Vocabulary.load()


@pytest.fixture(scope="module")
def lexicon(vocab: Vocabulary) -> Lexicon:
    return Lexicon.load(vocab=vocab)


@pytest.fixture(scope="module")
def full_kit(vocab: Vocabulary, lexicon: Lexicon) -> Kit:
    return Kit.load(PLACEHOLDER, vocab=vocab, lexicon=lexicon)


@pytest.fixture(scope="module")
def sparse_kit(vocab: Vocabulary, lexicon: Lexicon) -> Kit:
    return Kit.load(SPARSE, vocab=vocab, lexicon=lexicon)


@pytest.fixture(scope="module")
def real_kit(vocab: Vocabulary, lexicon: Lexicon) -> Kit:
    return Kit.load(DEOLEKAR, vocab=vocab, lexicon=lexicon)


@pytest.fixture(scope="module")
def shipped_kits(full_kit: Kit, sparse_kit: Kit, real_kit: Kit) -> tuple[Kit, ...]:
    return (full_kit, sparse_kit, real_kit)


# -- fixture builder -------------------------------------------------------


def write_kit(
    tmp_path: Path,
    strokes: dict,
    *,
    files: list[str] | None = None,
    **manifest_extra,
) -> Path:
    """Write a kit directory, creating a real (tiny) WAV for each named sample.

    Real files rather than empty ones because the loader checks existence, and a
    fixture that lies about that would let a coverage test pass for the wrong
    reason.
    """
    if files is None:
        files = sorted(
            {f for body in strokes.values() for f in body.get("samples", [])}
            | {
                f
                for body in manifest_extra.get("composites", {}).values()
                for f in body.get("samples", [])
            }
        )
    for filename in files:
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(48_000)
            handle.writeframes(b"\x00\x00" * 64)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "name": "fixture",
        "strokes": strokes,
        **manifest_extra,
    }
    (tmp_path / "kit.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def total_strokes(vocab: Vocabulary) -> dict:
    """The minimum manifest that covers the vocabulary: one sample per stroke."""
    return {name: {"samples": [f"{name}.wav"]} for name in vocab.names}


# -- the kits that ship ----------------------------------------------------


def test_placeholder_kit_loads(full_kit: Kit) -> None:
    assert full_kit.name == "placeholder-tabla"
    assert full_kit.schema_version == SCHEMA_VERSION


def test_every_stroke_resolves_in_every_shipped_kit(
    shipped_kits: tuple[Kit, ...], vocab: Vocabulary
) -> None:
    """The property the whole module is for, asserted against every kit we ship."""
    for kit in shipped_kits:
        assert vocab.missing_from(kit.stroke_names) == []
        for stroke in vocab.names:
            sample_set = kit.resolve_stroke(stroke)
            assert sample_set.samples, f"{kit.name}: {stroke} resolved to nothing"


def test_every_referenced_sample_is_on_disk(shipped_kits: tuple[Kit, ...]) -> None:
    for kit in shipped_kits:
        for stroke in kit.stroke_names:
            for i in range(len(kit.resolve_stroke(stroke).samples)):
                assert kit.sample_path(stroke, i).is_file()


def test_placeholder_round_robins_are_deep_enough(full_kit: Kit, vocab: Vocabulary) -> None:
    """Fewer than a handful and repeated bols machine-gun, which is the tell."""
    for stroke in vocab.names:
        assert len(full_kit.resolve_stroke(stroke).samples) >= 6


def test_sparse_kit_covers_everything_from_four_sample_sets(
    sparse_kit: Kit, vocab: Vocabulary
) -> None:
    """The many-to-one path, on a real fixture.

    This is the shape a bought sample pack arrives in: six usable sounds, a
    whole vocabulary to cover. If it works here it works for a bol -> 909 map.
    """
    owners = {sparse_kit.resolve_stroke(s).owner for s in vocab.names}
    assert len(owners) == 4
    assert vocab.missing_from(sparse_kit.stroke_names) == []


# -- the recorded kit, which is the default the UI loads --------------------


def test_recorded_kit_loads(real_kit: Kit) -> None:
    assert real_kit.name == "deolekar-tabla"
    assert real_kit.schema_version == SCHEMA_VERSION


def test_recorded_kit_is_first_alphabetically(vocab: Vocabulary) -> None:
    """How it becomes the default.

    `server.py` lists `kits/` sorted and `main.ts` selects the first entry, so
    the default kit is whichever sorts first. That is load-bearing and invisible
    -- renaming this directory would silently demote it.
    """
    loadable = sorted(p.name for p in KITS_DIR.iterdir() if (p / "kit.json").is_file())
    assert loadable[0] == "deolekar-tabla", (
        "the UI defaults to the first kit alphabetically; deolekar-tabla must sort first"
    )


def test_recorded_kit_has_deep_round_robins(real_kit: Kit, vocab: Vocabulary) -> None:
    for stroke in vocab.names:
        assert len(real_kit.resolve_stroke(stroke).samples) >= 8


def test_recorded_kit_covers_every_stroke_with_real_or_declared_material(
    real_kit: Kit, vocab: Vocabulary
) -> None:
    """Nine strokes are recordings; the one that is not says so out loud."""
    stand_ins = real_kit.stand_ins
    assert set(stand_ins) == {"ki"}
    recorded = [s for s in vocab.names if s not in stand_ins]
    assert len(recorded) == 9
    for stroke in recorded:
        assert real_kit.resolve_stroke(stroke).owner == stroke


def test_re_plays_its_own_recorded_material(real_kit: Kit) -> None:
    """`re` was an alias onto `te` and is now the dataset's `Tr` class.

    It matters because `re` is the quietest, shortest stroke in the vocabulary
    and the one buried inside `tirakita`. Playing a `te` there was audibly wrong
    -- too loud and roughly twice as long.
    """
    assert real_kit.alias_target("re") is None, "no longer a substitution"
    assert real_kit.resolve_stroke("re") is not real_kit.resolve_stroke("te")
    assert real_kit.resolve_stroke("re").owner == "re"
    assert len(real_kit.resolve_stroke("re").samples) >= 8


def test_re_is_quieter_than_te_after_gain(real_kit: Kit) -> None:
    """The musical relationship the ceilings encode: `re` is the ghost stroke."""
    assert real_kit.resolve_stroke("re").gain_db > real_kit.resolve_stroke("te").gain_db, (
        "raw `Tr` is quiet, so it needs MORE make-up gain than `te` -- "
        "if this inverts, the ceilings were edited without re-reading them"
    )


def test_stand_ins_are_visible_rather_than_audible_only(real_kit: Kit) -> None:
    """A substitution you can only find by ear is the failure mode here."""
    assert real_kit.stand_ins, "this kit still has one; the check is not vacuous"
    for stroke in real_kit.stand_ins:
        assert real_kit.note_for(stroke), f"{stroke} substitutes silently"
    assert real_kit.notes, "the kit as a whole should say it has stand-ins"


def test_stand_in_notes_reach_the_browser(real_kit: Kit) -> None:
    payload = json.loads(json.dumps(real_kit.to_dict()))
    assert payload["strokes"]["ki"]["notes"]
    assert payload["strokes"]["ki"]["owner"] == "ka"


def test_every_unverified_mapping_says_so(real_kit: Kit) -> None:
    """`re`, `dha` and `dhun` are inferences, not dataset labels.

    They are defensible and they are real audio, but none is a labelled match,
    so each has to carry a VERIFY that reaches the manifest and the browser.
    """
    for name in ("re", "ki"):
        assert "VERIFY" in real_kit.note_for(name).upper(), name
    for bol in ("dha", "dhun"):
        assert "VERIFY" in (real_kit.note_for(bol) or "").upper(), bol


def test_a_kit_of_real_recordings_has_no_stand_ins_by_default(full_kit: Kit) -> None:
    """Guards the other direction: `stand_ins` must not report false positives."""
    assert full_kit.stand_ins == {}


def test_recorded_composites_are_real_recordings(real_kit: Kit) -> None:
    """The point of the composite slot: a struck `dha`, not two one-shots summed."""
    dha = real_kit.resolve_composite("dha")
    assert dha is not None and dha.owner == "dha"
    assert len(dha.samples) >= 8
    assert dha.samples != real_kit.resolve_stroke("ge").samples
    assert dha.samples != real_kit.resolve_stroke("na").samples
    assert real_kit.resolve_composite("dhun") is not None


def test_recorded_composite_samples_exist(real_kit: Kit) -> None:
    for bol in real_kit.composite_names:
        for i in range(len(real_kit.resolve_composite(bol).samples)):
            assert real_kit.sample_path(bol, i).is_file()


def test_recorded_kit_carries_a_balance_rather_than_flat_levels(real_kit: Kit) -> None:
    """`gain_db` is where the cross-stroke balance lives, since the audio is untouched.

    All-zero gains would mean the source's inconsistent gain staging went
    straight through, and the bayan would be inaudible under the dayan.
    """
    gains = {s: real_kit.resolve_stroke(s).gain_db for s in real_kit.stroke_names}
    assert any(g != 0.0 for g in gains.values())
    assert gains["ge"] > gains["ti"], "the open bayan cannot sit under a damped dayan stroke"


def test_recorded_kit_ships_its_attribution(real_kit: Kit) -> None:
    """CC BY 4.0 obliges us. A kit directory without it is not redistributable."""
    license_text = (DEOLEKAR / "LICENSE.txt").read_text(encoding="utf-8")
    for required in ("Subodh Deolekar", "10.5281/zenodo.4327350", "CC BY 4.0",
                     "creativecommons.org/licenses/by/4.0", "MODIFICATIONS MADE"):
        assert required in license_text, f"LICENSE.txt is missing {required!r}"


def test_aliased_strokes_share_one_sample_set(sparse_kit: Kit) -> None:
    assert sparse_kit.resolve_stroke("tin") is sparse_kit.resolve_stroke("na")
    assert sparse_kit.alias_target("tin") == "na"
    assert sparse_kit.alias_target("na") is None, "a stroke with its own samples is not an alias"


def test_alias_chains_resolve(sparse_kit: Kit) -> None:
    """`re` -> `ti` -> `te`, two hops, in the kit that ships."""
    assert sparse_kit.alias_target("re") == "te"
    assert sparse_kit.resolve_stroke("re") is sparse_kit.resolve_stroke("te")


# -- coverage: the silent-dropout guard ------------------------------------


def test_missing_stroke_raises_naming_exactly_which(tmp_path: Path, vocab: Vocabulary) -> None:
    strokes = total_strokes(vocab)
    del strokes["re"]
    del strokes["tin"]
    path = write_kit(tmp_path, strokes)

    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)

    message = str(exc.value)
    assert "'re'" in message and "'tin'" in message
    assert "'na'" not in message, "only the uncovered strokes should be named"


def test_a_stroke_covered_only_by_an_alias_still_counts(
    tmp_path: Path, vocab: Vocabulary
) -> None:
    """Coverage is checked after alias resolution, or sparse kits could not exist."""
    strokes = total_strokes(vocab)
    strokes["re"] = {"alias_of": "te"}
    Kit.load(write_kit(tmp_path, strokes), vocab=vocab)


def test_unknown_stroke_key_is_rejected(tmp_path: Path, vocab: Vocabulary) -> None:
    """A kit supplying `dha` as a stroke has misunderstood; `dha` is a composite."""
    strokes = total_strokes(vocab)
    strokes["dha"] = {"samples": ["dha.wav"]}

    with pytest.raises(UnknownStrokeError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert "dha" in str(exc.value)


# -- aliases ---------------------------------------------------------------


def test_alias_cycle_raises(tmp_path: Path, vocab: Vocabulary) -> None:
    """A cycle claims a sound exists without ever supplying it."""
    strokes = total_strokes(vocab)
    strokes["te"] = {"alias_of": "ti"}
    strokes["ti"] = {"alias_of": "re"}
    strokes["re"] = {"alias_of": "te"}

    with pytest.raises(KitError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)

    message = str(exc.value)
    assert "cycle" in message
    assert "te" in message and "ti" in message and "re" in message


def test_alias_to_a_stroke_that_declares_nothing_raises(
    tmp_path: Path, vocab: Vocabulary
) -> None:
    """Reported as a dangling alias, not as `ti` being uncovered.

    Both are true, but the alias is the line you actually have to edit.
    """
    strokes = total_strokes(vocab)
    strokes["re"] = {"alias_of": "ti"}
    del strokes["ti"]

    with pytest.raises(KitError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert "'ti'" in str(exc.value) and "no samples" in str(exc.value)


def test_alias_cannot_carry_its_own_settings(tmp_path: Path, vocab: Vocabulary) -> None:
    """`alias_of` plus `gain_db` is a contradiction, not a layered override."""
    strokes = total_strokes(vocab)
    strokes["ti"] = {"alias_of": "te", "gain_db": -3.0}

    with pytest.raises(KitError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert "alias_of" in str(exc.value) and "gain_db" in str(exc.value)


# -- files on disk ---------------------------------------------------------


def test_missing_wav_raises_naming_the_file(tmp_path: Path, vocab: Vocabulary) -> None:
    strokes = total_strokes(vocab)
    strokes["na"] = {"samples": ["na.wav", "na_rr2.wav"]}
    path = write_kit(tmp_path, strokes, files=[f"{n}.wav" for n in vocab.names])

    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)

    message = str(exc.value)
    assert "na_rr2.wav" in message
    assert "'na'" in message, "the error should name the stroke that wanted it"


def test_sample_paths_cannot_escape_the_kit_directory(
    tmp_path: Path, vocab: Vocabulary
) -> None:
    strokes = total_strokes(vocab)
    strokes["na"] = {"samples": ["../elsewhere/na.wav"]}
    with pytest.raises(KitError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert "relative path" in str(exc.value)


def test_missing_manifest_is_a_clear_error(tmp_path: Path, vocab: Vocabulary) -> None:
    with pytest.raises(KitError) as exc:
        Kit.load(tmp_path, vocab=vocab)
    assert "not found" in str(exc.value)


# -- schema strictness -----------------------------------------------------


def test_unknown_manifest_key_raises(tmp_path: Path, vocab: Vocabulary) -> None:
    """kit.json is hand-authored; a typo that is ignored is a setting that does nothing."""
    path = write_kit(tmp_path, total_strokes(vocab), sample_rate_polcy="resample_on_load")

    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)
    assert "sample_rate_polcy" in str(exc.value)


def test_unknown_stroke_entry_key_raises(tmp_path: Path, vocab: Vocabulary) -> None:
    strokes = total_strokes(vocab)
    strokes["na"] = {"samples": ["na.wav"], "pitch_semitone": 2.0}

    with pytest.raises(KitError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert "pitch_semitone" in str(exc.value)


def test_notes_may_ride_along_with_an_alias(tmp_path: Path, vocab: Vocabulary) -> None:
    """The one key an alias may carry, because a compromise has to be able to say so."""
    strokes = total_strokes(vocab)
    strokes["ti"] = {"alias_of": "te", "notes": "no real ti recorded"}

    kit = Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert kit.note_for("ti") == "no real ti recorded"
    assert kit.note_for("te") == ""


def test_notes_must_be_a_string(tmp_path: Path, vocab: Vocabulary) -> None:
    strokes = total_strokes(vocab)
    strokes["na"] = {"samples": ["na.wav"], "notes": 12}
    with pytest.raises(KitError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert "notes" in str(exc.value)


@pytest.mark.parametrize("version", [0, 2, 99])
def test_wrong_schema_version_raises(
    tmp_path: Path, vocab: Vocabulary, version: int
) -> None:
    path = write_kit(tmp_path, total_strokes(vocab))
    manifest = json.loads((path / "kit.json").read_text())
    manifest["schema_version"] = version
    (path / "kit.json").write_text(json.dumps(manifest))

    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)
    assert str(version) in str(exc.value)
    assert str(SCHEMA_VERSION) in str(exc.value)


def test_absent_schema_version_raises(tmp_path: Path, vocab: Vocabulary) -> None:
    path = write_kit(tmp_path, total_strokes(vocab))
    manifest = json.loads((path / "kit.json").read_text())
    del manifest["schema_version"]
    (path / "kit.json").write_text(json.dumps(manifest))

    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)
    assert "schema_version" in str(exc.value)


def test_invalid_json_names_the_file(tmp_path: Path, vocab: Vocabulary) -> None:
    (tmp_path / "kit.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(KitError) as exc:
        Kit.load(tmp_path, vocab=vocab)
    assert "invalid JSON" in str(exc.value)


def test_unknown_sample_rate_policy_raises(tmp_path: Path, vocab: Vocabulary) -> None:
    path = write_kit(tmp_path, total_strokes(vocab), sample_rate_policy="whatever")
    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)
    assert "whatever" in str(exc.value)


def test_non_numeric_gain_raises(tmp_path: Path, vocab: Vocabulary) -> None:
    strokes = total_strokes(vocab)
    strokes["na"] = {"samples": ["na.wav"], "gain_db": "loud"}
    with pytest.raises(KitError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert "gain_db" in str(exc.value)


def test_empty_samples_list_raises(tmp_path: Path, vocab: Vocabulary) -> None:
    """An empty list is the exact shape of silence, so it is an error, not a default."""
    strokes = total_strokes(vocab)
    strokes["na"] = {"samples": []}
    with pytest.raises(KitError) as exc:
        Kit.load(write_kit(tmp_path, strokes), vocab=vocab)
    assert "samples" in str(exc.value)


# -- composites ------------------------------------------------------------


def test_composite_resolution_returns_the_dha_sample_set(full_kit: Kit) -> None:
    dha = full_kit.resolve_composite("dha")
    assert dha is not None
    assert dha.owner == "dha"
    assert len(dha.samples) >= 6


def test_composite_is_absent_rather_than_silent(sparse_kit: Kit) -> None:
    """No `dha` one-shot is fine -- the caller falls back to `ge` + `na`."""
    assert sparse_kit.resolve_composite("dha") is None
    assert sparse_kit.resolve_composite("") is None


def test_composite_resolves_alternate_spellings(full_kit: Kit) -> None:
    """A composition keeps whatever you typed, so `dhaa` has to reach `dha`."""
    assert full_kit.resolve_composite("dhaa") is full_kit.resolve_composite("dha")
    assert full_kit.resolve_composite("DHA") is full_kit.resolve_composite("dha")


def test_a_stroke_is_not_a_valid_composite_key(tmp_path: Path, vocab: Vocabulary) -> None:
    path = write_kit(
        tmp_path,
        total_strokes(vocab),
        composites={"ge": {"samples": ["ge.wav"]}},
    )
    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)
    assert "'ge'" in str(exc.value)


def test_a_non_simultaneous_bol_is_not_a_valid_composite_key(
    tmp_path: Path, vocab: Vocabulary
) -> None:
    """`tirakita` is four strokes in sequence, not one instant. It cannot be one sample."""
    path = write_kit(
        tmp_path,
        total_strokes(vocab),
        composites={"tirakita": {"samples": ["tirakita.wav"]}},
    )
    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)
    assert "tirakita" in str(exc.value)


def test_unknown_composite_bol_raises(tmp_path: Path, vocab: Vocabulary) -> None:
    path = write_kit(
        tmp_path,
        total_strokes(vocab),
        composites={"dhoop": {"samples": ["dhoop.wav"]}},
    )
    with pytest.raises(KitError) as exc:
        Kit.load(path, vocab=vocab)
    assert "dhoop" in str(exc.value)


# -- round robin -----------------------------------------------------------


def test_round_robin_cycles_deterministically(full_kit: Kit) -> None:
    samples = full_kit.resolve_stroke("te").samples
    picked = [full_kit.round_robin("te", i) for i in range(len(samples) * 3)]
    assert picked[: len(samples)] == list(samples)
    assert picked == [samples[i % len(samples)] for i in range(len(picked))]


def test_round_robin_covers_every_sample(full_kit: Kit, vocab: Vocabulary) -> None:
    """A round robin that never reaches sample 6 is six wasted recordings."""
    for stroke in vocab.names:
        samples = full_kit.resolve_stroke(stroke).samples
        reached = {full_kit.round_robin(stroke, i) for i in range(len(samples))}
        assert reached == set(samples)


def test_round_robin_is_a_pure_function_of_the_index(full_kit: Kit) -> None:
    """The browser owns the counter; selection has to be testable without it."""
    period = len(full_kit.resolve_stroke("na").samples)
    assert full_kit.round_robin("na", 41) == full_kit.round_robin("na", 41)
    assert full_kit.round_robin("na", 41) == full_kit.round_robin("na", 41 + period)


def test_round_robin_reaches_composites_too(full_kit: Kit) -> None:
    assert full_kit.round_robin("dha", 0) == full_kit.resolve_composite("dha").samples[0]


def test_round_robin_on_a_single_sample_never_moves() -> None:
    one = SampleSet(owner="re", samples=("re.wav",))
    assert {one.round_robin(i) for i in range(10)} == {"re.wav"}


def test_round_robin_of_an_unknown_name_raises(full_kit: Kit) -> None:
    with pytest.raises(KitError) as exc:
        full_kit.round_robin("wobble", 0)
    assert "wobble" in str(exc.value)


# -- midi overrides --------------------------------------------------------


def test_midi_override_is_none_when_the_kit_says_nothing(full_kit: Kit) -> None:
    """None, not a default. midi.py owns the canonical map and the merge."""
    assert full_kit.midi_override("ge") is None
    assert full_kit.midi_override("na") is None


def test_midi_override_is_partial(sparse_kit: Kit) -> None:
    """A kit moves the notes it cares about and inherits the rest."""
    assert sparse_kit.midi_override("ge") == 36
    assert sparse_kit.midi_override("na") is None


def test_midi_override_rejects_unknown_strokes(tmp_path: Path, vocab: Vocabulary) -> None:
    path = write_kit(tmp_path, total_strokes(vocab), midi_map={"dha": 36})
    with pytest.raises(UnknownStrokeError):
        Kit.load(path, vocab=vocab)


@pytest.mark.parametrize("note", [-1, 128, 36.5, "36"])
def test_midi_override_rejects_impossible_notes(
    tmp_path: Path, vocab: Vocabulary, note: object
) -> None:
    path = write_kit(tmp_path, total_strokes(vocab), midi_map={"ge": note})
    with pytest.raises(KitError):
        Kit.load(path, vocab=vocab)


# -- serialization ---------------------------------------------------------


def test_to_dict_is_fully_resolved(sparse_kit: Kit, vocab: Vocabulary) -> None:
    """The browser gets a flat table and re-implements none of the alias rules."""
    payload = json.loads(json.dumps(sparse_kit.to_dict()))
    assert set(payload["strokes"]) == set(vocab.names)
    assert payload["strokes"]["re"]["samples"] == payload["strokes"]["te"]["samples"]
    assert payload["strokes"]["re"]["owner"] == "te"
