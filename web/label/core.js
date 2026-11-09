// Pure logic for the labeling page: completion, the word under the cursor,
// and the keyboard map. No DOM, no audio -- so it is unit-tested
// (core.test.js) and the page script stays a thin shell around it.
//
// Plain JS rather than TypeScript on purpose: the labeling page is served
// straight from web/label/ by `bolbox label`, with no build step, so a fresh
// clone can label without `npm install`.

/**
 * Build the completion dictionary from GET /api/vocabulary.
 * Canonical names first, then `bol@variant` for non-default realizations,
 * then aliases (alternate spellings) labelled with what they resolve to.
 */
export function buildDictionary(vocab) {
  const out = [];
  const seen = new Set();
  const push = (text, kind, detail) => {
    if (seen.has(text)) return;
    seen.add(text);
    out.push({ text, kind, detail });
  };
  for (const bol of vocab.bols) {
    const strokes = bol.strokes.join(bol.simultaneous ? "+" : " ");
    push(bol.name, "bol", strokes);
  }
  for (const bol of vocab.bols) {
    for (const v of bol.variants ?? []) {
      if (!v.name || v === bol.variants[0]) continue;
      push(`${bol.name}@${v.name}`, "variant", v.strokes.join(" "));
    }
  }
  const canonical = new Set(vocab.bols.map((b) => b.name));
  for (const form of vocab.surface_forms ?? []) {
    if (!canonical.has(form)) push(form, "alias", "");
  }
  return out;
}

/** Boundaries of the word the cursor is in (or just after). */
export function wordAt(text, cursor) {
  const isSep = (ch) => /[\s|{},]/.test(ch);
  let start = cursor;
  while (start > 0 && !isSep(text[start - 1])) start--;
  let end = cursor;
  while (end < text.length && !isSep(text[end])) end++;
  return { start, end, word: text.slice(start, cursor) };
}

/**
 * Completions for a typed prefix, best first.
 * Accent marks are not part of a bol, so `dha!` completes as `dha`.
 */
export function complete(dictionary, prefix, limit = 6) {
  const p = prefix.toLowerCase().replace(/[!.]+$/, "");
  if (!p || p === "-") return [];
  const rank = { bol: 0, variant: 1, alias: 2 };
  return dictionary
    .filter((e) => e.text.startsWith(p) && e.text !== p)
    .sort(
      (a, b) =>
        rank[a.kind] - rank[b.kind] ||
        a.text.length - b.text.length ||
        a.text.localeCompare(b.text),
    )
    .slice(0, limit);
}

/** Replace the word under the cursor with `choice`, then a space. */
export function applyCompletion(text, cursor, choice) {
  const { start, end } = wordAt(text, cursor);
  const before = text.slice(0, start);
  const after = text.slice(end);
  // Reuse an existing separator rather than doubling it.
  const insert = choice + (after.startsWith(" ") ? "" : " ");
  const value = before + insert + after;
  const caret = before.length + choice.length + 1;
  return { value, cursor: Math.min(caret, value.length) };
}

/**
 * The keyboard map. Every action has a modifier or is Enter/Esc, so typing a
 * label never triggers one. `code` rather than `key` for Alt chords, because
 * on macOS Alt+X types "≈" and `key` reports that.
 */
export function actionFor(e, { suggestionsOpen = false } = {}) {
  if (suggestionsOpen) {
    if (e.key === "Tab" || (e.key === "ArrowRight" && !e.altKey)) return "accept";
    if (e.key === "ArrowDown" && !e.altKey) return "suggestNext";
    if (e.key === "ArrowUp" && !e.altKey) return "suggestPrev";
    if (e.key === "Escape") return "closeSuggestions";
  }
  if (e.key === "Enter" && !e.shiftKey && !e.altKey) return "saveNext";
  if (e.key === "Escape") return "replay";
  if (e.altKey && e.code === "Space") return "togglePlay";
  if (e.altKey && (e.code === "ArrowRight" || e.code === "BracketRight")) return "next";
  if (e.key === "PageDown") return "next";
  if (e.altKey && (e.code === "ArrowLeft" || e.code === "BracketLeft")) return "prev";
  if (e.key === "PageUp") return "prev";
  if (e.altKey && e.code === "KeyX") return "skip";
  if (e.altKey && e.code === "ArrowDown") return "draftNext";
  if (e.altKey && e.code === "ArrowUp") return "draftPrev";
  if (e.altKey && e.code === "KeyC") return "clear";
  if (e.altKey && e.code === "KeyS") return "slower";
  return null;
}

/** Index of the next clip still needing a label, after `from`. -1 if none. */
export function nextUnlabelled(queue, from) {
  for (let i = from + 1; i < queue.length; i++) {
    if (!queue[i].bols.trim() && !queue[i].skipped) return i;
  }
  return -1;
}

/** Queue order: when it was recorded, then its original file name. */
export function queueOrder(recordings) {
  const key = (r) => [r.recorded_at, r.source?.name ?? "", r.id];
  return [...recordings].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    for (let i = 0; i < ka.length; i++) {
      if (ka[i] < kb[i]) return -1;
      if (ka[i] > kb[i]) return 1;
    }
    return 0;
  });
}

export function median(xs) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
