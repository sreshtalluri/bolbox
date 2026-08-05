# Speech capture and the variant lexicon

**Date:** 2026-08-04
**Status:** approved, not yet planned
**Covers:** sub-projects 1 and 2 of the redirect (capture tool, lexicon variants)

---

## Why this exists

bolbox v1 shipped the silent half: you type bols as text, hear them in a sampler,
export MIDI. That was the right thing to build first and it works. But it is not
the product — the product is **speak, and get a composition back**, with playback,
and eventually in real time.

This spec redirects toward that. It does not throw v1 away: the parser, grid,
`Pattern`, MIDI renderer and browser sampler are all reused unchanged. What
changes is that text stops being the only way in.

Two findings drove the design and both came from playing the instrument, not
from reading the code.

### Finding 1: `ta`, `tha` and `na`

`data/strokes.yaml` currently carries a `verify: true` guess that `ta` and `na`
may be the same physical stroke, and the vocabulary has no `tha` at all. Both are
wrong. `tha` is the open ringing rim stroke — the same physical stroke as `na` —
and `ta` is distinct from it.

### Finding 2: one bol, several realizations

The same spoken bol can be produced by physically different strokes. `din` can be
struck full-handed, or with one finger on the edge for the open sound. You *say*
it identically either way.

This is the important one, because it splits "context" into two categories that
the current design conflates:

| | Recoverable from the recitation | Not recoverable, even in principle |
|---|---|---|
| **Example** | `tirkit` vs `tirakita`; the `ta` inside `takita` coarticulating | full-hand `din` vs edge-finger `din` |
| **Where it lives** | the audio signal | performance practice |
| **Who resolves it** | the acoustic model + a sequence prior | a default, or the player |

The second column breaks a load-bearing assumption. `data/lexicon.yaml` maps one
bol to exactly one stroke tuple and `grid.py::_expand` resolves it
deterministically. But a bol does not *have* a realization — it has a set of
them, and something outside the audio chooses.

No acoustic model can ever recover that choice, because the information is not in
the signal. So it must become an explicit, editable layer. Which is convenient,
because an editable layer over a recognized bol sequence is exactly the
note-taking tool this redirect is aiming at.

---

## Scope

**In:**

0. Vocabulary corrections (`ta` / `tha` / `na`).
1. Variant lexicon: named realizations per bol, one default, explicit override.
2. The `Transcriber` seam, with a null implementation.
3. Capture tool: record, store, label, play back; dataset coverage reporting.
4. Tests, including closing the coverage gap that let the tirakita bug ship.

**Out (each gets its own spec):**

- The acoustic model (wav2vec2 fine-tune + CTC head).
- Streaming decode and realtime playback.
- Choke / mute groups and sampler realism (`TODOS.md`).
- Any rules engine that *infers* a variant from context. See §2.

---

## Ordering constraint

**§0 must land before a single take is recorded.** Recordings are labeled with
bol text. A take recited as `tha` but labeled `ta` is permanently mislabeled
training data — it cannot be fixed later without re-recording, and it will be
indistinguishable from correct data once there are hundreds of takes.

Vocabulary errors are free today and expensive after 30 minutes of audio. This is
the only hard sequencing constraint in the spec.

---

## §0. Vocabulary corrections

### `data/strokes.yaml`

- Remove the `verify: true` note on `ta` speculating that it may be `na`. `ta` is
  its own stroke and keeps its own entry, kit slot and MIDI note.
- No new stroke is added for `tha`: it is the same physical stroke as `na`, and
  `strokes.yaml` holds physical strokes. Encoding it as a stroke would violate
  the file's stated single-source-of-truth rule ("One physical stroke, one
  entry here").

### `data/lexicon.yaml`

Add `tha` as **its own bol** resolving to the `na` stroke:

```yaml
tha: { strokes: [na] }
```

Not as an alias, which was the obvious move and is wrong. The alias table is
documented as holding "alternate spellings, not separate bols" — `ghe` and `gha`
are spellings of `ge`. `tha` is not a spelling of `na`; it is a **different
spoken syllable that happens to share a physical stroke**. Two bols mapping to
one stroke is already legal and breaks nothing downstream, since kits and MIDI
key on strokes.

The distinction is not pedantic, and it matters twice:

- An alias would set `Event.source_bol` to `na`, so a grid where you recited
  `tha` would display `na`. In a note-taking tool, showing you a syllable you did
  not say is a defect.
- The CTC output vocabulary is the bol set. `tha` and `na` *are* acoustically
  distinguishable, so the model should have both labels available. Collapsing
  them into one label at the lexicon layer would discard information the audio
  actually carries — the exact opposite of the §1 argument, where the variant is
  collapsed because the audio carries nothing.

Existing compositions are unaffected; no current file uses `tha`.

### Consequences

- `bolbox/midi.py`'s stroke→note map is unchanged (no new stroke).
- Kits are unchanged (`tha` plays the `na` sample).
- `GET /api/vocabulary` picks the new bol up automatically.

---

## §1. Variants

### `din` does not currently exist, and adding it settles an open question

The motivating bol is not in the lexicon at all. `scripts/make_deolekar_kit.py`
records why a downloaded sample class was left unused:

> `Di`: Pure dayan — under 2% of its energy is below 200Hz […] so despite the
> name it is a `din`, not a `dhin`, and it cannot be a composite. **bolbox has no
> `din` bol, and inventing one to consume a sample would be the vocabulary
> following the dataset instead of the instrument.** Left out.

That reasoning was right and it now resolves cleanly in the other direction:
`din` enters the vocabulary because **the instrument demands it** — you play it,
two ways — not because a sample was sitting there. The `Di` class becomes
legitimately usable as a consequence rather than as a motivation.

Wiring `Di` into `kits/deolekar-tabla/` is follow-on work, not part of this spec.
The stroke content of `din`'s variants needs your ear before any of it is real;
both ship marked `verify: true`.

### Schema

A bol gains an optional `variants` mapping. Exactly one variant is the default.

```yaml
din:
  variants:
    kinar:
      strokes: [na]
      default: true
      verify: true
      description: VERIFY -- one finger striking the edge. The open ringing sound.
    full:
      strokes: [ta]
      verify: true
      description: VERIFY -- full hand on the drum.
```

A bare `strokes:` remains valid and is sugar for a single default variant with
the reserved name `""`:

```yaml
ge: { strokes: [ge] }       # unchanged, still valid
```

`simultaneous`, `description` and `verify` move onto the variant, since two
realizations of one bol can legitimately differ in all three.

### Loader rules (`bolbox/lexicon.py`)

- A bol declaring both `strokes:` and `variants:` is an error.
- A bol declaring `variants:` with zero or several `default: true` is an error.
- Variant names are lowercase, non-empty, and may not contain `@` or whitespace.
- Every variant's strokes are validated against `Vocabulary` exactly as today.

### Backward compatibility

`Bol` keeps `.strokes`, `.simultaneous`, `.is_composite` and `.slot_count` as
**properties delegating to the default variant**. `grid.py`, `midi.py`,
`server.py` and every test keep working with no edit. That is what makes this
additive rather than a migration, and it is the main reason for this shape.

New surface: `Bol.variants` (ordered, default first) and
`Bol.variant(name) -> Variant`.

### Notation

`@` is unused by the composition format, so:

```
din@full            select a non-default variant
din@full!           composes with accents; the accent suffix stays outermost
dha@x ge            two matras, variant on the first
```

Binding rule inside a multi-bol token: `@name` binds to the bol match
immediately preceding it, and the scan resumes after the variant name. This is
unambiguous under the existing longest-match tokenizer because `@` can never
appear inside a surface form.

An unknown variant name is a `TokenizeError` carrying the offset, consistent
with how unknown bols already fail. It never silently falls back to the default —
a typo'd variant that silently played the default would be invisible.

`unparse` emits `@name` only for non-default variants, so the round-trip property
holds and existing files re-emit byte-identically.

### Through the pipeline

- `Event` gains `variant: str = ""` (`""` means default), alongside `source_bol`.
- `Pattern.to_dict()` emits it; `from_dict` defaults it, so stored patterns and
  older payloads load unchanged.
- The browser `PatternEventJSON` gains `variant?: string`.
- Kits may later key a sample on `din@full`. **Not implemented here** — kit
  lookup falls back to the stroke, exactly as today.

### The `gharana` header

`FORMAT.md` already documents `gharana` as "Informs which lexicon variant to
prefer, once variants exist." Reserved, still not implemented. Selecting a
default *set* of variants by gharana is a natural follow-on but needs a catalogue
of real variants first.

### Explicitly not building: variant inference

No rules engine that guesses the variant from context — no "din after dha is
usually edge-finger."

The catalogue of ambiguous bols does not exist yet; `din` is the one known case.
Encoding guesses about the rest would bake in precisely the kind of unsourced
assumption the `verify: true` flags exist to mark. The mechanism ships now so
cases can be recorded as they are found; rules can come later, from evidence.

### Why this layer sits where it does

The acoustic model will output **bols, never variants** — because the variant
genuinely is not in the audio. Variant selection is therefore a rendering
decision strictly above transcription, and it can never become the model's
problem. This is the layering that makes Finding 2 tractable instead of fatal.

---

## §2. The `Transcriber` seam

```
mic ──► Recording ──► Transcriber ──► proposed bols ──► [correct] ──► text ──► Pattern ──► playback
                          │
                          ├── now:   NullTranscriber  — proposes nothing
                          └── later: CTCTranscriber   — proposes a draft
```

Interface (browser-side, TypeScript — the model will run in-browser via ONNX
Runtime Web, per the stack decision in `bolbox.md`):

```ts
interface Transcriber {
  readonly id: string;
  /** Propose bol text for a recording. Empty string means "no proposal". */
  transcribe(audio: AudioBuffer, hint: { tal: string; lay: number }): Promise<string>;
}
```

`NullTranscriber.transcribe()` resolves to `""`. You type the label yourself.

**Why build the seam now.** With the null implementation the interaction is
"record, then type what you said" — which *is* the labeling step the training
data requires. It is not throwaway work; it is operating the data collection
instrument.

More importantly, **correction is the permanent shape of this UI**. Once the
model lands it proposes a draft and you fix its mistakes; the surface is
unchanged and one function is swapped. Building "type a composition" and
"correct a transcription" as separate screens would mean discarding one.

---

## §3. Capture tool

### Split of responsibility

Recording runs in the browser: `getUserMedia` → `AudioWorklet` → PCM →
`encodeWav()`, which already exists in `web/src/export.ts` and is reused as-is.

The server writes bytes to disk and nothing else. It still renders no audio, so
the locked "one audio engine" contract is untouched.

### Storage

One WAV plus one JSON sidecar per take, in `data/recordings/`:

```
data/recordings/2026-08-04T18-22-05-a1b2.wav
data/recordings/2026-08-04T18-22-05-a1b2.json
```

```json
{
  "id": "2026-08-04T18-22-05-a1b2",
  "recorded_at": "2026-08-04T18:22:05Z",
  "duration_sec": 7.41,
  "sample_rate": 48000,
  "bols": "dha dhin dhin dha | dha dhin dhin dha | ...",
  "tal": "tintal",
  "lay": 120,
  "click": true,
  "notes": ""
}
```

Sidecars rather than one index file: they diff cleanly in git, they can be
hand-edited, and a corrupt one loses a single take instead of the dataset.

`bols: ""` means **unlabeled**, which is a legitimate state (see below).

### Endpoints (`bolbox/server.py`)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/recordings` | multipart: WAV + metadata. Returns the id. |
| `GET` | `/api/recordings` | List metadata, newest first. |
| `PATCH` | `/api/recordings/{id}` | Update `bols`, `tal`, `lay`, `notes`. |
| `DELETE` | `/api/recordings/{id}` | Remove both files. |
| `GET` | `/recordings/{id}.wav` | Static mount, same shape as `/kits`. |

Every id is resolved and confined to `data/recordings/` using the same check as
`read_composition` (`server.py:179-181`). Same traversal risk, same fix. Ids are
server-generated and validated against a strict pattern; a client-supplied id is
never trusted as a path component.

`POST` rejects payloads over a configured size cap and non-WAV content.

### Three decisions worth stating

**Recording and labeling are separable.** You can lay down six takes and label
them later; `bols: ""` is valid. Forcing a label per take makes you stop and type
mid-flow, which is how a recording session becomes a chore you avoid. This tool
only produces data if you actually reach for it.

**A take is never lost to a server error.** Audio is written to IndexedDB before
upload and retried; pending takes are visible in the UI and survive a reload.
Losing a good take to a dead server is the most enraging failure available here
and it would permanently cost trust in the tool.

**`bolbox dataset` reports coverage, not just totals.** Minutes recorded, takes
labeled vs unlabeled, and **per-bol occurrence counts** derived by tokenizing
every label through the lexicon:

```
$ python -m bolbox dataset
28.4 min across 96 takes (81 labeled, 15 unlabeled)

  tirakita   41    dhun        3
  dha       380    takatira    0
  ...
```

This turns "record 30 minutes" into "record until the gaps close." Without it,
30 minutes weighted entirely toward tintal theka looks identical to 30 minutes
of good coverage, and the model would fail in a way that is very hard to
attribute.

### UI

One page, two modes — **Compose** (today's typing surface) and **Record** —
sharing the existing pattern view, lay slider, kit picker and transport.

Record mode: arm → count-in over the click at the current lay → record → the take
appears in a list. Selecting a take shows its audio, its (possibly empty) label,
and a variant control for any bol whose lexicon entry has more than one variant.
Editing the label re-parses through `/api/pattern`, so playback of a labeled take
is the existing player with no new audio code.

Mic permission denial surfaces in the existing error area with an actionable
message. Silence is not an acceptable failure here.

---

## §4. Testing

### Python

- Lexicon: variant loading, both error cases (both keys present; not exactly one
  default), name validation, alias-to-variant interaction.
- Two distinct bols resolving to one stroke (`tha` and `na`): both load, both
  keep their own `source_bol` through `grid()`, and both play the same sample.
- Backward compatibility: every existing lexicon entry loads and
  `Bol.strokes` returns the default variant's strokes.
- Tokenizer: `din@full`, `din@full!`, `@` binding inside a multi-bol token,
  unknown-variant `TokenizeError` offsets.
- Recording store: round-trip, metadata validation, path confinement (including
  `../` ids and absolute paths), size cap, delete removes both files.
- `dataset`: counts, unlabeled handling, tokenization of labels.

### Property tests (extending the existing `hypothesis` suite)

The unparse→parse identity property is extended to generate variant syntax, so
`din@full` must survive a round trip **exactly**. The duration-sums-to-cycle
invariant must continue to hold with variants present — a variant may change the
stroke count, which changes sub-slot division, so this is a real check and not a
formality.

### Web

- `Transcriber` interface with `NullTranscriber`, and the correction state as
  pure functions; `getUserMedia` and `MediaRecorder` mocked.
- IndexedDB buffering: a failed upload leaves a recoverable pending take.
- **Grid-label derivation moves out of `main.ts` into a tested pure function.**
  This is the gap that let the tirakita bug ship: `main.ts` has zero unit
  coverage, so a label repeated four times reached the browser undetected while
  `midi.py` had the correct rule (`bol_offset == 0`) and a test for it. The fix
  is already applied; this makes it stay fixed, and covers the `variant` field
  reaching the same label.

---

## Risks

**The 30-minute estimate is unvalidated.** Fine-tuning a pretrained
self-supervised encoder should cut the data requirement by roughly an order of
magnitude versus the from-scratch CNN/GRU in `bolbox.md`, but that is a
literature-based expectation, not a measurement on this task. `bolbox dataset`
exists partly so the answer is observable rather than assumed. If 30 minutes
proves insufficient, the capture tool is exactly what makes recording more cheap.

**The variant catalogue may be larger than one entry.** `din` is the known case.
If ambiguity turns out to be pervasive, labeling gets slower because each
ambiguous bol needs a decision. Mitigated by defaults: the default variant is
always applied, and overriding is opt-in.

**Encoder choice is deferred but constrains realtime.** A bidirectional encoder
decodes more accurately and can never stream. The decision recorded in
conversation is to train causal / limited-lookahead so streaming is a decode-mode
switch rather than a retrain. Nothing in this spec depends on it, but the model
spec must not silently pick bidirectional for the accuracy win.

---

## Out of scope, recorded so it is not re-litigated

- Sub-10ms live triggering. Unchanged from `bolbox.md`: you cannot separate `dha`
  from `ta` inside 10ms. Realtime here means streaming decode at roughly
  80–150ms, with compound bols inherently costing their own duration.
- Speaker independence. Single speaker, deliberately.
- Non-tabla kits, tals beyond tintal, the DAW plugin.
