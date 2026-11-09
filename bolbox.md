# bolbox

Turn spoken tabla bols into playable percussion. You recite a phrase, it transcribes the syllables, quantizes them to a grid, and emits MIDI plus audio.

## Why this problem is tractable

Tabla is the rare percussion tradition with a canonical spoken vocabulary that maps one to one onto strokes. Reciting a composition out loud before playing it (padhant) is standard practice. That gives three things generic beatbox transcription does not have:

1. A closed, phonetically distinct label set.
2. Free labels. Compositions are already notated as bol text, so a recorded recitation plus its written transcript is a labeled example with zero manual annotation.
3. Strong sequence structure. Bol sequences are highly constrained, so a language model over them cleans up acoustic errors.

## Scope decision: loop station, not live instrument

Rejected: fire a sample the instant an onset is detected.

Reason: you cannot distinguish dha from ta inside the first 10ms, and percussionists notice timing error at roughly that threshold. Live triggering forces a choice between bad timing and bad classification.

Compound bols settle it. To place the four strokes of `tirakita` in time you have to know the subdivision they occupy, which means you need tempo and beat position, which a live trigger does not have. So:

- User records a phrase over a click or a detected tempo.
- Transcribe, quantize to a grid, expand compounds into stroke slots.
- Play back the corrected pattern on the next loop.

Latency stops mattering. Output is an editable pattern rather than a stream of triggers. Live mode stays possible later as a degraded fast path, but it is not v1.

## Why compound bols break the obvious approach

At 200bpm in sixteenths, `tirakita` is four strokes in about 300ms. Vowels collapse, the /r/ is a flap with almost no energy, and there is often no measurable onset between `ti` and `ra`. Onset detection will not reliably find four events.

Worse, `tirakita`, `takitira`, `kitataka` and `takitaka` are permutations of the same phoneme inventory. Any feature representation that averages over the window (MFCC means, bag of features) makes them near identical vectors. The time axis is the only thing separating them and it has to be preserved.

Also rejected: treating each compound as its own atomic class. Works, but requires enumerating every compound in advance and fails on anything novel or partial.

## Architecture

**Model.** Mel spectrogram in, CNN or GRU encoder, CTC head. Output vocabulary is base syllables plus blank:

```
dha dhin dhun na ta ti tin tun te re ki ta ka ge ke
```

CTC is the right fit because it needs only the utterance and its transcript, not frame level alignment. That is exactly what the notation gives you.

**Lexicon.** Pronunciation dictionary mapping surface forms to stroke sequences. `tirakita`, `tirkit` and `trkt` all resolve to the same four strokes. Needed because realization varies by tempo and gharana.

**Decoder.** Beam search with an n-gram or FST prior over bol sequences, trained on the same notated corpus. `tira` is followed by `kita` overwhelmingly often, so the acoustic model does not have to carry the whole burden of separating permutations.

**Grid.** Map the decoded sequence onto subdivisions of the detected tempo. Compounds fill their slot count.

**Output.** MIDI first, audio second. MIDI plugs into a DAW, a HandSonic, or any sample library, and it stops sound quality from being on the critical path. Note that dha and dhin are two simultaneous strokes and emit two notes.

## Data plan

Single speaker to start. Personalization removes most of the variance a general model would need a large corpus to handle, and calibration is a legitimate product feature rather than a workaround.

- Recite 50 to 80 known compositions from written notation, three tempos each.
- Store (audio, bol text) pairs. Roughly two to four hours of recording.
- Augment with tempo perturbation, which is semantically valid here since bols genuinely are performed across a wide tempo range.

## Sample engine

Tabla is not a one shot sample instrument and a naive sampler will sound obviously wrong to anyone who knows the instrument. Plan for this from the start, not as a later fix:

- Round robins so repeated bols do not machine gun.
- Pitch envelope on `ge`, since the bayan gliss comes from heel pressure.
- Tunable dayan so `na`, `tin` and `ta` sit in the working key.

## Stack

- Prototype and train in Python.
- Export to ONNX, run in the browser via ONNX Runtime Web.
- Audio path in an AudioWorklet, not the main thread.
- Avoid Python in the runtime audio path. GIL and GC jitter is not worth debugging.

## Open question, unresolved

Is this a composition tool or a padhant practice tool?

- **Composition tool.** Sketch grooves by voice when hands or gear are unavailable. Bigger audience, tolerates errors better.
- **Practice tool.** CTC output plus a target transcript gives edit distance for free, so you get a cleanliness score with no extra modeling. Sharper product, deeper moat, smaller audience.

This changes UI, evaluation metric, and arguably the name. Decide before building past the recording tool.

## Two projects, decided 2026-11-09

These are separate ideas that share a subject, not two versions of one system.

**1. bolbox (this repo): speak bols, get notation.** Recited bols are transcribed
into the composition format with tal and grid, then played back or exported. The
accurate one. Everything in this document describes it.

- Data: own voice plus the IIT Bombay Tabla Bol Recitation Dataset (non-commercial
  research licence) to start. Friends later, first as held-out test speakers.
- Speaker independence is an eventual goal, no longer a permanent non-goal. v1
  still ships single-speaker; every take is tagged with its speaker so the split
  is possible later.

**2. Voice-to-tabla instrument (not started, no code here).** Speak or beatbox and
hear tabla-like sound almost immediately, through a neural audio model (RAVE, or
the low-latency BRAVE variant) trained on 1-2 hours of clean solo tabla. The
expressive one: it follows timing and timbre, and does not guarantee that a spoken
`dha` comes out as a dha stroke. Inspired by Manaswi Mishra's work at the MIT
Media Lab (https://www.youtube.com/watch?v=VJHuIgLQx9Q): a "tiny" AI trained on
1-2 hours of percussion recordings, in "just the language and timbres of one small
dataset", built to help performers express rather than to be correct. The video
does not name the model, so RAVE/BRAVE is an inference. The earlier planning notes
for this idea have not been located.

What they share: tabla audio and an ear for it. What they do not share: model,
training data (labelled speech vs unlabelled drum audio), or runtime. Project 2
should live in its own repo.

## Roadmap

1. Recording and notation tool. Record utterance, paste bol text, store the pair. No ML. Start here.
2. Mel spectrogram, CNN/GRU, CTC. Base syllables only.
3. Lexicon and n-gram decoder.
4. Grid quantization and MIDI output.
5. Sample engine with round robins, ge envelope, tuning.
6. Later: speaker independence, other kits, live mode.

## Non-goals for v1

- Speaker independent recognition.
- Non tabla kits.
- Sub 10ms live triggering.
- Polyphonic or overlapping input.

## Prior art worth reading

Automatic drum transcription. Tabla bol transcription (published work out of IIT Bombay). Konnakol and solkattu recognition, which is the Carnatic version of the same problem. Adaptive vocal percussion literature for the calibration approach.
