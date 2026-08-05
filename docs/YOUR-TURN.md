# Your turn

Things only you can do, because they need a tabla and an ear. Everything here
blocks or degrades work I would otherwise do blind.

Ordering matters in one place and one place only: **everything in §1 must be
right before you record a single take.** Recordings are labelled with bol text,
so a take recited as `tha` but labelled `ta` is permanently mislabelled data —
indistinguishable from good data once there are hundreds of takes, and only
fixable by re-recording.

---

## §1. Correct the vocabulary by ear — blocks recording

Eight entries are flagged as unverified. See them any time with:

```bash
python -m bolbox check data/compositions/theka-tintal.txt   # sanity check the toolchain
python - <<'PY'
from bolbox.lexicon import Lexicon
from bolbox.vocab import Vocabulary
v = Vocabulary.load(); lex = Lexicon.load(vocab=v)
for s in v.needs_verification: print("stroke", s.name, "-", s.description.strip()[:90])
for b in lex.needs_verification: print("bol   ", b.name, "->", " ".join(b.strokes))
PY
```

Everything downstream reads `data/strokes.yaml` and `data/lexicon.yaml`, so a
fix in those files is a fix everywhere. Delete the `verify: true` line once
you have confirmed an entry.

### The two I invented — check these first

- [ ] **`din@kinar` → `[na]`** — one finger striking the edge, for the open ringing sound.
- [ ] **`din@full` → `[ta]`** — full hand on the drum.
- [ ] **Is `kinar` the right default?** I guessed it is the more common reading. If `full` is what you mean when you just say "din", swap `default: true` in `data/lexicon.yaml`.

These are in `data/lexicon.yaml` under `din:`. They came from your description,
but I chose the strokes — they are the least trustworthy thing in the repo.

### The central one

- [ ] **`tirakita` → `te re ki ta`.** The whole project is organised around this word. Readings differ on whether the first stroke is `te` or `ti`, and on whether `ki` is a closed bayan stroke — in which case it is physically the same as `ka`. Fix it in `data/lexicon.yaml`.

### The rest

- [ ] `takita` → `ta ki ta`
- [ ] `kitataka` → `ki ta ta ka`
- [ ] `takatira` → `ta ka te re`
- [ ] `dhun` → `ge + tun` (simultaneous)
- [ ] **stroke `ti`** — may be identical to `te` for you. If so, delete the entry from `data/strokes.yaml` and add `ti: {alias_of: te}` to the lexicon aliases.
- [ ] **stroke `ki`** — same question against `ka`.

### One judgement call

- [ ] `data/strokes.yaml`'s `ta` entry no longer carries `verify: true`, on your word that `ta` and `na` are distinct and that `tha` is the one sharing `na`'s stroke. If you want that auditable later, add a clause to its description saying you confirmed it by ear and when.

---

## §2. Find more `din`-shaped cases — grows the catalogue

You said there are "small things like this" beyond `din`, and that you would
need to hunt for them. `din` is currently the **only** multi-variant bol in the
lexicon.

What you are looking for: **a bol you recite identically but play two different
ways.** Not a spelling variant, not a tempo contraction — a genuine fork in
which physical stroke you make.

The test that separates it from the other kind of context-dependence: if you
can hear the difference *in the recitation*, the model will learn it and it
does not belong here. If you cannot, it belongs here.

- [ ] Play through your repertoire and note every bol where you make that choice.
- [ ] For each, add a `variants:` block to `data/lexicon.yaml` following `din`'s shape, with `verify: true` until you are sure.

You do not need to find them all before recording. Each one you find *first*,
though, is one you do not have to re-label later — and if a bol turns out to be
ambiguous after you have recorded fifty takes of it, those takes are ambiguous too.

Try it now to see the mechanism work:

```bash
python -m bolbox show data/compositions/theka-tintal.txt
# then edit a line to use din@full and re-run — the strokes should change
```

---

## §3. When the capture tool lands — test it before trusting it

I will build it against Chromium with a fake audio device, which proves the
plumbing but proves nothing about *your* microphone, room, or voice. These are
the checks that need a human.

- [ ] **Mic permission denial says so.** Deny the permission and confirm you get a readable error, not a dead button.
- [ ] **A take plays back and sounds like you.** Not thin, not clipped, not half-speed.
- [ ] **Levels.** Recite a loud `dha` and check it does not clip. Capture is deliberately raw — no AGC, no noise suppression, no echo cancellation, because those eat percussion transients — so **your input gain is not being fixed for you.** Set it once and leave it.
- [ ] **Kill the server mid-session, record two more takes, restart it.** Both takes should upload on their own. This is the failure I most want to be wrong about; if a take is ever lost, tell me immediately — that is a bug, not a limitation.
- [ ] **Reload the page with an unsent take pending.** It should still be there.
- [ ] **Confirm the WAV is real.** `file data/recordings/*.wav` should say PCM, and the sample rate should match your interface.

---

## §4. The recording session — the actual critical path

Not yet. This waits on §1 being done and the capture tool existing. Written
down now so the shape is not a surprise.

Target is roughly **30–45 minutes** of your voice, on the assumption that
fine-tuning a pretrained speech encoder needs an order of magnitude less data
than training from scratch. That number is an expectation from the literature,
not a measurement on this task — the coverage report exists so we find out
rather than guess.

- [ ] Recite from written notation, so the label is exact and free.
- [ ] Three tempos per composition — slow, medium, fast. Tempo variation is real here, not augmentation.
- [ ] **Spread across material, not repetitions.** 30 minutes of tintal theka looks identical to 30 minutes of good coverage until the model fails and you cannot tell why.
- [ ] Include the compound bols deliberately — `tirakita`, `takita`, `kitataka`, `takatira`. They are the hard case and the reason this project is interesting.
- [ ] Record `din` both ways, labelled `din` and `din@full`. Those two are indistinguishable in the audio, which is the whole point — the model must learn to output `din` and let you choose the realization.

`bolbox dataset` will tell you which bols are thin. Record until the gaps close
rather than until the clock says 30 minutes.

---

## §5. Decisions I will need from you

- [ ] **Do you want a click during recording?** A detected tempo is less intrusive but less exact; a click gives clean tempo metadata and a grid to quantize against, at the cost of playing to a metronome.
- [ ] **Speaker independence — ever?** v1 is deliberately single-speaker: personalisation removes most of the variance a general model would need a large corpus to handle. If you ever want other people using this, say so before the model spec, because it changes the data plan completely.
- [ ] **Realtime latency you would actually accept.** You said "as you say it, it plays." Realistically that is 80–150ms for simple bols, and a compound like `tirakita` inherently costs its own duration — you cannot know it was a `tirakita` until it is over. Is that still the thing you want, or is the notebook the real product?
