# bolbox composition format

A plain-text format for tabla compositions. Readable by anyone who knows bols,
parseable without ambiguity, and precise enough that a machine can place every
stroke exactly on the grid.

This spec is frozen before any composition is typed. Typing thirty files in a
format you then change is the most expensive possible ordering.

---

## A complete example

```
tal: tintal
lay: 120
title: Tintal theka

dha  dhin dhin dha  | dha  dhin dhin dha  | dha  tin  tin  ta   | ta   dhin dhin dha
```

That is the whole format for simple material. Everything below is for the cases
that are not simple.

---

## Header

Key/value lines at the top of the file. Order does not matter. The header ends
at the first blank line or the first line that is not `key: value`.

| Key | Required | Meaning |
|---|---|---|
| `tal` | **yes** | Metric cycle. v1 accepts `tintal` only. |
| `lay` | no | Tempo in **matras per minute**. Default 60. The UI slider overrides it at playback without editing the file. |
| `title` | no | Free text. |
| `gharana` | no | Free text. Informs which lexicon variant to prefer, once variants exist. |
| `source` | no | Free text. Where you learned it. Worth filling in. |

`tal` is required even though v1 supports exactly one tal. It costs four
characters per file and it means that adding jhaptal, rupak or ektal later is a
table entry in `bolbox/tal.py` rather than a hand-edit of every file you own.

**Lay is matras per minute, not quarter notes per minute.** This is the tabla
convention. For tintal one matra is one quarter note, so the two happen to
coincide; for a tal whose matra is not a quarter they do not, which is why the
unit is stated rather than assumed.

---

## Body

One line per **avartan** (one full cycle). Blank lines are ignored. `#` starts a
comment, to end of line.

Within a line:

- **Whitespace separates matras.** One whitespace-delimited token occupies
  exactly one matra.
- **`|` separates vibhags.** Optional, but if present the vibhag widths must
  match the tal. For tintal that is 4 + 4 + 4 + 4. Getting this wrong is a
  parse error, which is the point: it catches a miscounted line immediately
  rather than after you have typed thirty of them.
- Every line must contain exactly the tal's matra count. **This is the format's
  central invariant** and the primary property test.

---

## Bols

A token is segmented into bols by **longest match** against
`data/lexicon.yaml`, scanning left to right, case-insensitively. Whitespace
separates matras; it does not separate bols.

```
tirakita     ->  one bol, four strokes, sharing one matra
dhage        ->  two bols (dha, ge) sharing one matra
tete         ->  two bols (te, te) sharing one matra
dha ge       ->  two matras
```

Longest match is what makes `tirakita` resolve as one word rather than as
`ti` + `ra` + `ki` + `ta`. It also means **an incomplete alias table changes
meaning silently rather than erroring** — if `tirakita` were missing from the
lexicon, `tirakita` would still segment, just into four one-stroke bols with the
same total duration but a different musical reading. Every contraction you
actually use belongs in `data/lexicon.yaml`. Adding one is a single line.

If no known bol starts at some position, parsing fails with the line, the
column, and the offending substring. Characters are never dropped.

### Composite bols

`dha`, `dhin` and `dhun` are single syllables produced by two strokes struck at
the same instant. They occupy one slot, emit two MIDI notes on one tick, and may
be replaced by a single recorded sample if the loaded kit provides one. That is
why the lexicon marks them `simultaneous: true` — see `data/lexicon.yaml`.

---

## Rests

`-` occupies its matra and produces nothing.

```
dha  -    dha  -    | ...
```

A rest inside a group works the same way and takes its share of the group.

---

## Groups: `{n, ... }`

A group packs several elements into **one matra**.

```
dha  {2, ti ra}  dhin  na   | ...
```

Here `{2, ti ra}` is the second matra, split evenly between `ti` and `ra`.

`n` must equal the number of elements in the group.

```
{3, a b c d}    ->  parse error: declared 3, found 4
```

**This deviates from Bol Processor deliberately.** In BP, `{k, ...}` means the
sequence spans *k* beats, so `k` is not derivable from the contents. Here `n` is
derivable, which makes it redundant — and that redundancy is the point. It is a
checksum on hand-typed material, and hand-typing is exactly what this corpus is.
A miscounted group is caught at the group rather than surfacing as a whole line
that fails to sum.

Groups nest to any depth:

```
{2, dha {4, te re ki ta}}   ->  one matra; first half `dha`,
                                second half four strokes
```

Group durations are exact rationals. `{2, dha {4, te re ki ta}}` puts those four
strokes at 1/2, 5/8, 3/4 and 7/8 of the matra — computed as fractions, never as
floating point, so a 7-way group lands exactly on sam and stays there for as
many repetitions as you care to loop.

---

## Accents

A suffix on a bol.

| Suffix | Meaning | Velocity |
|---|---|---|
| `!` | accent | +12 |
| `.` | ghost | −20 |

```
dha! dha  ti  ta  | ...
```

Baseline velocity is 100, `+12` on sam, `−20` on every matra inside a khali
vibhag. An explicit `!` or `.` overrides the positional default rather than
stacking with it, so what you typed is what you get.

---

## Errors

Every parse error carries a line, a column and the offending text:

```
line 4, column 23: declared 3 elements but found 4: '{3, ti ra ki ta}'
line 7, column 1: expected 16 matras, found 15
line 2, column 6: cannot segment 'dhaka' at offset 3: no known bol starts at 'ka'
```

Errors are never warnings and nothing is ever silently dropped. A composition
that parses is a composition that will play exactly as written.

---

## Full grammar

```
file        := header blankline body
header      := ( key ":" value newline )+
body        := ( avartan | comment | blank )+
avartan     := element+ ( "|" element+ )*
element     := bol | rest | group
bol         := surface accent?
surface     := [a-zA-Z]+          ; segmented by longest match on the lexicon
accent      := "!" | "."
rest        := "-"
group       := "{" integer "," element+ "}"
comment     := "#" .*
```
