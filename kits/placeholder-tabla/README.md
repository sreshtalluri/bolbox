# placeholder-tabla — SYNTHESIZED. NOT RECORDINGS.

> Not the default kit any more. `kits/deolekar-tabla/` is real recorded tabla and is
> what the UI loads; this one stays as the offline fallback, since it needs no
> download and no third-party license. Everything below still applies, and the
> advice on recording your own drum applies to both kits.


Every WAV in this folder came out of `scripts/make_placeholder_kit.py`. Nothing here
was played on a drum. They are additive-synthesis stand-ins: a few near-harmonic
modes with exponential decay for the resonant strokes, band-limited noise and a click
for the damped ones, and a downward pitch glide on `ge`.

They exist so the sequencer is audible on day one. If the scheduler is written against
silence, every timing bug looks exactly like a missing sample and you lose an evening
finding out it wasn't. These are good enough to hear whether a `tirakita` landed on the
right subdivision. They are not good enough to keep, and they will sound wrong to you
immediately, which is the point.

**No third-party audio is in this folder.** Everything is generated from scratch by a
script in this repo, so there is no license to honour and nothing to attribute. Treat
it as public domain.

## Regenerating

```
python scripts/make_placeholder_kit.py
```

One fixed seed, so this is byte-for-byte reproducible — regenerating is never a diff.
It rewrites `kits/sparse-demo/` too. Nothing at runtime needs numpy; the WAVs are
written with the stdlib `wave` module and read back by the browser.

## What is here

10 strokes × 6 round robins, plus 3 composite one-shots × 6.

| stroke | drum  | length | what it is                                        |
|--------|-------|--------|---------------------------------------------------|
| `ge`   | bayan | 550ms  | 82Hz fundamental gliding down from ~45% sharp     |
| `ka`   | bayan | 160ms  | damped thud, low band-limited noise                |
| `ki`   | bayan | 100ms  | shorter, brighter damped bayan                     |
| `tun`  | dayan | 600ms  | C#4 (277Hz), fundamental strongest, longest ring   |
| `na`   | dayan | 450ms  | rim: 2nd mode strongest, 555Hz dominant            |
| `tin`  | dayan | 420ms  | 3rd mode strongest                                 |
| `ta`   | dayan | 350ms  | like `na`, shorter — see the note below            |
| `te`   | dayan | 100ms  | damped, 800Hz–6kHz noise + click                   |
| `ti`   | dayan | 85ms   | damped, brighter                                   |
| `re`   | dayan | 65ms   | damped, quietest by a wide margin                  |

Composites `dha`, `dhin` and `dhun` are the *sum* of their component renders at the
same round-robin index — `dha_rr3.wav` really is `ge_rr3.wav` + `na_rr3.wav`. That
makes `Kit.resolve_composite()` demonstrable end to end rather than theoretical.

`ta` and `na` are rendered as different sounds even though they may be the same
physical stroke for you (see the `verify: true` note in `data/strokes.yaml`). Keeping
them distinct here means a mis-mapped kit is audible instead of invisible.

## Replacing these with your own tabla

This is the part that actually matters. When you record:

- **6+ round robins per stroke, minimum.** Fewer and repeated bols machine-gun, which
  is the single most obvious tell of a sampled tabla. More is better for `te`, `re`,
  `ti` and `ki` specifically — they are the strokes that repeat fastest, inside
  `tirakita`, so they are where machine-gunning is most audible.
- **A real recorded `dha`.** Not `ge` and `na` played together in the DAW — struck
  together on the drum. The bayan and dayan couple physically and the sum of two
  one-shots does not reproduce it. Same for `dhin`. Drop them in `composites` and the
  sampler will fire one voice instead of two automatically.
- **Sustained and multi-pitch `ge` material.** v2 wants a real pitch envelope for the
  heel-pressure bend. Record `ge` at several bend positions and hold each one long
  enough to loop — a single decaying one-shot cannot be bent convincingly after the
  fact.
- **Velocity layers if you have the patience.** Not in the v1 schema, but recording
  them costs one more pass and adding the field later is free.
- **Match the levels you hear.** `re` really is much quieter than `tun`. If you
  normalize every stroke to the same peak the kit will sound wrong in a way that is
  hard to diagnose later.

Keep the filenames or don't — `kit.json` names them explicitly. Anything the manifest
references has to exist or the kit refuses to load, which is deliberate: a kit that
loads is a kit that makes a sound for every stroke in `data/strokes.yaml`.

If you only have a handful of usable sounds, you do not need to fake the rest. Use
`alias_of` and say so out loud — see `kits/sparse-demo/kit.json` for the shape.
