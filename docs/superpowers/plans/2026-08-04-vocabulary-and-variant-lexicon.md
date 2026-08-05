# Vocabulary Corrections and the Variant Lexicon — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the `ta`/`tha`/`na` vocabulary, and make a bol resolve to one of several named physical realizations rather than to exactly one stroke tuple.

**Architecture:** A new `Variant` dataclass holds what `Bol` used to hold (strokes, `simultaneous`, `description`, `verify`). `Bol` becomes a name plus an ordered tuple of variants, default first, and keeps `.strokes` / `.simultaneous` / `.is_composite` / `.slot_count` as properties delegating to the default — so every existing caller in `grid.py`, `midi.py` and `server.py` compiles and passes unchanged. Variant selection rides through the pipeline as a plain string (`""` = default) from tokenizer to `PlacedBol` to `Event` to JSON.

**Tech Stack:** Python 3.13 (pyenv, `.python-version`), pytest + hypothesis, PyYAML, FastAPI. TypeScript + vitest in `web/`.

## Global Constraints

- Environment is **pyenv**, pinned by `.python-version`. Never `python3 -m venv`, never system pip.
- `data/strokes.yaml` is the single source of truth for physical strokes. Nothing else may introduce a stroke name.
- Positions are exact `fractions.Fraction` in matras, never seconds and never floats.
- The Python server renders no audio. This plan adds no exception.
- Mappings not backed by a cited source are marked `verify: true`. New `din` variants ship flagged.
- Variant names: lowercase, non-empty, no `@`, no whitespace. The empty string `""` is reserved for the implicit default of a bare `strokes:` entry.
- Run the full suite (`python -m pytest`) at every "run tests" step, not just the new file. The point of the delegating-property design is that existing tests keep passing; a plan step that only runs the new test cannot observe that.
- **Task 1 must land before any padhant is recorded.** Recordings are labeled with bol text; a take recited as `tha` and labeled `ta` is permanently mislabeled data.

---

### Task 1: `tha` enters the vocabulary, `ta` stops being a guess

`tha` is the open ringing rim stroke — the same *physical stroke* as `na` — but a
different *spoken syllable*. It becomes its own bol pointing at the `na` stroke,
not an alias, so `Event.source_bol` preserves the syllable you actually recited.
No new stroke is added: `strokes.yaml` holds physical strokes, and `tha` is not one.

**Files:**
- Modify: `data/strokes.yaml:64-72` (the `ta` entry)
- Modify: `data/lexicon.yaml:29-42` (the simple-bol block)
- Test: `tests/test_lexicon.py`

**Interfaces:**
- Consumes: nothing.
- Produces: bol `tha` resolving to stroke `na`; stroke `ta` with `verify` removed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lexicon.py`:

```python
# -- ta / tha / na ----------------------------------------------------------


def test_tha_is_its_own_bol_not_an_alias(lex: Lexicon) -> None:
    """`tha` and `na` share a stroke but are different syllables.

    An alias would canonicalise `tha` to `na`, so a grid where you recited
    `tha` would display `na` -- showing a syllable that was never said. It
    also matters for the CTC vocabulary later: `tha` and `na` ARE acoustically
    distinguishable, so both belong in the label set.
    """
    assert lex.resolve("tha").name == "tha"
    assert lex.resolve("na").name == "na"
    assert lex.strokes_for("tha") == ("na",)
    assert lex.strokes_for("na") == ("na",)


def test_ta_is_a_distinct_stroke_from_na(vocab: Vocabulary) -> None:
    """The old `verify` note speculated ta and na might be one stroke. They are not."""
    assert "ta" in vocab
    assert vocab["ta"].verify is False
    assert vocab["ta"] != vocab["na"]


def test_tha_and_na_keep_their_own_source_bol_through_the_grid() -> None:
    """Two bols, one stroke. The syllable you recited survives to the Event.

    This is the payoff of not aliasing: the sampler fires the same `na` sample
    for both, but the grid and any future transcription still say which was said.
    """
    from bolbox.format import parse
    from bolbox.grid import grid

    pattern = grid(parse(
        "tal: tintal\nlay: 120\n\ntha na - - | - - - - | - - - - | - - - -\n"
    ))
    assert [e.source_bol for e in pattern.events[:2]] == ["tha", "na"]
    assert [e.stroke for e in pattern.events[:2]] == ["na", "na"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lexicon.py -k "tha_is_its_own_bol or ta_is_a_distinct" -v`
Expected: FAIL — `TokenizeError` on `"tha"`, and `assert True is False` on `vocab["ta"].verify`.

- [ ] **Step 3: Add the `tha` bol**

In `data/lexicon.yaml`, in the `# --- simple` block, directly after the `ta:` line:

```yaml
  ta:   { strokes: [ta] }
  tha:  { strokes: [na] }
```

Add the comment above the simple block explaining why this is not an alias:

```yaml
  # --- simple: one syllable, one stroke -----------------------------------
  #
  # `tha` and `na` are two bols sharing one physical stroke. That is legal and
  # deliberate: the alias table holds alternate SPELLINGS (`ghe` for `ge`), and
  # `tha` is not a spelling of `na` -- it is a different spoken syllable. An
  # alias would canonicalise it away, so a grid would show `na` where you
  # recited `tha`, and the CTC label set would lose a distinction the audio
  # genuinely carries.
```

- [ ] **Step 4: Remove the `ta`/`na` speculation from the stroke vocabulary**

Replace the `ta:` entry in `data/strokes.yaml` (lines 64-72) with:

```yaml
  ta:
    drum: dayan
    damped: false
    description: >
      Struck dayan stroke, distinct from `na`. An earlier note here guessed
      that `ta` and `na` might be one physical stroke; they are not. The bol
      `tha` is the one that shares `na`'s stroke, and it lives in the lexicon.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest -v`
Expected: PASS, whole suite.

No existing test needs updating. `tests/test_vocab.py` makes no assertion about
which strokes carry `verify`, and `tests/test_lexicon.py:170` asserts only that
`"tirakita"` appears in `lex.needs_verification` — a bol, not a stroke.

- [ ] **Step 6: Commit**

```bash
git add data/strokes.yaml data/lexicon.yaml tests/test_lexicon.py
git commit -m "Add tha as its own bol; ta is a distinct stroke

tha is the open ringing rim stroke -- the same physical stroke as na, but a
different spoken syllable, so it is a bol rather than an alias. An alias would
set source_bol to na and show a syllable that was never recited.

Removes the verify note speculating that ta and na are one stroke."
```

---

### Task 2: `Variant`, `Bol` as a set of realizations, and `din`

`din` is added here rather than later because Tasks 4 and 5 parse `din@full`
against the real default lexicon. It is also the only multi-variant bol that
ships, so it is what gives this task's loader tests something real to load.

**Files:**
- Modify: `bolbox/lexicon.py:39-66` (the `Bol` dataclass), `bolbox/lexicon.py:113-141` (the loader loop)
- Modify: `data/lexicon.yaml`
- Test: `tests/test_lexicon.py`

**Interfaces:**
- Consumes: Task 1's lexicon.
- Produces:
  - `Variant(name: str, strokes: tuple[str, ...], simultaneous: bool = False, description: str = "", verify: bool = False)` with properties `is_composite: bool`, `slot_count: int`.
  - `Bol(name: str, variants: tuple[Variant, ...])` with `default: Variant`, `variant(name: str) -> Variant`, and delegating properties `strokes`, `simultaneous`, `is_composite`, `slot_count`, `description`, `verify`.
  - `Bol.variant("")` returns the default.
  - Unknown variant name raises `LexiconError`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lexicon.py`:

```python
# -- variants ---------------------------------------------------------------

VARIANT_YAML = """
version: 1
bols:
  ge:  { strokes: [ge] }
  din:
    variants:
      kinar: { strokes: [na], default: true }
      full:  { strokes: [ta] }
"""


def _lex(text: str, vocab: Vocabulary) -> Lexicon:
    return Lexicon.from_dict(yaml.safe_load(text), vocab, source="<test>")


def test_bare_strokes_becomes_one_unnamed_default_variant(vocab: Vocabulary) -> None:
    """Existing entries keep working. This is what makes the change additive."""
    bol = _lex(VARIANT_YAML, vocab).resolve("ge")
    assert len(bol.variants) == 1
    assert bol.variants[0].name == ""
    assert bol.strokes == ("ge",)          # delegates to the default
    assert bol.simultaneous is False


def test_default_variant_is_first_and_drives_the_delegating_properties(
    vocab: Vocabulary,
) -> None:
    bol = _lex(VARIANT_YAML, vocab).resolve("din")
    assert [v.name for v in bol.variants] == ["kinar", "full"]
    assert bol.default.name == "kinar"
    assert bol.strokes == ("na",)          # NOT ("ta",)
    assert bol.variant("").strokes == ("na",)
    assert bol.variant("full").strokes == ("ta",)


def test_unknown_variant_names_the_ones_that_exist(vocab: Vocabulary) -> None:
    bol = _lex(VARIANT_YAML, vocab).resolve("din")
    with pytest.raises(LexiconError) as exc:
        bol.variant("edge")
    assert "edge" in str(exc.value)
    assert "kinar" in str(exc.value)       # tells you what IS available


@pytest.mark.parametrize(
    "body, expected",
    [
        ("{ strokes: [ge], variants: { a: { strokes: [ka] } } }", "both"),
        ("{ variants: { a: { strokes: [ka] }, b: { strokes: [ge] } } }", "default"),
        ("{ variants: { a: { strokes: [ka], default: true },"
         "              b: { strokes: [ge], default: true } } }", "default"),
        ("{ variants: {} }", "non-empty"),
        ("{ variants: { 'a@b': { strokes: [ka], default: true } } }", "@"),
        ("{ variants: { 'A': { strokes: [ka], default: true } } }", "lowercase"),
    ],
)
def test_malformed_variant_entries_are_rejected(
    body: str, expected: str, vocab: Vocabulary
) -> None:
    text = f"version: 1\nbols:\n  x: {body}\n"
    with pytest.raises(LexiconError) as exc:
        _lex(text, vocab)
    assert expected in str(exc.value)


def test_every_shipped_bol_still_loads(lex: Lexicon) -> None:
    """The real lexicon, through the new loader. Guards the migration."""
    for bol in lex:
        assert bol.variants, bol.name
        assert bol.default is bol.variants[0]
        assert bol.strokes == bol.default.strokes


def test_din_ships_with_two_realizations_both_flagged_for_verification(
    lex: Lexicon,
) -> None:
    """The motivating case. Strokes are inferences until played -- hence verify."""
    din = lex.resolve("din")
    assert [v.name for v in din.variants] == ["kinar", "full"]
    assert din.default.name == "kinar"
    assert din.strokes == ("na",)
    assert all(v.verify for v in din.variants)
    assert din in lex.needs_verification
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lexicon.py -k variant -v`
Expected: FAIL — `AttributeError: 'Bol' object has no attribute 'variants'`.

- [ ] **Step 3: Add `Variant` and rewrite `Bol`**

In `bolbox/lexicon.py`, replace the `Bol` dataclass (lines 39-66) with:

```python
@dataclass(frozen=True)
class Variant:
    """One physical realization of a bol.

    This holds what `Bol` used to hold. It exists because a bol does not have
    *a* realization -- `din` is struck full-handed or with one finger on the
    edge, and you SAY it identically either way. The choice is not in the audio,
    so it cannot be the acoustic model's problem; it is a rendering decision
    that lives here and is overridable in the notation.

    ``name`` is `""` for the implicit default of a bare `strokes:` entry.
    """

    name: str
    strokes: tuple[str, ...]
    simultaneous: bool = False
    description: str = ""
    verify: bool = False

    @property
    def is_composite(self) -> bool:
        return self.simultaneous and len(self.strokes) > 1

    @property
    def slot_count(self) -> int:
        """How many sequential sub-slots this realization occupies."""
        return 1 if self.simultaneous else len(self.strokes)


@dataclass(frozen=True)
class Bol:
    """One spoken syllable or word, and the realizations it can take.

    ``variants`` is ordered with the default first. The strokes/simultaneous
    properties delegate to it, which is what lets grid.py, midi.py and every
    existing test keep working untouched.
    """

    name: str
    variants: tuple[Variant, ...]

    @property
    def default(self) -> Variant:
        return self.variants[0]

    def variant(self, name: str) -> Variant:
        if not name:
            return self.default
        for candidate in self.variants:
            if candidate.name == name:
                return candidate
        known = ", ".join(v.name for v in self.variants if v.name) or "(none)"
        raise LexiconError(
            f"bol {self.name!r} has no variant {name!r}; known variants: {known}"
        )

    # -- delegating to the default ----------------------------------------

    @property
    def strokes(self) -> tuple[str, ...]:
        return self.default.strokes

    @property
    def simultaneous(self) -> bool:
        return self.default.simultaneous

    @property
    def is_composite(self) -> bool:
        return self.default.is_composite

    @property
    def slot_count(self) -> int:
        return self.default.slot_count

    @property
    def description(self) -> str:
        return self.default.description

    @property
    def verify(self) -> bool:
        """True if ANY realization needs a player's ear."""
        return any(v.verify for v in self.variants)
```

- [ ] **Step 4: Rewrite the loader**

In `bolbox/lexicon.py`, replace the body of the `for name, body in entries.items():`
loop (lines 114-141) with:

```python
        for name, body in entries.items():
            if not isinstance(name, str) or not name.islower():
                raise LexiconError(f"{source}: bol names must be lowercase strings")
            if not isinstance(body, dict):
                raise LexiconError(f"{source}: bol {name!r} must map to a mapping")

            has_strokes = "strokes" in body
            has_variants = "variants" in body
            if has_strokes and has_variants:
                raise LexiconError(
                    f"{source}: bol {name!r} declares both `strokes` and "
                    "`variants`; use one or the other"
                )

            if has_variants:
                variants = _parse_variants(name, body["variants"], vocab, source)
            else:
                variants = (_parse_variant(name, "", body, vocab, source),)

            bols[name] = Bol(name=name, variants=variants)
```

Add these module-level helpers to `bolbox/lexicon.py`, above the `Lexicon` class:

```python
def _parse_variants(
    bol: str, raw: object, vocab: Vocabulary, source: str
) -> tuple[Variant, ...]:
    """Parse a `variants:` mapping. Exactly one entry must be the default.

    The default is returned FIRST, because every delegating property on `Bol`
    reads `variants[0]`.
    """
    if not isinstance(raw, dict) or not raw:
        raise LexiconError(f"{source}: bol {bol!r} `variants` must be a non-empty mapping")

    parsed: list[Variant] = []
    defaults: list[str] = []
    for name, body in raw.items():
        if not isinstance(name, str) or not name:
            raise LexiconError(f"{source}: bol {bol!r} has an empty variant name")
        if name != name.lower():
            raise LexiconError(
                f"{source}: bol {bol!r} variant {name!r} must be lowercase"
            )
        if "@" in name or any(c.isspace() for c in name):
            raise LexiconError(
                f"{source}: bol {bol!r} variant {name!r} may not contain "
                "'@' or whitespace -- '@' is the notation's variant separator"
            )
        if not isinstance(body, dict):
            raise LexiconError(
                f"{source}: bol {bol!r} variant {name!r} must map to a mapping"
            )
        if body.get("default"):
            defaults.append(name)
        parsed.append(_parse_variant(bol, name, body, vocab, source))

    if len(defaults) != 1:
        raise LexiconError(
            f"{source}: bol {bol!r} must mark exactly one variant `default: true`; "
            f"found {len(defaults)} ({', '.join(defaults) or 'none'})"
        )

    ordered = sorted(parsed, key=lambda v: v.name != defaults[0])
    return tuple(ordered)


def _parse_variant(
    bol: str, name: str, body: dict, vocab: Vocabulary, source: str
) -> Variant:
    where = f"{source}: bol {bol!r}" + (f" variant {name!r}" if name else "")

    strokes = body.get("strokes")
    if not isinstance(strokes, list) or not strokes:
        raise LexiconError(f"{where} needs a non-empty `strokes`")
    if not all(isinstance(s, str) for s in strokes):
        raise LexiconError(f"{where} strokes must be strings")

    # The single-source-of-truth check: every target must be a real stroke.
    vocab.require(strokes, source=where)

    simultaneous = bool(body.get("simultaneous", False))
    if simultaneous and len(strokes) < 2:
        raise LexiconError(f"{where} is marked simultaneous but has one stroke")

    return Variant(
        name=name,
        strokes=tuple(s.lower() for s in strokes),
        simultaneous=simultaneous,
        description=str(body.get("description", "")).strip(),
        verify=bool(body.get("verify", False)),
    )
```

Note `sorted(..., key=lambda v: v.name != defaults[0])` is a stable sort on a
boolean, so the default moves to index 0 and every other variant keeps its file
order.

- [ ] **Step 5: Add `din` to the lexicon**

`din` is not currently a bol. `scripts/make_deolekar_kit.py:161-165` records a
sample class deliberately left unused because "bolbox has no `din` bol, and
inventing one to consume a sample would be the vocabulary following the dataset
instead of the instrument." That reasoning was right; `din` enters now because
the instrument demands it, and the sample becomes usable as a consequence.

In `data/lexicon.yaml`, add a new block after the simple bols and before the
composites:

```yaml
  # --- variants: one syllable, several possible strokes --------------------
  # A bol with more than one physical realization. You say these identically
  # whichever way you play them, so the recitation carries no information about
  # which was meant -- and neither will the transcription model. The choice is
  # a rendering decision, defaulted here and overridable in the notation with
  # `din@full`.

  din:
    variants:
      kinar:
        strokes: [na]
        default: true
        verify: true
        description: >
          VERIFY -- one finger striking the edge, for the open ringing sound.
          Marked default because it is the more common reading; confirm both
          the choice of default and the stroke by playing them.
      full:
        strokes: [ta]
        verify: true
        description: VERIFY -- full hand on the drum.
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS, including every pre-existing test. If `test_lexicon.py` or
`test_grid.py` fails, the delegating properties are wrong — fix the property,
not the caller. Outside `data/lexicon.yaml`, no file but `bolbox/lexicon.py`
should need an edit in this task.

- [ ] **Step 7: Commit**

```bash
git add bolbox/lexicon.py data/lexicon.yaml tests/test_lexicon.py
git commit -m "A bol resolves to one of several named realizations

Variant holds what Bol used to hold. Bol becomes a name plus an ordered tuple
of variants, default first, with strokes/simultaneous/slot_count delegating to
the default so every existing caller is untouched.

Adds din, the motivating case: struck full-handed or with one finger on the
edge, and recited identically either way -- so no acoustic model can ever
recover the choice, and it has to be an explicit layer instead. Both
realizations ship marked verify; the strokes are inferences until played."
```

---

### Task 3: `@variant` in the tokenizer

All `@` handling lives in `lexicon.py`, next to the longest-match scanner. The
parser learns nothing about variants beyond widening one regex (Task 4).

**Files:**
- Modify: `bolbox/lexicon.py` (`tokenize`, `strokes_for`, add `Segment`)
- Modify: `bolbox/format.py:203-216` (`_place`)
- Test: `tests/test_lexicon.py`

**Interfaces:**
- Consumes: Task 2's `Bol` / `Variant`.
- Produces:
  - `Segment(bol: Bol, variant: Variant)` — frozen dataclass.
  - `Lexicon.tokenize(token: str) -> tuple[Segment, ...]` (**return type changed** from `tuple[Bol, ...]`).
  - `PlacedBol.variant: str` — the variant *name*, `""` for default.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lexicon.py`:

```python
# -- @variant notation ------------------------------------------------------


def test_variant_suffix_selects_a_realization(vocab: Vocabulary) -> None:
    segments = _lex(VARIANT_YAML, vocab).tokenize("din@full")
    assert len(segments) == 1
    assert segments[0].bol.name == "din"
    assert segments[0].variant.name == "full"
    assert segments[0].variant.strokes == ("ta",)


def test_bare_bol_selects_the_default(vocab: Vocabulary) -> None:
    segments = _lex(VARIANT_YAML, vocab).tokenize("din")
    assert segments[0].variant.name == "kinar"


def test_variant_binds_to_the_preceding_bol_in_a_multi_bol_token(
    vocab: Vocabulary,
) -> None:
    """`dinge` is two bols in one matra. The suffix binds to the one before it."""
    segments = _lex(VARIANT_YAML, vocab).tokenize("din@fullge")
    assert [s.bol.name for s in segments] == ["din", "ge"]
    assert [s.variant.name for s in segments] == ["full", ""]


def test_unknown_variant_is_a_tokenize_failure_not_a_silent_default(
    vocab: Vocabulary,
) -> None:
    """A typo'd variant that quietly played the default would be invisible."""
    with pytest.raises((TokenizeError, LexiconError)) as exc:
        _lex(VARIANT_YAML, vocab).tokenize("din@edge")
    assert "edge" in str(exc.value)


@pytest.mark.parametrize("bad", ["@full", "din@", "din@@full"])
def test_malformed_variant_suffixes_fail_loudly(bad: str, vocab: Vocabulary) -> None:
    with pytest.raises((TokenizeError, LexiconError)):
        _lex(VARIANT_YAML, vocab).tokenize(bad)


def test_strokes_for_follows_the_selected_variant(vocab: Vocabulary) -> None:
    lex = _lex(VARIANT_YAML, vocab)
    assert lex.strokes_for("din") == ("na",)
    assert lex.strokes_for("din@full") == ("ta",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lexicon.py -k "variant_suffix or binds_to or strokes_for_follows" -v`
Expected: FAIL — `TokenizeError` on `"din@full"`, because `@` is not in any surface form.

- [ ] **Step 3: Add `Segment` and rewrite `tokenize`**

In `bolbox/lexicon.py`, add after the `Bol` dataclass:

```python
VARIANT_SEP = "@"


@dataclass(frozen=True)
class Segment:
    """One bol occurrence inside a token, with the realization chosen for it."""

    bol: Bol
    variant: Variant
```

Replace `tokenize` and `strokes_for` with:

> **CORRECTION (found during execution — the code below is wrong).** The variant-name
> scan shown here consumes the whole run of alphabetic characters after `@`, which
> makes this task's own `test_variant_binds_to_the_preceding_bol_in_a_multi_bol_token`
> unpassable: for `din@fullge` it swallows `fullge` as the variant name instead of
> reading `full` and resuming into `ge`. The shipped implementation instead matches the
> alpha run against **the bol's own known variant names, longest first**, falling back
> to the whole run when none match — so an unknown variant like `din@edge` still fails
> loudly naming the typo. See `bolbox/lexicon.py` as built, and the regression test
> `test_variant_suffix_prefers_the_longest_matching_variant_name`, which fails if the
> longest-first sort is reversed.

```python
    def tokenize(self, token: str) -> tuple[Segment, ...]:
        """Segment one whitespace-delimited token into bols by longest match.

        A bol may be followed by `@name` to select a non-default realization.
        The suffix binds to the bol match immediately before it and the scan
        resumes after the variant name, which is unambiguous because `@` can
        never appear inside a surface form.

        Raises TokenizeError naming the exact offset and substring that failed.
        Never drops characters and never guesses.
        """
        text = token.strip().lower()
        if not text:
            raise TokenizeError(token, 0, "")

        out: list[Segment] = []
        i = 0
        while i < len(text):
            match = self._longest_at(text, i)
            if match is None:
                raise TokenizeError(token, i, text[i:])
            bol = self.resolve(match)
            i += len(match)

            variant_name = ""
            if i < len(text) and text[i] == VARIANT_SEP:
                start = i + 1
                end = start
                while end < len(text) and text[end].isalpha():
                    end += 1
                if end == start:
                    raise TokenizeError(token, i, text[i:])
                variant_name = text[start:end]
                i = end

            out.append(Segment(bol=bol, variant=bol.variant(variant_name)))
        return tuple(out)

    def strokes_for(self, token: str) -> tuple[str, ...]:
        """Flat stroke sequence for a token. Convenience for tests and tooling."""
        return tuple(s for seg in self.tokenize(token) for s in seg.variant.strokes)
```

`bol.variant(name)` raises `LexiconError` for an unknown name, which is what the
test accepts. It is deliberately not swallowed into a silent default.

- [ ] **Step 4: Update the one caller that unpacks tokenize's result**

In `bolbox/format.py`, replace the `PlacedBol` field block (lines 126-132) with
the following. `variant` goes after `matra`, not next to `surface` where it reads
more naturally — a defaulted field cannot precede the non-defaulted `accent` and
`matra`:

```python
@dataclass(frozen=True)
class PlacedBol:
    pos: Fraction
    duration: Fraction
    surface: str
    accent: str | None
    matra: int
    variant: str = ""
    line: int = field(default=0, compare=False)
    column: int = field(default=0, compare=False)
```

Then replace the tail of `_place` (lines 202-216):

```python
    # A token may carry several bols (`dhage` -> dha, ge). They share the slot.
    segments = lexicon.tokenize(node.text)
    share = duration / len(segments)
    for index, segment in enumerate(segments):
        out.append(
            PlacedBol(
                pos=start + share * index,
                duration=share,
                surface=segment.bol.name,
                accent=node.accent,
                matra=matra,
                variant=segment.variant.name,
                line=node.line,
                column=node.column,
            )
        )
```

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS. `test_format.py` and `test_grid.py` exercise `_place` heavily;
they must stay green because `variant` defaults to `""`.

- [ ] **Step 6: Commit**

```bash
git add bolbox/lexicon.py bolbox/format.py tests/test_lexicon.py
git commit -m "Tokenizer understands din@full

All @ handling lives beside the longest-match scanner. The suffix binds to the
preceding bol match, which is unambiguous because @ can never appear inside a
surface form. An unknown variant fails loudly rather than falling back to the
default -- a typo that silently played the default would be invisible."
```

---

### Task 4: `@` survives the parser and the round-trip property

**Files:**
- Modify: `bolbox/format.py:43` (`_WORD_RE`)
- Modify: `data/compositions/FORMAT.md`
- Test: `tests/test_format.py`

**Interfaces:**
- Consumes: Task 3's tokenizer.
- Produces: composition text containing `din@full` parses; `unparse(parse(x)) == x`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_format.py` (match the file's existing import style; it
already imports `parse` and builds a `Lexicon`):

```python
VARIANT_COMPOSITION = """tal: tintal
lay: 120

dha dhin dhin dha | dha dhin dhin dha | dha tin tin ta | ta dhin dhin din@full
"""


def test_variant_notation_parses() -> None:
    comp = parse(VARIANT_COMPOSITION)
    placed = comp.flatten()
    last = placed[-1]
    assert last.surface == "din"
    assert last.variant == "full"


def test_variant_notation_round_trips_exactly() -> None:
    """The token keeps what you typed, so unparse reproduces it verbatim."""
    comp = parse(VARIANT_COMPOSITION)
    assert "din@full" in comp.unparse()
    assert parse(comp.unparse()) == comp


def test_variant_composes_with_an_accent() -> None:
    text = VARIANT_COMPOSITION.replace("din@full", "din@full!")
    comp = parse(text)
    assert comp.flatten()[-1].accent == "accent"
    assert "din@full!" in comp.unparse()


def test_unknown_variant_is_reported_at_the_column_you_typed_it() -> None:
    text = VARIANT_COMPOSITION.replace("din@full", "din@edge")
    with pytest.raises(ParseError) as exc:
        parse(text)
    assert exc.value.line == 4
    assert "edge" in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_format.py -k variant -v`
Expected: FAIL — `ParseError: expected a bol, a rest '-', or a group` at the `@`,
because `_WORD_RE` stops at it.

- [ ] **Step 3: Widen the word regex**

Replace `bolbox/format.py` line 43 with:

```python
# `@` is part of a bol token: it introduces a variant selector (`din@full`).
# Segmenting it is the tokenizer's job -- the parser only has to not stop here,
# which is why this stays permissive rather than encoding the `bol@variant`
# shape twice.
_WORD_RE = re.compile(r"[A-Za-z@]+")
```

A bare `@`, a trailing `din@`, or `din@@full` all match this regex and are then
rejected by `lexicon.tokenize`, which `_parse_token` already calls for validation
at the typed column — so the error position stays correct with no other change.

- [ ] **Step 4: Verify the ParseError path still reports the variant**

`_parse_token` catches only `TokenizeError` (lines 493-502). An unknown variant
raises `LexiconError`, which would escape as a 500 rather than a positioned parse
error. Widen the catch:

```python
    try:
        lexicon.tokenize(word)
    except TokenizeError as exc:
        raise ParseError(
            f"cannot segment {word!r} at offset {exc.offset}: "
            f"no known bol starts at {exc.offending!r}",
            line_no,
            column,
            word,
        ) from exc
    except LexiconError as exc:
        # An unknown @variant. Positioned like any other bol error rather than
        # escaping as a 500 from the server's generic handler.
        raise ParseError(str(exc), line_no, column, word) from exc
```

Add `LexiconError` to the imports at `bolbox/format.py:33`:

```python
from .errors import LexiconError, ParseError, TokenizeError
```

- [ ] **Step 5: Extend the round-trip property test**

The hypothesis strategy at `tests/test_format.py:235-248` draws bol tokens from a
`SAFE_BOLS` list. Replace line 232:

```python
# `din@full` must survive the round trip exactly, same as any other token: the
# variant rides inside Token.text, so this asserts the parser neither drops nor
# normalises it -- which is exactly what a naive word regex would do. `tha` is
# here because it shares a stroke with `na`, so a bug that canonicalised bols to
# their strokes would show up as a round-trip failure rather than silently.
SAFE_BOLS = [
    "dha", "dhin", "ta", "tha", "na", "ti", "te", "re", "ki", "ka", "ge",
    "tirakita", "din", "din@full",
]
```

Both properties in the file now exercise variants: the unparse→parse identity,
and duration-sums-to-cycle. The second is a real check rather than a formality,
because `din@full` has a different stroke count from `din` in general, which
changes sub-slot division inside a matra.

- [ ] **Step 6: Document the syntax**

In `data/compositions/FORMAT.md`, in the `## Bols` section after the longest-match
table, add:

```markdown
### Variants

Some bols have more than one physical realization. `din` is struck full-handed
or with one finger on the edge, and it is recited identically either way — so
the recitation cannot tell you which, and neither can any transcription model.
Pick one explicitly with `@`:

```
din          the default realization, from data/lexicon.yaml
din@full     a named non-default realization
din@full!    composes with accents; the accent stays outermost
```

The suffix binds to the bol immediately before it, so in a multi-bol token
`din@fullge` is `din` (full) followed by `ge` (default).

An unknown variant name is a parse error at the column you typed it. It never
falls back to the default — a typo that silently played the default would be
invisible.
```

Also update the `gharana` row's note, which currently says "once variants exist":

```markdown
| `gharana` | no | Free text. Reserved: will select a default variant set. Not yet implemented. |
```

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS, including both hypothesis properties.

- [ ] **Step 8: Commit**

```bash
git add bolbox/format.py data/compositions/FORMAT.md tests/test_format.py
git commit -m "Parse and round-trip din@full

The variant rides inside Token.text, so unparse reproduces it for free. An
unknown variant now raises a positioned ParseError instead of escaping as a
LexiconError -- the server's generic handler would have turned that into an
unpositioned 500."
```

---

### Task 5: Variant reaches `Event` and the wire

**Files:**
- Modify: `bolbox/pattern.py:45-77` (`Event`), `bolbox/pattern.py:160-180` (`to_dict` / `from_dict`)
- Modify: `bolbox/grid.py:70-98` (`_expand`)
- Modify: `web/src/types.ts:14-32`
- Test: `tests/test_grid.py` (there is no `tests/test_pattern.py`; `Pattern` round-trip
  assertions live in `test_grid.py`, so add `from bolbox.pattern import Pattern` to
  its imports if it is not already there)

**Interfaces:**
- Consumes: Task 3's `PlacedBol.variant`.
- Produces: `Event.variant: str` (default `""`, `compare=False`); `"variant"` key in `Pattern.to_dict()` events; `PatternEventJSON.variant?: string` in TypeScript.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_grid.py`:

```python
def test_variant_selects_the_strokes_and_reaches_the_event() -> None:
    comp = parse(
        "tal: tintal\nlay: 120\n\n"
        "din din@full - - | - - - - | - - - - | - - - -\n"
    )
    pattern = grid(comp)
    default, chosen = pattern.events[0], pattern.events[1]

    assert default.source_bol == "din" and default.variant == ""
    assert default.stroke == "na"          # the default realization

    assert chosen.source_bol == "din" and chosen.variant == "full"
    assert chosen.stroke == "ta"           # the selected one


def test_variant_survives_the_dict_round_trip() -> None:
    comp = parse(
        "tal: tintal\nlay: 120\n\n"
        "din@full - - - | - - - - | - - - - | - - - -\n"
    )
    pattern = grid(comp)
    assert pattern.to_dict()["events"][0]["variant"] == "full"
    assert Pattern.from_dict(pattern.to_dict()) == pattern


def test_events_without_a_variant_key_still_load() -> None:
    """Patterns stored before variants existed must not fail to load."""
    payload = grid(parse(
        "tal: tintal\nlay: 120\n\ndha - - - | - - - - | - - - - | - - - -\n"
    )).to_dict()
    for event in payload["events"]:
        del event["variant"]
    assert Pattern.from_dict(payload).events[0].variant == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_grid.py -k variant -v`
Expected: FAIL — `AttributeError: 'Event' object has no attribute 'variant'`.

- [ ] **Step 3: Add the field to `Event`**

In `bolbox/pattern.py`, in the `Event` dataclass after `bol_offset` (line 60):

```python
    bol_offset: int = field(default=0, compare=False)
    variant: str = field(default="", compare=False)
```

Extend the class docstring:

```python
    ``variant`` names the physical realization chosen for ``source_bol``, empty
    for the default. It is here rather than derivable from ``stroke`` because
    two realizations can share a stroke, and because a kit may later key a
    sample on `din@full` specifically.
```

- [ ] **Step 4: Carry it through `to_dict` / `from_dict`**

In `bolbox/pattern.py`, in the `to_dict` event mapping (around line 165):

```python
                    "bol_offset": e.bol_offset,
                    "variant": e.variant,
```

And in `from_dict` (around line 179):

```python
                bol_offset=int(e.get("bol_offset", 0)),
                variant=str(e.get("variant", "")),
```

`.get` with a default is what makes a stored pattern from before this change load.

- [ ] **Step 5: Select the variant in `grid._expand`**

In `bolbox/grid.py`, replace the head of `_expand` (lines 70-72):

```python
def _expand(placed: PlacedBol, tal: Tal, lexicon: Lexicon) -> list[Event]:
    bol = lexicon.resolve(placed.surface)
    realization = bol.variant(placed.variant)
    velocity = _velocity(placed, tal)

    if realization.simultaneous:
```

Then replace every remaining `bol.strokes` with `realization.strokes`, and add
`variant=placed.variant` to both `Event(...)` constructions. The simultaneous
branch becomes:

```python
        return [
            Event(
                pos=placed.pos,
                stroke=stroke,
                velocity=velocity,
                source_bol=bol.name,
                bol_offset=index,
                variant=placed.variant,
            )
            for index, stroke in enumerate(realization.strokes)
        ]

    share = placed.duration / len(realization.strokes)
    return [
        Event(
            pos=placed.pos + share * index,
            stroke=stroke,
            velocity=velocity,
            source_bol=bol.name,
            bol_offset=index,
            variant=placed.variant,
        )
        for index, stroke in enumerate(realization.strokes)
    ]
```

- [ ] **Step 6: Add the field to the wire type**

In `web/src/types.ts`, inside `PatternEventJSON` after `bol_offset`:

```ts
  /**
   * The physical realization chosen for `source_bol`, empty for the default.
   * Some bols can be struck more than one way (`din` full-handed vs one finger
   * on the edge) and are recited identically either way, so the choice cannot
   * come from the audio and travels here instead. Optional: older payloads
   * predate the field.
   */
  readonly variant?: string;
```

- [ ] **Step 7: Run both suites**

Run: `python -m pytest -v`
Expected: PASS.

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no type errors, 51 tests pass.

- [ ] **Step 8: Commit**

```bash
git add bolbox/pattern.py bolbox/grid.py web/src/types.ts tests/test_grid.py
git commit -m "Carry the selected variant through to Event and the wire

grid._expand resolves the realization rather than reading Bol.strokes, so a
non-default variant produces different strokes. Both to_dict and from_dict use
a default so patterns stored before this change still load."
```

---

### Task 6: Expose variants from the API

`din` itself landed in Task 2, because Tasks 4 and 5 parse it. What is left is
making variants visible to clients, and correcting the note in the kit script
that says bolbox has no `din` bol.

**Files:**
- Modify: `bolbox/server.py:113-121` (the `/api/vocabulary` bols block)
- Modify: `scripts/make_deolekar_kit.py:159-165` (the `UNUSED` note)
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: Tasks 2-5.
- Produces: each bol in `/api/vocabulary` carries a `variants` array, default first, alongside the existing flattened `strokes`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server.py`. Note it uses a **module-level** `client =
TestClient(app)` at line 19, not a fixture — so these take no parameter:

```python
def test_vocabulary_exposes_variants() -> None:
    body = client.get("/api/vocabulary").json()
    din = next(b for b in body["bols"] if b["name"] == "din")
    assert [v["name"] for v in din["variants"]] == ["kinar", "full"]
    assert din["strokes"] == din["variants"][0]["strokes"]  # default first

    # A client that does not care about variants reads what it read before.
    ge = next(b for b in body["bols"] if b["name"] == "ge")
    assert len(ge["variants"]) == 1
    assert ge["variants"][0]["name"] == ""
    assert ge["strokes"] == ["ge"]


def test_vocabulary_lists_tha_and_na_separately() -> None:
    names = [b["name"] for b in client.get("/api/vocabulary").json()["bols"]]
    assert "tha" in names and "na" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_server.py -k "variants or tha" -v`
Expected: FAIL — `KeyError: 'variants'`. (`test_vocabulary_lists_tha_and_na_separately`
should already pass; Task 1 added `tha`.)

- [ ] **Step 3: Expose variants from `/api/vocabulary`**

In `bolbox/server.py`, replace the `bols` list comprehension (lines 113-121):

```python
        "bols": [
            {
                "name": bol.name,
                # The default realization, flattened -- so a client that does
                # not care about variants reads exactly what it read before.
                "strokes": list(bol.strokes),
                "simultaneous": bol.simultaneous,
                "verify": bol.verify,
                "variants": [
                    {
                        "name": v.name,
                        "strokes": list(v.strokes),
                        "simultaneous": v.simultaneous,
                        "verify": v.verify,
                        "description": v.description,
                    }
                    for v in bol.variants
                ],
            }
            for bol in _LEXICON
        ],
```

- [ ] **Step 4: Update the kit script's `UNUSED` note**

In `scripts/make_deolekar_kit.py`, replace the `Di` entry (lines 161-165):

```python
    "Di": "Pure dayan -- under 2% of its energy is below 200Hz, against 86% for "
          "`Dh` and 75% for `Da`. There is no bayan in it, so despite the name "
          "it is a `din`, not a `dhin`, and it cannot be a composite. Left out "
          "when bolbox had no `din` bol. It has one now -- added because the "
          "instrument has it, not to consume this sample -- so wiring `Di` in "
          "as a `din` realization is open work. Do it after recording your own "
          "kit, and only once the din variants stop being marked `verify`.",
```

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS. The README's "things that need your ear" snippet will now also
list `din` — that is correct and wanted.

- [ ] **Step 6: Commit**

```bash
git add bolbox/server.py scripts/make_deolekar_kit.py tests/test_server.py
git commit -m "Expose bol variants from /api/vocabulary

Each bol carries a variants array, default first, alongside the flattened
default strokes -- so a client that does not care about variants reads exactly
what it read before.

Also corrects the Di note in make_deolekar_kit.py, which said bolbox has no din
bol. It has one now, added because the instrument has it rather than to consume
that sample, which is the distinction the note was drawing."
```

---

### Task 7: Close the coverage gap that let the tirakita bug ship

`web/src/main.ts` has no unit coverage. That is why a grid label repeated four
times reached the browser while `midi.py` had the correct rule (`bol_offset == 0`)
and a test for it. The fix is already applied; this makes it stay fixed and
extends it to carry the variant.

**Files:**
- Create: `web/src/grid-labels.ts`, `web/src/grid-labels.test.ts`
- Modify: `web/src/main.ts:122-185` (`renderPatternView`)

**Interfaces:**
- Consumes: Task 5's `PatternEventJSON.variant`.
- Produces: `bolLabels(events: readonly PatternEventJSON[]): Map<number, string>` — matra position (as a `number`) to the joined label for that position.

- [ ] **Step 1: Write the failing test**

Create `web/src/grid-labels.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { bolLabels } from "./grid-labels";
import type { PatternEventJSON } from "./types";

const ev = (
  pos: [number, number],
  stroke: string,
  source_bol: string,
  bol_offset: number,
  variant = "",
): PatternEventJSON => ({ pos, stroke, velocity: 100, source_bol, bol_offset, variant });

describe("bolLabels", () => {
  it("prints a compound bol once, not once per stroke", () => {
    // tirakita is ONE word across FOUR positions. Keying on position alone
    // printed it four times -- the bug this test exists for.
    const labels = bolLabels([
      ev([0, 1], "te", "tirakita", 0),
      ev([1, 4], "re", "tirakita", 1),
      ev([1, 2], "ki", "tirakita", 2),
      ev([3, 4], "ta", "tirakita", 3),
    ]);
    expect([...labels.values()]).toEqual(["tirakita"]);
  });

  it("prints a composite bol once, not once per simultaneous stroke", () => {
    // dha is one word across two strokes at ONE position.
    const labels = bolLabels([
      ev([0, 1], "ge", "dha", 0),
      ev([0, 1], "na", "dha", 1),
    ]);
    expect(labels.get(0)).toBe("dha");
  });

  it("joins distinct bols that share a matra", () => {
    const labels = bolLabels([
      ev([0, 1], "ge", "dha", 0),
      ev([1, 2], "ge", "ge", 0),
    ]);
    expect(labels.get(0)).toBe("dha");
    expect(labels.get(0.5)).toBe("ge");
  });

  it("shows the variant so the grid reflects what was written", () => {
    const labels = bolLabels([ev([0, 1], "ta", "din", 0, "full")]);
    expect(labels.get(0)).toBe("din@full");
  });

  it("omits the variant suffix for the default realization", () => {
    const labels = bolLabels([ev([0, 1], "na", "din", 0, "")]);
    expect(labels.get(0)).toBe("din");
  });

  it("falls back to the stroke when there is no source_bol", () => {
    const labels = bolLabels([ev([0, 1], "ge", "", 0)]);
    expect(labels.get(0)).toBe("ge");
  });

  it("treats a missing bol_offset as the start of a bol", () => {
    const e = { pos: [0, 1], stroke: "ge", velocity: 100, source_bol: "ge" } as
      unknown as PatternEventJSON;
    expect(bolLabels([e]).get(0)).toBe("ge");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/grid-labels.test.ts`
Expected: FAIL — `Cannot find module './grid-labels'`.

- [ ] **Step 3: Create the module**

Create `web/src/grid-labels.ts`:

```ts
/**
 * Deriving grid labels from pattern events.
 *
 * Extracted from main.ts so it can be tested. It was inline DOM code, which is
 * why it shipped printing `tirakita` four times: midi.py had the correct rule
 * and a test for it, and the browser had neither.
 */

import type { PatternEventJSON } from "./types";

/**
 * One label per BOL, keyed by its matra position.
 *
 * `bol_offset === 0` is the stroke that starts a bol, and keying on it collapses
 * both shapes a bol can take: a composite `dha` is one word across two strokes
 * at ONE position, and a compound `tirakita` is one word across four DIFFERENT
 * positions. Position alone only collapses the first.
 */
export function bolLabels(events: readonly PatternEventJSON[]): Map<number, string> {
  const labels = new Map<number, string>();
  for (const e of events) {
    if ((e.bol_offset ?? 0) !== 0) continue;
    const den = e.pos[1] === 0 ? 1 : e.pos[1];
    const at = e.pos[0] / den;
    const label = labelFor(e);
    const existing = labels.get(at);
    // Off-grid positions (tuplets) still get a cell on their matra, joined.
    if (existing === undefined) labels.set(at, label);
    else if (!existing.split(" ").includes(label)) labels.set(at, `${existing} ${label}`);
  }
  return labels;
}

function labelFor(e: PatternEventJSON): string {
  const bol = e.source_bol || e.stroke;
  // Non-default realizations are shown as written. `din` and `din@full` are
  // different sounds, so a grid that rendered both as `din` would be lying.
  return e.variant ? `${bol}@${e.variant}` : bol;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/grid-labels.test.ts`
Expected: PASS, 7 tests.

- [ ] **Step 5: Use it from main.ts**

In `web/src/main.ts`, add to the imports:

```ts
import { bolLabels } from "./grid-labels";
```

Then replace the whole label-building block inside `renderPatternView` (the
comment plus the `const bols = new Map<number, string>();` loop) with:

```ts
  const bols = bolLabels(p.events);
```

Leave the rest of `renderPatternView` untouched — the cell loop already reads
`bols` and is unchanged.

- [ ] **Step 6: Run everything**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no type errors; 58 tests pass (51 existing + 7 new).

- [ ] **Step 7: Commit**

```bash
git add web/src/grid-labels.ts web/src/grid-labels.test.ts web/src/main.ts
git commit -m "Extract and test grid label derivation

main.ts had zero unit coverage, which is why a label repeated four times
shipped while midi.py had the correct bol_offset == 0 rule and a test for it.
Now tested, and extended to show non-default variants -- din and din@full are
different sounds, so rendering both as din would be lying."
```

---

## What this plan does not do

Carried to the capture-tool plan (`§2` and `§3` of the spec):

- The `Transcriber` interface and `NullTranscriber`.
- Recording capture, storage, endpoints, IndexedDB buffering.
- `bolbox dataset` coverage reporting.
- Record-mode UI, including the per-bol variant control.

Carried to their own specs entirely:

- The acoustic model, streaming decode, choke groups.
- Wiring the `Di` sample class into `kits/deolekar-tabla/` as a `din` realization.
  Blocked on the `din` variants losing their `verify` flags, which needs your ear.
- Selecting a default variant set from the `gharana` header. Needs a real
  catalogue of variants first; `din` is currently the only one.
