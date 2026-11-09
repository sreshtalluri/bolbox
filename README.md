# bolbox

Speak tabla bols, get MIDI. Vocal percussion transcription with CTC over syllables.

**v1 is the silent half.** Type bols as text, hear them in a sampler, export MIDI.
No microphone, no model yet. That half has no research risk, it is the part you
would actually reach for while mixing, and it becomes the test harness that makes
the transcription half debuggable — without it, a bad loop could be the model, the
lexicon, or the grid, and you would have no way to tell which.

See [`bolbox.md`](bolbox.md) for the original design thinking.

---

## Quick start

The project uses **pyenv**. The environment is pinned by `.python-version`.

```bash
pyenv virtualenv 3.13.0 bolbox && pyenv local bolbox
pip install -e ".[dev]"
```

Validate a composition, look at its grid, render it:

```bash
python -m bolbox check  data/compositions/theka-tintal.txt
python -m bolbox show   data/compositions/theka-tintal.txt
python -m bolbox render data/compositions/theka-tintal.txt -o theka.mid
```

Run the server and open <http://127.0.0.1:8000>:

```bash
python -m bolbox serve
```

---

## Labeling recordings

```bash
python -m bolbox label --import ~/path/to/takes   # copy takes in (any format ffmpeg reads), then serve
open http://127.0.0.1:8000/label
python -m bolbox dataset --manifest data/manifest.jsonl   # coverage + one JSON line per trainable take
```

- Each take becomes `data/recordings/<id>.wav` + `<id>.json`. The `bols` field is the
  text you recited (`tirakita`, not its strokes). CTC targets are derived from it at
  training time by `bolbox.dataset.ctc_targets`.
- If `take.txt` sits next to `take.wav` on import, that text becomes the label.
- Re-importing a folder is safe: files already imported are skipped by hash.
- `BOLBOX_RECORDINGS=/some/backed-up/dir` moves the store out of the repo.
- The page pre-fills a draft: the take's saved label, else the previous take's label
  if its length fits the detected syllable count (tempo triples), else the closest
  corpus line. Onset ticks on the waveform carry the label's syllables, so a wrong
  count is visible at a glance.
- Keys: **Enter** save and next, **Esc** replay, **Tab** accept completion,
  **Alt+↓** next draft, **Alt+→** next without saving, **Alt+X** bad take,
  **Alt+S** 0.7× speed. The full list is on the page.

---

## Writing a composition

```
tal: tintal
lay: 120
title: Tintal theka

dha  dhin dhin dha  | dha  dhin dhin dha  | dha  tin  tin  ta   | ta   dhin dhin dha
```

One line per avartan, one whitespace token per matra, `|` between vibhags.
Compounds fill one matra: `dha tirakita dhin na`. Explicit groups nest:
`{2, dha {4, te re ki ta}}`. `-` is a rest, `!` accents, `.` ghosts.

Full spec: [`data/compositions/FORMAT.md`](data/compositions/FORMAT.md).

---

## How it fits together

```
composition text ──parse──► tree ──grid──► Pattern ──┬──► midi.py ──► .mid ──► your DAW
(FORMAT.md)                                          │
                                                     └──► browser ──► audio
recited audio (v2) ──align/quantize──────────────────┘                  │
                                                                        └──► WAV export
```

`Pattern` is the single source of truth. `midi.py` and the browser are
**independent renderers** of it — neither reads the other's output.

Three decisions hold this together, and all three are load-bearing:

**Positions are exact rationals in matras, never seconds.** Seconds are
tempo-derived render data. Storing them would mean a tempo change recomputes every
event and re-accumulates float error, and loops would stop landing on sam.
Rounding to a fixed MIDI tick grid has the same problem for odd tuplets: PPQ 1920
factors as 2⁷·3·5, so it represents 3-, 5-, 6- and 8-way splits exactly and
**cannot represent a 7-way one** — which tisra and khand need. So the time model is
`fractions.Fraction`, and rounding happens exactly once, at each renderer's
boundary.

**Events carry the bol they came from.** Without `source_bol`, a composite `dha` is
unreachable: once it is two strokes, the sampler cannot know it was ever a `dha`,
so it fires `ge` and `na` separately and a single recorded `dha` sample can never
play. That sample is the difference between sounding like a tabla and sounding like
tabla samples.

**One audio engine.** Playback and WAV export both run in the browser over the same
graph-building code — `AudioContext` for one, `OfflineAudioContext` for the other.
The exported file matches what you heard by construction rather than by keeping two
sample engines in agreement. The Python server never renders audio.

---

## Layout

| Path | What |
|---|---|
| `data/strokes.yaml` | Canonical stroke vocabulary. **Single source of truth.** |
| `data/lexicon.yaml` | Spoken bols → strokes, plus alternate spellings. |
| `data/compositions/` | The format spec and the corpus. |
| `bolbox/format.py` | Parser. Recursive, exact durations, positional errors. |
| `bolbox/grid.py` | Bols → positioned strokes. |
| `bolbox/pattern.py` | The `Pattern` contract both renderers read. |
| `bolbox/midi.py` | MIDI renderer. |
| `bolbox/kit.py` | Kit schema and validator. |
| `bolbox/server.py` | Local HTTP. Patterns and MIDI only, no audio. |
| `web/` | Browser: scheduler, playback, WAV export. |
| `kits/` | Sample kits. |

---

## Things that need your ear

Some mappings came from the design doc and general practice rather than a cited
source. They are marked `verify: true` in the data files so they can be found:

```bash
python - <<'PY'
from bolbox.lexicon import Lexicon
from bolbox.vocab import Vocabulary
v = Vocabulary.load()
print("strokes:", [s.name for s in v.needs_verification])
print("bols:   ", [b.name for b in Lexicon.load(vocab=v).needs_verification])
PY
```

The important one is **`tirakita` → `te re ki ta`**. Common readings differ on
whether the first stroke is `te` or `ti`, and on whether `ki` is a closed bayan
stroke (in which case it is physically the same stroke as `ka`). Everything
downstream reads `data/lexicon.yaml`, so fixing it there fixes it everywhere.

The default kit is real recorded tabla (see `kits/deolekar-tabla/`), but three of
its mappings are inferences rather than dataset labels, and each carries a
`VERIFY` note that reaches the manifest and the browser:

| Mapping | Why it is an inference |
|---|---|
| `re` ← class `Tr` | Not labelled `re`. Promoted because it is the shortest (72 ms) and quietest (peak 0.17) stroke in the set and sits spectrally with the closed dayan strokes — the profile `strokes.yaml` describes for a ring-finger flick. |
| `dha` ← class `Dh` | Real simultaneous material, 86% of its energy below 200 Hz, so the bayan is genuinely there. Which dayan stroke is in it does not resolve by measurement: it scores 0.46–0.63 against every candidate with no winner. |
| `dhun` ← class `Da` | The label `Da` is ambiguous. Its dayan component matches `Tu` and its bayan content is strong, so acoustically it reads as ge+tun. |

`ki` → `ka` is the one remaining substitution, and it is probably not a
compromise at all — `strokes.yaml` notes they are commonly the same physical
closed-bayan stroke.

Two dataset classes are deliberately unused, with reasons recorded in
`scripts/make_deolekar_kit.py`. The interesting one is `Di`: despite the name it
has under 2% of its energy below 200 Hz, so there is no bayan in it. It is a
`din`, not a `dhin`, and it cannot be a composite. It was left out when bolbox
had no `din` bol. bolbox has one now (`data/lexicon.yaml`, realizations `kinar`
and `full`) — added because the instrument has it, not to consume this sample —
so wiring `Di` in as a `din` realization is open work, gated on the `din`
variants losing their `verify` flags.

Recording your own tabla is still the highest-value thing you can do for how this
sounds — six or more round robins per stroke, a genuinely struck `dha`, a real
`re`, and sustained multi-pitch `ge` material for the pitch envelope that arrives
in v2. **That recording session is the one thing that cannot be synthesized
later**; the schema around it extends cheaply.

---

## Not in v1

Voice input, the acoustic model, practice mode, reverb, the `ge` pitch envelope,
tals beyond tintal, non-tabla kits, and the DAW plugin. See [`TODOS.md`](TODOS.md)
and the design doc for what is parked and why.

---

## Tests

```bash
python -m pytest          # Python
cd web && npx vitest run  # browser scheduler
```

The parser and grid are covered by property-based tests (`hypothesis`): every
generated composition's durations must sum to **exactly** the cycle length, and
unparse→parse must be the identity. Those are equalities rather than tolerances,
which is only possible because the time model is rational — and it is where that
choice earns its keep.
