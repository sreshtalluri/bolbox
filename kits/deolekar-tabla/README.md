# deolekar-tabla — real recorded tabla, the default kit

Recordings of a real tabla played by professional players, tuned to C#.
This is the kit the UI loads by default. `placeholder-tabla` remains as a
synthesized offline fallback and `sparse-demo` as the alias-path fixture.

## Attribution

> "Tabla strokes dataset" by Subodh Deolekar (2020), licensed under Creative Commons Attribution 4.0 International (CC BY 4.0). Source: https://zenodo.org/records/4327350 (DOI 10.5281/zenodo.4327350). Modified for bolbox: takes selected, trimmed, downmixed to mono.

Full license terms, the complete list of modifications, and a per-file
provenance table are in [LICENSE.txt](LICENSE.txt). Keep that file with
the audio — CC BY 4.0 requires the attribution to travel with it.

## What is real and what is not

110 WAVs: 11 sample sets, up to 10 round robins each.

| bolbox | source class | real recording? |
|--------|--------------|-----------------|
| `ge` | `Ge` | yes |
| `ka` | `Ka` | yes |
| `na` | `Na` | yes |
| `tin` | `Tin` | yes |
| `tun` | `Tu` | yes |
| `ta` | `Ta` | yes |
| `ti` | `Ti` | yes |
| `te` | `T` | yes |
| `re` | `Tr` | yes |
| `dha` (composite) | `Dh` | yes |
| `dhun` (composite) | `Da` | yes |
| `ki` | — | **no — plays `ka`** |

So 9 strokes and 2 composites are genuine recordings, and
1 strokes are substitutions. The substitutions are `alias_of`
entries with a `notes` string, so they are visible in `kit.json`, in
`Kit.stand_ins`, and in the manifest the browser loads — you should never
have to discover one by ear.

**`re` is the one that will bother you.** The dataset has no ring-finger
flick, so `re` plays `te`: too loud, too long, and wrong inside
`tirakita`, which is the single most important thing this project has to
get right. Recording your own `re` is the highest-value thing you can do
to this kit.

## Levels

No sample here has been normalized, gained or compressed — the audio is
bit-faithful to the source. The dataset's classes were gain-staged very
inconsistently (`Ge` peaks near -19dBFS, `Na` is pinned at full scale),
so the musical balance lives in `gain_db` in `kit.json` and is applied at
playback. If the bayan is too loud for you, that is one number in a text
file, not a re-render:

```
  ge    gain_db +17.10
  ka    gain_db +10.03
  na    gain_db  -1.04
  tin   gain_db  +0.81
  tun   gain_db  +5.96
  ta    gain_db  +1.69
  ti    gain_db  -5.52
  te    gain_db  -2.25
  re    gain_db  +3.72
  dha   gain_db +15.35 (composite)
  dhun  gain_db +16.42 (composite)
```

## Regenerating

```
python scripts/make_deolekar_kit.py
```

Downloads the dataset to `.cache/` on first run, then works offline. The
selection rule is deterministic, so regenerating is never a diff.

## Still worth recording yourself

This kit is a real tabla, but it is not *your* tabla, and it is one drum
at one tuning. `kits/placeholder-tabla/README.md` has the full list of
what to capture; the short version is a real `re`, a `dha` played the way
you play it, and sustained `ge` material for the v2 pitch envelope.
