# TODOS

Deferred work with enough context to pick up cold. Added by `/plan-eng-review`.

---

## Choke / mute groups in the kit schema

**Status:** deferred to v2
**Added:** 2026-08-03 (eng review of the bolbox design doc)

**What.** Let a kit declare that certain strokes cut off certain others. A closed dayan
stroke silences a ringing `na`; a damped bayan cuts a sustaining `ge`.

**Why.** On a real tabla, strokes physically interact because your hand is already on the
drum. A sampler that lets every stroke ring out over the next one sounds obviously wrong to
anyone who plays, in a way that round robins do not fix. v1 has a per-stroke voice cap of 4
with a 20ms release on steal — that handles voice *count*, not cross-stroke *damping*. They
are different problems and the voice cap does not solve this one.

Surfaced by the Codex outside voice during eng review, which named it as the hardest tabla
sampling problem and correctly noted the v1 spec ignores it.

**Current state.** Kit format is versioned JSON (eng review D6 / D11), so adding a
`choke_groups` field later is structurally free. The browser scheduler is a pure function
`schedule(pattern, bpm, nowSec, windowSec) -> events[]` (D9), unit-tested with vitest.
Choke handling adds cross-event state, so it either extends that signature or lives in the
WebAudio layer that consumes its output — decide which before writing it, because the
purity of `schedule()` is what makes the timing tests possible.

**Where to start.** `bolbox/kit.py` schema, plus whichever layer you pick in `web/`.
A `choke_groups: [["ge", "ke"], ["na", "te"]]` shape is probably enough — strokes in a
group cut each other.

**Depends on.** Nothing blocking, but do it *after* recording your own kit. You need real
sustaining `ge` and `na` samples to hear whether the choke rules are musically right, and
guessing at them against placeholder samples wastes the iteration.
