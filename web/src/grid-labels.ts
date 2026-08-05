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
