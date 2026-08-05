# The workbench: a local surface for the human work

**Date:** 2026-08-04
**Status:** approved, not yet planned
**Supersedes:** Task 5 of `docs/superpowers/plans/2026-08-04-padhant-capture.md`

---

## Why this exists

bolbox has work only Sreshta can do — confirming stroke mappings by ear, reciting
padhant, labelling takes, and noticing when a bol has two realizations. Today
that work lives in `docs/YOUR-TURN.md`, a checklist, which has the failure mode
every checklist has: it goes stale the moment something is fixed without editing
it, and it can't play you a sound.

The workbench is a local page that shows what human work is outstanding,
computes most of it from the repo rather than a list, and lets it be done in
place: hear a mapping and confirm it, record a take and have it labelled.

It is deliberately **separate** from the composition app. Different job,
different surface, no mode toggle, no cross-linking. The composition app is
where you write and hear music; the workbench is where you do chores.

### The load-bearing reason to build it now

The recording session is the project's critical path, and it depends on a
vocabulary that has been confirmed by ear. Takes are labelled with bol text, so
a take recited as `tha` and labelled `ta` is permanently mislabelled data —
indistinguishable from good data once there are hundreds of takes, and fixable
only by re-recording.

Eight entries currently carry `verify: true`, and two of them (`din`'s
realizations) were invented rather than played. Confirming them is a
prerequisite. The workbench makes that prerequisite pleasant instead of a YAML
chore, and then makes the recording loop that follows pleasant too — which
matters, because a data collection instrument only produces data if it gets used.

---

## Scope

**In:**

1. A derived task list, refreshed from repo state.
2. Verify: hear a flagged mapping through the real kit, confirm or correct it,
   or split a bol into variants. Writes to `data/lexicon.yaml` / `data/strokes.yaml`.
3. Record: guided (prompt shown, take auto-labelled with it) and free (record
   now, label later).
4. Label: give an unlabelled take its bol text.

**Out, with reasons:**

- **Generated riyaz drills.** Chosen in discussion, then cut for v1: drills are a
  coverage optimisation, and there is no coverage problem until there are
  recordings. v1 prompts come from the corpus and from a paste box.
- **A standalone "invent a new bol" form.** Splitting an existing bol into
  variants stays, because that is the `din` case and the one actually hit.
  Creating a bol from nothing is rarer and is two lines of YAML.
- **Retrain / reindex.** There is no model. Building its trigger now would be
  inventing an interface for something that does not exist.
- **Kit editing, composition authoring, anything the composition app already does.**

All three cuts drop in later as one new task kind plus one panel; §2 is designed
so that is true.

---

## §0. Prerequisite: prove the round-trip before building on it

`data/lexicon.yaml` and `data/strokes.yaml` are heavily commented, and the
comments carry the reasoning — why `tha` is a bol rather than an alias, why `ki`
may be physically the same stroke as `ka`, what each `VERIFY` note asks. PyYAML
destroys all of it: load-and-dump takes the lexicon from 144 lines to 126 with
every comment gone and `ge: { strokes: [ge] }` expanded to four lines.

So writes go through `ruamel.yaml` in round-trip mode, a new dependency whose
only job is not vandalising those files.

**This is verified first, before anything is built on it.** The files mix flow
style (`{ strokes: [ge] }`) with block style, which is where round-trip libraries
sometimes reformat. The gate is a test asserting that load → dump with no changes
produces a **byte-identical** file.

If that test cannot be made to pass, direct writes are off the table and the
design falls back to the workbench proposing a diff for manual application. That
is a worse experience but an acceptable one, and it is far cheaper to discover
now than after three panels depend on it.

---

## §1. Placement

`web/workbench.html` plus `web/src/workbench/`, a second entry in the existing
Vite build, served at `/workbench`.

**Separate surface, shared engine.** The workbench imports `kit.ts`, `graph.ts`
and `export.ts` and nothing else from the composition app. Reimplementing
playback would mean two sample engines drifting apart, and the entire value of
the Verify panel is that it plays the *real kit* — the same samples that will
play when you use the thing for real. An approximation would be worse than
silence, because it would let you confirm a mapping against a sound you will
never hear again.

The composition app gains no link, no toggle, and no awareness of the workbench.

**It requires `bolbox serve`.** Every read and write goes through the Python
server. With no server, the workbench shows a single clear error rather than an
empty page.

---

## §2. One task model, two sources

Everything shown is a `Task`:

```python
@dataclass(frozen=True)
class Task:
    id: str        # stable across refreshes, so authored tasks can persist `done`
    kind: str
    title: str
    detail: str
    payload: dict  # kind-specific
```

**Derived tasks are computed on every request** and vanish when their condition
clears. That is what makes the list maintenance-free, and it is the property
worth protecting when new kinds are added.

| kind | appears when | payload |
|---|---|---|
| `verify_bol` | a bol has `verify: true` on any variant | bol name, variants, strokes |
| `verify_stroke` | a stroke has `verify: true` | stroke name, drum, damped |
| `label_take` | a recording has `bols: ""` | recording id, duration |

**Authored tasks** live in `data/human-tasks.yaml`, for work no query can find —
"deny the microphone permission and check the error reads clearly." Each has an
id, a title, a detail, and a `done` flag the workbench writes back.
`docs/YOUR-TURN.md` §3 becomes this file's first entries; the rest of that
document stays as prose, since narrative context is not a task.

Adding a new derived kind later is one function returning `list[Task]`,
registered in a list. `coverage` (a bol is under-represented in the dataset) and
`missing_sample` (a kit lacks a sample for a vocabulary stroke) are the two
obvious next ones and are explicitly not built now.

---

## §3. Verify

For a `verify_bol` task the panel shows the bol, each of its variants, and the
strokes each resolves to. Three actions:

- **Play** — each stroke individually, and the bol as a whole, through the
  currently selected kit.
- **Confirm** — removes the `verify: true` flag. The task disappears from the list.
- **Correct** — edit the stroke list, or split the bol into named variants.

Splitting is the `din` path and the reason variants exist: you discover mid-check
that one syllable is two realizations, and you record that without leaving the page.

`verify_stroke` is the same shape against `data/strokes.yaml`. Note that `ki`
currently plays `ka`'s sample by documented substitution — so pressing Play on
`ki` asks exactly the question the flag exists to ask, which is whether they are
the same physical stroke for you.

**Playing one stroke** goes through a thin `playStroke(kit, name)` adapter over
the existing `planNotes` / `renderEvents`, which take arrays of scheduled events.
Named here so nobody invents a parallel audio path for it.

### The staleness trap

`bolbox/server.py` loads `_VOCAB` and `_LEXICON` **once, at import**, and every
request reuses them. Without a fix, the workbench writes a confirmed mapping to
disk and `/api/pattern` keeps serving the old one until the server restarts — you
would confirm a correction and watch the app ignore it, or worse, record takes
against a vocabulary you believe you fixed.

Every successful write therefore reloads both singletons before returning. The
reload is part of the write, not a separate endpoint, so it cannot be forgotten.

---

## §4. Record and label

**Guided:** the workbench shows a prompt — a line from `data/compositions/`, or
text pasted into a box — you recite it, and the take is stored already labelled
with that exact text. No typing, and the label is exact by construction.

**Free:** record without a prompt. The take is stored unlabelled, which is a
legitimate state, and it reappears in the task list as a `label_take` task. This
is what makes recording fast: you can lay down six takes without stopping, and
the ones you did not label are tracked rather than lost.

**Label:** a `label_take` task shows the audio with a text box. Submitting it
`PATCH`es the recording.

Capture itself — `getUserMedia`, the AudioWorklet, PCM WAV encoding, and the
IndexedDB buffer that means a dead server never costs a take — is Tasks 1-4 of
`docs/superpowers/plans/2026-08-04-padhant-capture.md`, unchanged. This spec
replaces only that plan's Task 5, moving record mode out of the composition app.

**Ordering.** The capture plan's Tasks 1-4 must land before this spec's Record
and Label panels, which have nothing to call otherwise. The Verify panel and the
task list have no such dependency and could ship first. The implementation plan
should therefore sequence: capture Tasks 1-4 → workbench §0-§3 → workbench §4.
Task 5 of the capture plan is not to be built; a note in that file records why.

---

## §5. Endpoints

Added to `bolbox/server.py`, alongside the recording endpoints from the capture plan:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/tasks` | Derived + authored tasks, merged |
| `POST` | `/api/tasks/{id}/done` | Mark an authored task done |
| `POST` | `/api/lexicon/bols/{name}/confirm` | Clear `verify` on a bol |
| `PUT` | `/api/lexicon/bols/{name}` | Replace a bol's strokes or variants |
| `POST` | `/api/strokes/{name}/confirm` | Clear `verify` on a stroke |

Every write validates through `Lexicon.from_dict` **before** touching disk, so a
bad edit fails with the loader's own error message rather than producing a file
that no longer loads. Then it writes, then it reloads the server's singletons.

---

## §6. Testing

**Python:**
- The byte-identical round-trip gate from §0, on the real shipped files.
- Each derived task source, against fixture state: a flagged bol produces a task,
  clearing the flag removes it.
- Write endpoints: a confirm clears exactly one flag and leaves neighbouring
  comments intact; an invalid edit is rejected before the file changes.
- The staleness fix: write through the API, then read `/api/vocabulary` **in the
  same process** and see the new value. This test fails against the current
  import-time caching, which is the point.

**Browser:**
- Task rendering and the merge of derived and authored tasks, as pure functions.
- `playStroke` builds the right one-event plan for a given kit.

**End to end (Playwright, fake audio device):** open the workbench, confirm a
flagged mapping, see the task disappear; record a guided take and see it listed
with the prompt as its label.

---

## Risks

**ruamel may not round-trip these files byte-identically.** Mitigated by making
it §0 — the first thing built and the gate on everything else. Fallback is
propose-a-diff.

**The workbench is a detour from the recording session.** True, and worth
stating plainly: every task here could be done by editing two YAML files and
running `bolbox show`. The justification is that it makes the *recording* loop
pleasant, and an instrument that is unpleasant to use produces no data. If it
starts growing features that are not human-work surfaces, that is the signal it
has outlived this rationale.

**Writing to the repo's data files from a browser.** The server binds
`127.0.0.1` and this is a single-user local tool, so the exposure is small. But
validation-before-write and git as the undo mechanism are both load-bearing, and
neither is optional.
