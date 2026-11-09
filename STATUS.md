# STATUS — where bolbox actually stopped

**Audited:** 2026-11-09, against `bolbox.md`, `README.md`, `TODOS.md`,
`docs/YOUR-TURN.md` and the three plans and two specs under `docs/superpowers/`.

**The short version:** there are zero recordings, so the blocker is data. Nothing in
the repo can capture, import, store or label a recitation yet. There is no training
code, no decoder and no ONNX model. All of the ML half of `bolbox.md` (roadmap steps
2 and 3) is unbuilt, and so is roadmap step 1, the recording tool. The part that
does exist (text → grid → MIDI/audio) is solid and well tested.

Confidence tags: **[Certain]** = checked in the repo, **[Likely]** = strong
inference, **[Guessing]** = estimate with no measurement behind it.

---

## 1. What is built and runs

All of the following was run during the audit. [Certain]

| Piece | Where | State |
|---|---|---|
| Stroke vocabulary, single source of truth | `data/strokes.yaml`, `bolbox/vocab.py` | Built, tested |
| Lexicon: bols → strokes, aliases, **variants** (`din@full`) | `data/lexicon.yaml`, `bolbox/lexicon.py` | Built, tested |
| Composition format + parser (exact `Fraction` time, groups, rests, accents) | `bolbox/format.py`, `data/compositions/FORMAT.md` | Built, property-tested |
| Grid: bols → positioned strokes, compounds fill their slot | `bolbox/grid.py`, `bolbox/pattern.py` | Built, tested |
| MIDI renderer | `bolbox/midi.py` | Built, tested |
| Kit schema + 3 kits (real Deolekar CC-BY tabla, synthesized placeholder, sparse demo) | `bolbox/kit.py`, `kits/` | Built, tested |
| CLI: `check`, `show`, `render`, `serve` | `bolbox/cli.py` | Runs |
| FastAPI server: `/api/pattern`, `/api/midi`, `/api/vocabulary`, `/api/kits`, `/api/compositions` | `bolbox/server.py` | Runs |
| Browser sampler: pure `schedule()`, WebAudio graph, round robins, WAV export | `web/src/` | Runs |

Test results: `python -m pytest` gives **281 passed, 1 skipped**. `npx vitest run`
gives **61 passed**. I did not run the Playwright e2e suites (`web/e2e/`).

This is the "silent half" from `README.md`: you type bols and hear them. It is what
roadmap steps 4 and 5 call grid and sample engine, minus the `ge` pitch envelope,
dayan tuning and choke groups.

## 2. What is designed but not built

| Piece | Design doc | Code |
|---|---|---|
| Recording store (WAV + JSON sidecar per take) | capture plan Task 1 | **none**. No `bolbox/recordings.py` and no `data/recordings/` |
| Recording endpoints | capture plan Task 2 | **none** |
| Mic capture (AudioWorklet → PCM WAV) | capture plan Task 3 | **none**. Only `encodeWav` exists, in `web/src/export.ts` |
| IndexedDB "never lose a take" buffer | capture plan Task 4 | **none** |
| `Transcriber` seam / `NullTranscriber` | speech-capture spec §2 | **none** |
| `bolbox dataset` coverage report | speech-capture spec §3 | **none** |
| Workbench (verify by ear, record, label, import) | workbench spec + plan | **none** |

## 3. What is stubbed or absent: the whole ML path

[Certain] for every row: I grepped for torch, onnx, ctc, mel and librosa and found nothing.

| `bolbox.md` component | State |
|---|---|
| Mel spectrogram front end | absent |
| CNN/GRU encoder + CTC head | absent. Not even a model spec. |
| CTC output vocabulary | absent. `bolbox/vocab.py` says `vocab.json` is "generated, never hand-written", but nothing generates it. |
| n-gram / FST decoder | absent |
| Training / eval scripts | absent |
| ONNX export, ONNX Runtime Web, live mic path | absent. `onnxruntime` happens to be installed in this container, but the project does not use it. |

## 4. The data, counted

| Thing | Count |
|---|---|
| Recorded recitation clips in the repo | **0** [Certain] |
| Labeled clips | **0** [Certain] |
| Recitation audio anywhere else on this machine | **0** [Certain]. The only WAVs are the three drum kits and pytest fixtures. |
| Notated compositions (needed both as a recitation script and as the n-gram corpus) | **1 real** (`theka-tintal.txt`, one avartan). `demo-format-features.txt` says outright that it is not a real composition. |

The kit WAVs are struck drums, not speech. They must **never** go into the training
set: they would teach the model that the sound of a drum is the syllable `na`.
The workbench spec §7 already says this, and it is right.

If you have recordings on your laptop that were never committed, this audit cannot
see them. The 1b tool imports them (`bolbox label --import DIR`).

## 5. The single next blocker

**There is no labeled recitation audio, and until now nothing could get any into
the repo.**

Everything downstream needs (audio, bol text) pairs: CTC training, the confusion
analysis, the compound-bol eval and the ONNX export. The pairs do not exist, and
the instrument that produces them (capture plan Tasks 1–4) was never built. Step 1b
fixes the *import + label* half of that.

### Where I disagree with the repo's own gating

`docs/YOUR-TURN.md` says all of §1 (the 8 `verify: true` entries) must be fixed
before you record a single take. **I disagree because** the sidecar stores the bol
*text you recited* (`tirakita`), not the strokes. If `tirakita → te re ki ta` turns
out to be wrong, you fix one line in `lexicon.yaml` and every label re-expands. The
audio and the label are both still correct. [Likely]

The real gate is narrower. It covers only cases where the *spoken word itself*
could be mislabeled:

1. **Is the syllable you say in the lexicon at all?** `traka`, which you asked about
   for 1c, is **not in `data/lexicon.yaml`**. [Certain] Neither are `kran`, `dhet`,
   or the spelling `tirkita`. All three fail to tokenize today. (`dhage` is fine:
   it splits into `dha ge`.) The same goes for any bol from a composition you have
   not typed in yet.
   A label containing it fails to tokenize, and the 1b tool refuses to save it.
   Add it before you label clips that contain it.
2. **Spoken-unit identity for the CTC targets** (the next section). This one *does*
   affect training, and you need to decide it before 1c.

### A decision 1c needs from you: what is a CTC unit?

`bolbox.md` says "base syllables". The lexicon maps bols to **strokes**, and those
are not the same thing:

- `tirakita` → strokes `te re ki ta`, but you *say* "ti ra ki ta". If the CTC target
  for `tirakita` is the strokes, the label `te` gets trained on two different sounds:
  standalone "te", and the "ti" at the start of tirakita.
- `din@kinar` → stroke `na` and `din@full` → stroke `ta`. The variant is not in the
  audio, so the target has to be `din`, never its strokes.
- `tha` and `na` share a stroke but are spoken differently. They need separate units.

My recommendation: CTC units are the **non-compound bol names** (`dha dhin dhun din
ge ka ki na re ta te tha ti tin tun`, which is 15 plus blank). Compound bols expand
to their component syllables. Variants and accents are dropped. `bolbox/dataset.py`
(added in 1b) implements exactly this as `ctc_targets()`. It currently expands
compounds through their *strokes*, which gives the right syllables for `takita`,
`kitataka` and `takatira` but writes `tirakita` as `te re …`. If you say "ti", either
change the lexicon entry to `ti re ki ta` or give compounds a `spoken:` field.
That is a 10-line change, and it should happen before training.

### Minimum labeled set for a first CTC run

"First run" here means one thing: the model learns *something* on held-out audio,
and the per-class and compound numbers are not just noise. It does not mean good
enough to ship.

| Constraint | Floor | Reasoning |
|---|---|---|
| Total | **~120 clips, ~15–20 min** | A from-scratch CRNN-CTC with ~15 classes and one speaker. That is roughly 2–3k syllable tokens. Below that, a small CTC model tends to collapse to blanks or the majority class. [Guessing]: no measurement on this task. |
| Per base syllable | **≥ 50 occurrences in train** | Every unit has to be seen enough times to have its own emission. Theka-only data gives `dha`/`dhin`/`ta`/`tin` and *nothing else*. [Likely] |
| Per compound (`tirakita`, `kitataka`, `takita`, `takatira`, `traka`) | **≥ 60 occurrences total** | With a 15% test split that leaves about 9 in test, which is the bare minimum for the compound SER you asked for to mean anything. [Likely] |
| Material spread | **≥ 10 distinct compositions × 3 tempos** | Hold-out has to be by composition (below). With fewer than ~10 compositions, a 15% test split is one or two compositions, and the number swings on which ones they are. [Likely] |

Split note for 1c: **holding out by speaker is not possible.** v1 is deliberately
single-speaker, so there is one speaker. [Certain] Instead I'll hold out by
**composition**: all three tempos of a held-out composition go to test. Otherwise
the model, and especially the n-gram prior trained on the same corpus, gets
evaluated on sequences it memorised.

For comparison, the repo's own estimate is 30–45 min, assuming a pretrained encoder
(`docs/YOUR-TURN.md` §4). The 15–20 min above is the floor for a *first* run, not
that target.

## 6. Contradictions between docs that will bite in 1c/1d

1. **Encoder.** `bolbox.md` says a small CNN/GRU trained from scratch. The
   speech-capture spec says a "wav2vec2 fine-tune + CTC head". wav2vec2-base has
   ~95M params (~360 MB fp32, ~95 MB int8), and it is bidirectional unless you
   retrain it causal. For an in-browser, <150 ms target, the small CRNN is the
   realistic v1. Use wav2vec2 as a teacher or a later upgrade. [Likely]
2. **Latency target vs scope.** 1d asks for <150 ms perceived latency, live.
   `bolbox.md`'s scope decision is "loop station, not live instrument", and it gives
   the reason: compound bols cannot be placed until they finish. `docs/YOUR-TURN.md`
   §5 already says a `tirakita` "inherently costs its own duration". <150 ms is
   achievable for atomic bols with a causal model. It is **not achievable for
   compounds** in any architecture. 1d should report the two separately.
3. **n-gram corpus.** The decoder is meant to be trained "on the same notated
   corpus". That corpus is one line of theka. Typing the 50–80 compositions you plan
   to recite gives you the recitation script *and* the n-gram data, so it is not
   extra work.

## 7. Order of work from here

1. Add any bols you will recite that are missing (`traka` first).
2. Type ≥ 10 compositions into `data/compositions/`.
3. Record them, or bring in existing recordings, and label them with
   `bolbox label` (step 1b). Watch the coverage report until it shows the floors above.
4. Decide the CTC-unit question in §5.
5. Then 1c.

---

## Update: 1b done (labeling tool)

`python -m bolbox label --import DIR` imports takes and serves `/label`. See
README → "Labeling recordings". It includes capture-plan Tasks 1–2 (store and
endpoints). It does **not** include Tasks 3–4 (in-browser mic capture and the
IndexedDB buffer). Record with any app and import the files.

Pre-labeling is heuristic because there is no model. It works from onsets plus
the previous take and the corpus. When a CTC model exists, it replaces the draft
source in `prelabel()` (`bolbox/server.py`) and nothing else changes.
